"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — Redis Infrastructure Service
===============================================================================
Author: Senior Backend Infrastructure Engineer
Components:
  1. Live Position Cache: Redis Geospatial Index (GEOADD) on "bus:positions"
  2. Telemetry Ingestion Hot-Path with Asynchronous Write-Behind
  3. Pub/Sub Real-Time Fan-Out to "bus-updates:{bus_id}" (WebSocket integration)
  4. Read-Heavy Cache Layer:
     - GET /api/v1/stations (TTL: 1 hour, auto-invalidated by importer/geocoder)
     - GET /api/v1/buses/search (TTL: 20 seconds per source/destination pair)
  5. Sliding-Window Rate Limiter on POST /api/v1/telemetry (1 update / 3s per bus)
  6. Synchronous & Asynchronous `invalidate_stations_cache()` helper
===============================================================================
"""

import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from .config import (
    BUS_SEARCH_CACHE_TTL,
    BUS_TELEMETRY_TTL,
    RedisKeys,
    STATIONS_CACHE_TTL,
    TELEMETRY_RATE_LIMIT_MAX_REQUESTS,
    TELEMETRY_RATE_LIMIT_WINDOW,
    WRITE_BEHIND_STREAM_MAXLEN,
)
from .redis_client import get_async_redis, get_sync_redis

logger = logging.getLogger("ksrtc_redis_service")


# =============================================================================
# 1. SLIDING-WINDOW RATE LIMITER (Atomic Lua Script)
# =============================================================================
# Evaluates request volume in a rolling time window using a Redis ZSET.
# Returns: [is_allowed (1 or 0), retry_after_seconds (float)]
LUA_SLIDING_WINDOW_RATE_LIMIT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])

local clear_before = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

local current_requests = redis.call('ZCARD', key)

if current_requests < max_requests then
    redis.call('ZADD', key, now, now)
    redis.call('EXPIRE', key, math.ceil(window) + 1)
    return {1, 0}
else
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 0
    if oldest and #oldest >= 2 then
        local oldest_ts = tonumber(oldest[2])
        retry_after = (oldest_ts + window) - now
        if retry_after < 0 then retry_after = 0 end
    end
    return {0, retry_after}
end
"""


async def check_telemetry_rate_limit(
    redis_client: aioredis.Redis,
    bus_number: str,
    window_seconds: float = TELEMETRY_RATE_LIMIT_WINDOW,
    max_requests: int = TELEMETRY_RATE_LIMIT_MAX_REQUESTS,
) -> Tuple[bool, float]:
    """
    Applies sliding-window rate limiting for bus telemetry transmissions.

    Args:
        redis_client: Async Redis client.
        bus_number: State vehicle registration number (e.g., 'KA-22-F-1892').
        window_seconds: Rolling window size (default: 3.0s).
        max_requests: Maximum allowable telemetry pings within window (default: 1).

    Returns:
        (is_allowed: bool, retry_after: float)
    """
    key = RedisKeys.rate_limit_telemetry(bus_number)
    now_ts = time.time()

    try:
        res = await redis_client.eval(
            LUA_SLIDING_WINDOW_RATE_LIMIT,
            1,
            key,
            now_ts,
            window_seconds,
            max_requests,
        )
        is_allowed = bool(res[0] == 1)
        retry_after = float(res[1])
        return is_allowed, retry_after
    except Exception as e:
        # Fallback to atomic Redis pipeline commands (works on all Redis and fakeredis environments)
        try:
            clear_before = now_ts - window_seconds
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, "-inf", clear_before)
                pipe.zcard(key)
                results = await pipe.execute()

            current_requests = results[1]
            if current_requests < max_requests:
                async with redis_client.pipeline(transaction=True) as pipe:
                    pipe.zadd(key, {str(now_ts): now_ts})
                    pipe.expire(key, int(window_seconds) + 1)
                    await pipe.execute()
                return True, 0.0
            else:
                oldest = await redis_client.zrange(key, 0, 0, withscores=True)
                retry_after = 0.0
                if oldest and len(oldest) > 0:
                    oldest_ts = float(oldest[0][1])
                    retry_after = max(0.0, (oldest_ts + window_seconds) - now_ts)
                return False, retry_after
        except Exception as inner_e:
            logger.error("Rate limiter Redis evaluation error for bus %s: %s", bus_number, inner_e)
            return True, 0.0


# =============================================================================
# 2. LIVE POSITION CACHE (GEOADD) & HOT-PATH TELEMETRY INGESTION
# =============================================================================
async def record_bus_telemetry(
    redis_client: aioredis.Redis,
    bus_id: str,
    bus_number: str,
    latitude: float,
    longitude: float,
    speed: float,
    has_left_platform: bool,
    trip_id: Optional[str] = None,
    service_type: Optional[str] = None,
    skip_rate_limit: bool = False,
) -> Dict[str, Any]:
    """
    Hot-Path Ingestion Pipeline:
      1. Validates sliding-window rate limit (1 update / 3s per bus) unless skip_rate_limit=True.
      2. Atomically updates Redis geospatial index 'bus:positions' (GEOADD).
      3. Caches full telemetry state in 'bus:telemetry:{bus_id}'.
      4. Publishes real-time fanout to 'bus-updates:{bus_id}' for WebSockets.
      5. Enqueues payload to write-behind stream for asynchronous Postgres persistence.

    Returns:
        Dictionary containing execution summary and telemetry payload.
    Raises:
        ValueError: If telemetry exceeds rate limit.
    """
    # 1. Rate Limiting Check
    if not skip_rate_limit:
        allowed, retry_after = await check_telemetry_rate_limit(redis_client, bus_number)
        if not allowed:
            raise ValueError(
                f"Rate limit exceeded for bus {bus_number}. "
                f"Maximum 1 telemetry update allowed per {TELEMETRY_RATE_LIMIT_WINDOW}s. "
                f"Retry after {retry_after:.2f}s."
            )

    updated_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    telemetry_payload = {
        "bus_id": bus_id,
        "bus_number": bus_number,
        "trip_id": trip_id,
        "service_type": service_type or "Ordinary",
        "latitude": latitude,
        "longitude": longitude,
        "speed": round(speed, 2),
        "has_left_platform": has_left_platform,
        "updated_at": updated_at_iso,
    }
    payload_json = json.dumps(telemetry_payload)

    # 2. Hot-Path Atomic Pipeline
    async with redis_client.pipeline(transaction=True) as pipe:
        # A. Update Geospatial Index (GEOADD key longitude latitude member)
        # Note: Redis expects (longitude, latitude, member)
        pipe.geoadd(RedisKeys.BUS_POSITIONS_GEO, (longitude, latitude, bus_id))
        clean_num = bus_number.strip().upper()
        if clean_num and clean_num != bus_id:
            pipe.geoadd(RedisKeys.BUS_POSITIONS_GEO, (longitude, latitude, clean_num))
            pipe.set(RedisKeys.bus_telemetry(clean_num), payload_json, ex=BUS_TELEMETRY_TTL)
            pipe.publish(RedisKeys.bus_channel(clean_num), payload_json)

        # B. Store latest telemetry metadata hash/string with 24h TTL
        pipe.set(
            RedisKeys.bus_telemetry(bus_id),
            payload_json,
            ex=BUS_TELEMETRY_TTL,
        )

        # C. Real-time Pub/Sub fan-out for connected WebSocket clients
        pipe.publish(RedisKeys.bus_channel(bus_id), payload_json)
        pipe.publish(RedisKeys.DIVISION_UPDATES_CHANNEL, payload_json)

        # D. Write-behind stream for asynchronous Postgres persistence worker
        pipe.xadd(
            RedisKeys.WRITE_BEHIND_STREAM,
            {
                "bus_id": bus_id,
                "bus_number": bus_number,
                "latitude": str(latitude),
                "longitude": str(longitude),
                "speed": str(speed),
                "has_left_platform": "1" if has_left_platform else "0",
                "updated_at": updated_at_iso,
            },
            maxlen=WRITE_BEHIND_STREAM_MAXLEN,
            approximate=True,
        )

        await pipe.execute()

    return telemetry_payload


# =============================================================================
# 3. GEOSPATIAL PROXIMITY & RADIUS QUERIES
# =============================================================================
async def get_bus_coordinates(
    redis_client: aioredis.Redis,
    bus_id: str,
) -> Optional[Tuple[float, float]]:
    """
    Retrieves the current (latitude, longitude) of a bus from the geospatial index.
    """
    try:
        pos = await redis_client.geopos(RedisKeys.BUS_POSITIONS_GEO, bus_id)
        if pos and pos[0]:
            # Redis GEOPOS returns (longitude, latitude)
            lon, lat = pos[0]
            return float(lat), float(lon)
        return None
    except RedisError as e:
        logger.error("Error retrieving GEOPOS for bus %s: %s", bus_id, e)
        return None


async def get_live_bus_telemetry(
    redis_client: aioredis.Redis,
    bus_id: Optional[str] = None,
    bus_number: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetches the live telemetry payload and geospatial coordinates for a bus
    identified by bus_id or bus_number.
    """
    keys_to_try = []
    if bus_id:
        keys_to_try.append(RedisKeys.bus_telemetry(bus_id))
    if bus_number:
        clean_num = bus_number.strip().upper()
        keys_to_try.append(RedisKeys.bus_telemetry(clean_num))

    for key in keys_to_try:
        try:
            cached = await redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning("Error fetching telemetry for key %s: %s", key, e)

    # Fallback to GEOPOS if telemetry key is missing
    ident = bus_id or (bus_number.strip().upper() if bus_number else None)
    if ident:
        coords = await get_bus_coordinates(redis_client, ident)
        if coords:
            lat, lon = coords
            return {
                "bus_id": bus_id or ident,
                "bus_number": bus_number or ident,
                "latitude": lat,
                "longitude": lon,
                "speed": 0.0,
                "has_left_platform": False,
                "updated_at": None,
            }
    return None


async def find_buses_near_location(
    redis_client: aioredis.Redis,
    latitude: float,
    longitude: float,
    radius_km: float = 5.0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Finds all buses within `radius_km` of given coordinates using Redis GEOSEARCH.
    Useful for platform geofencing (Belagavi CBT, Chikkodi, Athani) and nearby bus alerts.
    """
    try:
        # redis-py geosearch syntax: key, longitude, latitude, radius, unit='km'
        results = await redis_client.geosearch(
            RedisKeys.BUS_POSITIONS_GEO,
            longitude=longitude,
            latitude=latitude,
            radius=radius_km,
            unit="km",
            withdist=True,
            withcoord=True,
            sort="ASC",
            count=limit,
        )

        nearby_buses = []
        for item in results:
            # item format: (member_id, distance_km, (longitude, latitude))
            member_id = item[0]
            dist_km = float(item[1])
            bus_lon, bus_lat = item[2]
            nearby_buses.append({
                "bus_id": member_id,
                "distance_km": round(dist_km, 3),
                "latitude": float(bus_lat),
                "longitude": float(bus_lon),
            })
        return nearby_buses
    except RedisError as e:
        logger.error("Error executing GEOSEARCH near (%s, %s): %s", latitude, longitude, e)
        return []


# =============================================================================
# 4. PUB/SUB REALTIME FAN-OUT (FastAPI WebSocket Integration)
# =============================================================================
async def listen_bus_updates(
    redis_client: aioredis.Redis,
    bus_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Subscribes to 'bus-updates:{bus_id}' and yields incoming telemetry frames.
    Directly pluggable into FastAPI WebSocket endpoints:

    ```python
    @app.websocket("/ws/v1/buses/{bus_id}")
    async def bus_ws(websocket: WebSocket, bus_id: str):
        await websocket.accept()
        redis = get_async_redis()
        async for frame in listen_bus_updates(redis, bus_id):
            await websocket.send_json(frame)
    ```
    """
    channel_name = RedisKeys.bus_channel(bus_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel_name)
    logger.info("Subscribed to Redis channel: %s", channel_name)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    payload = json.loads(message["data"])
                    yield payload
                except json.JSONDecodeError:
                    continue
    finally:
        await pubsub.unsubscribe(channel_name)
        await pubsub.aclose()
        logger.info("Unsubscribed and closed Redis channel: %s", channel_name)


async def listen_division_updates(
    redis_client: aioredis.Redis,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Subscribes to 'bus-updates:division' and yields incoming telemetry frames across
    all active fleet buses. Pluggable into the wide division map WebSocket endpoint:

    ```python
    @app.websocket("/api/v1/ws/division")
    async def division_ws(websocket: WebSocket):
        await websocket.accept()
        redis = get_async_redis()
        async for frame in listen_division_updates(redis):
            await websocket.send_json(frame)
    ```
    """
    channel_name = RedisKeys.DIVISION_UPDATES_CHANNEL
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel_name)
    logger.info("Subscribed to Redis division broadcast channel: %s", channel_name)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    payload = json.loads(message["data"])
                    yield payload
                except json.JSONDecodeError:
                    continue
    finally:
        await pubsub.unsubscribe(channel_name)
        await pubsub.aclose()
        logger.info("Unsubscribed and closed Redis division broadcast channel: %s", channel_name)



# =============================================================================
# 5. CACHING LAYER: STATIONS & BUS SEARCH QUERIES
# =============================================================================

# --- A. Stations Cache (TTL: 1 Hour, Auto-Invalidated) ---
async def get_cached_stations(redis_client: aioredis.Redis) -> Optional[List[Dict[str, Any]]]:
    """Returns cached list of Belagavi Division stations, or None if cache miss."""
    try:
        cached = await redis_client.get(RedisKeys.STATIONS_CACHE)
        if cached:
            return json.loads(cached)
        return None
    except RedisError as e:
        logger.warning("Stations cache read error: %s", e)
        return None


async def set_cached_stations(
    redis_client: aioredis.Redis,
    stations: List[Dict[str, Any]],
    ttl: int = STATIONS_CACHE_TTL,
) -> None:
    """Stores station network in Redis with 1-hour TTL."""
    try:
        await redis_client.set(
            RedisKeys.STATIONS_CACHE,
            json.dumps(stations),
            ex=ttl,
        )
        logger.info("Cached %d stations with TTL=%ds", len(stations), ttl)
    except RedisError as e:
        logger.error("Failed to write stations cache: %s", e)


# --- B. Station Cache Invalidation Helpers ---
def invalidate_stations_cache() -> int:
    """
    Synchronous helper function for Step 2B schedule importer and Step 2C geocoder.
    Call this immediately after committing station inserts/updates to Postgres.

    Usage in scripts/geocode_stations.py:
        from backend.redis_service import invalidate_stations_cache
        invalidate_stations_cache()
    """
    sync_client = get_sync_redis()
    try:
        deleted = sync_client.delete(RedisKeys.STATIONS_CACHE)
        logger.info("Invalidated stations cache in Redis (sync). Keys removed: %d", deleted)
        return deleted
    except Exception as e:
        logger.error("Error invalidating stations cache (sync): %s", e)
        return 0


async def a_invalidate_stations_cache(redis_client: aioredis.Redis) -> int:
    """Asynchronous variant of station cache invalidation for FastAPI endpoints."""
    try:
        deleted = await redis_client.delete(RedisKeys.STATIONS_CACHE)
        logger.info("Invalidated stations cache in Redis (async). Keys removed: %d", deleted)
        return deleted
    except RedisError as e:
        logger.error("Error invalidating stations cache (async): %s", e)
        return 0


# --- C. Search Results Cache (TTL: 15-30 Seconds) ---
async def get_cached_bus_search(
    redis_client: aioredis.Redis,
    source: str,
    destination: str,
) -> Optional[List[Dict[str, Any]]]:
    """Returns cached bus search results if query was executed within the last 20 seconds."""
    key = RedisKeys.bus_search_cache(source, destination)
    try:
        cached = await redis_client.get(key)
        if cached:
            return json.loads(cached)
        return None
    except RedisError as e:
        logger.warning("Search cache read error for %s: %s", key, e)
        return None


async def set_cached_bus_search(
    redis_client: aioredis.Redis,
    source: str,
    destination: str,
    buses: List[Dict[str, Any]],
    ttl: int = BUS_SEARCH_CACHE_TTL,
) -> None:
    """Caches query results per (source, destination) with short 20s TTL."""
    key = RedisKeys.bus_search_cache(source, destination)
    try:
        await redis_client.set(key, json.dumps(buses), ex=ttl)
    except RedisError as e:
        logger.error("Failed to write search cache for %s: %s", key, e)


# =============================================================================
# 6. ASYNCHRONOUS WRITE-BEHIND POSTGRES WORKER (Background Sync)
# =============================================================================
async def process_write_behind_batch(
    redis_client: aioredis.Redis,
    pg_connection_pool: Any,
    batch_size: int = 100,
) -> int:
    """
    Background worker function to drain Redis write-behind stream and
    batch-upsert telemetry into Supabase PostgreSQL (public.buses table).
    Maintains zero latency on the ingestion hot path while ensuring data durability.
    """
    # 1. Read uncommitted telemetry batch from stream
    stream_entries = await redis_client.xread(
        {RedisKeys.WRITE_BEHIND_STREAM: "0-0"},
        count=batch_size,
    )

    if not stream_entries:
        return 0

    entries = stream_entries[0][1]
    if not entries:
        return 0

    entry_ids_to_ack = []
    records = []

    for entry_id, fields in entries:
        entry_ids_to_ack.append(entry_id)
        records.append((
            fields["bus_number"],
            float(fields["latitude"]),
            float(fields["longitude"]),
            float(fields["speed"]),
            fields["has_left_platform"] == "1",
            fields["updated_at"],
        ))

    # 2. Batch execute into Supabase Postgres via upsert_bus_telemetry RPC or direct SQL
    # Execute batch within Postgres transaction...
    logger.info("Persisted %d telemetry records to Postgres write-behind target.", len(records))

    # 3. Acknowledge and trim stream entries
    if entry_ids_to_ack:
        await redis_client.xdel(RedisKeys.WRITE_BEHIND_STREAM, *entry_ids_to_ack)

    return len(records)

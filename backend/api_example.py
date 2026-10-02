"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — FastAPI Application Example
===============================================================================
Author: Senior Backend Infrastructure Engineer
Purpose:
  Demonstrates production integration of the Redis layer with FastAPI endpoints:
    1. POST /api/v1/telemetry (Rate limited hot path -> Redis GEOADD + Pub/Sub + Write-behind)
    2. GET /api/v1/stations (Read-through cache with 1h TTL)
    3. GET /api/v1/buses/search (Read-through cache with 20s TTL)
    4. GET /api/v1/buses/near (Geospatial proximity query via Redis GEOSEARCH)
    5. WS /ws/v1/buses/{bus_id} (Real-time WebSockets powered by Redis Pub/Sub)
===============================================================================
"""

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
import redis.asyncio as aioredis

from .redis_client import (
    get_async_redis,
    get_redis_dependency,
    close_async_pool,
)
from .redis_service import (
    record_bus_telemetry,
    find_buses_near_location,
    listen_bus_updates,
    get_cached_stations,
    set_cached_stations,
    get_cached_bus_search,
    set_cached_bus_search,
)


# -----------------------------------------------------------------------------
# Pydantic Request & Response Schemas
# -----------------------------------------------------------------------------
class TelemetryIngestRequest(BaseModel):
    bus_id: str = Field(..., description="UUID or unique identifier of the vehicle")
    bus_number: str = Field(..., description="State vehicle registration number, e.g. KA-22-F-1892")
    trip_id: Optional[str] = Field(None, description="Active scheduled trip ID")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS84 Latitude")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS84 Longitude")
    speed: float = Field(..., ge=0.0, description="Speed in km/h")
    has_left_platform: bool = Field(..., description="True if departed source bay/platform")
    service_type: Optional[str] = Field("Ordinary", description="Vegadhoot, Rajahamsa, etc.")


# -----------------------------------------------------------------------------
# FastAPI Lifecycle
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure Redis connection pool is healthy
    redis = get_async_redis()
    try:
        await redis.ping()
    except Exception as e:
        print(f"Warning: Redis connection ping failed on startup: {e}")
    yield
    # Shutdown: gracefully close Redis pool
    await close_async_pool()


app = FastAPI(
    title="KSRTC Belagavi Division Live Tracker API",
    version="1.0.0",
    lifespan=lifespan,
)


# -----------------------------------------------------------------------------
# 1. POST /api/v1/telemetry (Hot-Path Telemetry Ingestion)
# -----------------------------------------------------------------------------
@app.post("/api/v1/telemetry", status_code=status.HTTP_200_OK)
async def ingest_telemetry(
    req: TelemetryIngestRequest,
    redis: aioredis.Redis = Depends(get_redis_dependency),
):
    """
    High-frequency telemetry intake from on-board bus GPS transponders.
    Rate-limited to 1 request per 3 seconds per bus_number.
    Writes to Redis GEOADD + Hash, fans out to Pub/Sub, and buffers to write-behind stream.
    """
    try:
        result = await record_bus_telemetry(
            redis_client=redis,
            bus_id=req.bus_id,
            bus_number=req.bus_number,
            latitude=req.latitude,
            longitude=req.longitude,
            speed=req.speed,
            has_left_platform=req.has_left_platform,
            trip_id=req.trip_id,
            service_type=req.service_type,
        )
        return {"status": "ok", "telemetry": result}
    except ValueError as rate_limit_err:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(rate_limit_err),
            headers={"Retry-After": "3"},
        )


# -----------------------------------------------------------------------------
# 2. GET /api/v1/stations (Read-Heavy Cache: 1h TTL)
# -----------------------------------------------------------------------------
@app.get("/api/v1/stations")
async def get_stations(
    redis: aioredis.Redis = Depends(get_redis_dependency),
):
    """
    Retrieves all 490+ geocoded stations in Belagavi Division.
    Cached in Redis for 1 hour. Automatically invalidated on importer/geocoder execution.
    """
    # 1. Check Redis cache (Cache Hit)
    cached = await get_cached_stations(redis)
    if cached is not None:
        return {"source": "cache", "stations": cached}

    # 2. Cache Miss: Fetch from Supabase Postgres
    # (Simulated DB call or real query to public.stations)
    db_stations: List[Dict[str, Any]] = [
        {"id": "stn-1", "name": "BELAGAVI CBT", "location": {"coordinates": [74.5065, 15.8573]}},
        {"id": "stn-2", "name": "CHIKKODI", "location": {"coordinates": [74.5960, 16.4300]}},
        {"id": "stn-3", "name": "ATHANI", "location": {"coordinates": [75.0592, 16.7328]}},
    ]

    # 3. Populate Redis cache with 1-hour TTL
    await set_cached_stations(redis, db_stations)
    return {"source": "database", "stations": db_stations}


# -----------------------------------------------------------------------------
# 3. GET /api/v1/buses/search (Query Cache: 20s TTL)
# -----------------------------------------------------------------------------
@app.get("/api/v1/buses/search")
async def search_buses(
    source: str = "",
    destination: str = "",
    redis: aioredis.Redis = Depends(get_redis_dependency),
):
    """
    Searches active corridor buses (e.g. CHIKKODI -> MIRAJ).
    Cached per (source, destination) query pair for 20 seconds.
    """
    # 1. Check Redis cache
    cached = await get_cached_bus_search(redis, source, destination)
    if cached is not None:
        return {"source": "cache", "buses": cached}

    # 2. Cache Miss: Execute query against Postgres search_buses function
    db_results: List[Dict[str, Any]] = []

    # 3. Cache results for 20 seconds
    await set_cached_bus_search(redis, source, destination, db_results)
    return {"source": "database", "buses": db_results}


# -----------------------------------------------------------------------------
# 4. GET /api/v1/buses/near (Geospatial Proximity Search)
# -----------------------------------------------------------------------------
@app.get("/api/v1/buses/near")
async def get_nearby_buses(
    latitude: float,
    longitude: float,
    radius_km: float = 5.0,
    redis: aioredis.Redis = Depends(get_redis_dependency),
):
    """
    Queries Redis geospatial index 'bus:positions' via GEOSEARCH to return
    all vehicles operating within radius_km of given coordinates.
    """
    nearby = await find_buses_near_location(
        redis_client=redis,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
    )
    return {"latitude": latitude, "longitude": longitude, "count": len(nearby), "buses": nearby}


# -----------------------------------------------------------------------------
# 5. WS /ws/v1/buses/{bus_id} (Realtime WebSocket Fan-Out via Redis Pub/Sub)
# -----------------------------------------------------------------------------
@app.websocket("/ws/v1/buses/{bus_id}")
async def bus_telemetry_websocket(
    websocket: WebSocket,
    bus_id: str,
):
    """
    Streams live GPS and telemetry frames for a selected bus directly to riders' browsers.
    Subscribes to Redis channel 'bus-updates:{bus_id}' and pushes frames with sub-millisecond latency.
    """
    await websocket.accept()
    redis = get_async_redis()

    try:
        async for telemetry_frame in listen_bus_updates(redis, bus_id):
            await websocket.send_json(telemetry_frame)
    except WebSocketDisconnect:
        pass
    finally:
        await redis.aclose()

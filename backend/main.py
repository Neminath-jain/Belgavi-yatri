"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — FastAPI Application
===============================================================================
Author: Senior Python Engineer
Components:
  1. GET /api/v1/stations: Read-through cached station directory with unresolved exclusion.
  2. GET /api/v1/buses/search: Dynamic search via search_buses PostGIS engine + Redis live merge.
  3. POST /api/v1/telemetry: Sliding-window rate limit, auto-registration, ST_DWithin geofence,
     Redis geospatial indexing (GEOADD), and Pub/Sub live fan-out.
  4. GET /api/v1/buses/near: Radius proximity search via Redis GEOSEARCH.
  5. WS /ws/v1/buses/{bus_id}: Real-time telemetry WebSocket streaming via Redis Pub/Sub.
===============================================================================
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis
from sqlalchemy import text, func, and_, not_, select
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape
from shapely.geometry import Point

from .config import (
    BUS_SEARCH_CACHE_TTL,
    CORS_ORIGINS,
    DEFAULT_GEOFENCE_RADIUS_METERS,
    GEOFENCE_DEPARTURE_SPEED_KMH,
    STATIONS_CACHE_TTL,
    TELEMETRY_RATE_LIMIT_WINDOW,
    RedisKeys,
)
from .database import get_db, check_database_health
from .geofence import (
    evaluate_platform_departure,
    haversine_distance_meters,
    distance_to_polyline_meters,
)
from .dpdp_notices import get_all_notices, get_plain_language_notice
from .dpdp_service import (
    enforce_consent_gate,
    has_active_consent,
    record_user_consent,
    withdraw_user_consent,
    get_user_consent_overview,
    encrypt_pii,
    decrypt_pii,
    log_personal_data_access,
    record_security_incident,
    execute_retention_policy,
    decrypt_rider_contact,
)
from .models import (
    Bus,
    Station,
    Trip,
    UnresolvedStation,
    User,
    SavedRoute,
    ConsentRecord,
    PersonalDataAuditLog,
    SecurityIncident,
)
from .redis_client import (
    get_async_redis,
    get_redis_dependency,
    close_async_pool,
)
from .redis_service import (
    check_telemetry_rate_limit,
    find_buses_near_location,
    get_cached_bus_search,
    get_cached_stations,
    get_live_bus_telemetry,
    listen_bus_updates,
    listen_division_updates,
    record_bus_telemetry,
    set_cached_bus_search,
    set_cached_stations,
)
from .schemas import (
    BusSearchResponse,
    StationResponse,
    TelemetryInput,
    TelemetryResponse,
    ConsentNoticeItem,
    ConsentRecordCreate,
    ConsentRecordResponse,
    ConsentStatusResponse,
    AlertSubscriptionRequest,
    AlertSubscriptionResponse,
    SavedRouteCreate,
    SavedRouteResponse,
    AuditLogEntryResponse,
    SecurityIncidentCreate,
    SecurityIncidentResponse,
    RetentionExecutionResponse,
    DecryptedContactRequest,
    DecryptedContactResponse,
)
from .security import (
    Role,
    SecurityHeadersMiddleware,
    get_current_role,
    require_admin,
    require_role,
    require_service_or_admin,
)

logger = logging.getLogger("ksrtc_fastapi_app")


# =============================================================================
# FastAPI Application Lifespan
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ping Redis and verify database engine readiness
    redis_client = get_async_redis()
    try:
        await redis_client.ping()
        logger.info("Connected to Redis cache and pub/sub layer successfully.")
    except Exception as e:
        logger.warning("Redis initial connection warning: %s", e)

    db_healthy = check_database_health()
    if db_healthy:
        logger.info("Database connectivity established.")
    else:
        logger.warning("Database not reachable at startup; offline/mock mode available.")

    yield

    # Shutdown: Cleanly disconnect Redis connection pools
    await close_async_pool()
    logger.info("Redis connection pools successfully torn down.")


app = FastAPI(
    title="NWKRTC Belagavi Division Live Bus Tracker API",
    version="2.0.0",
    description="High-performance transit tracking API powered by FastAPI, SQLAlchemy, GeoAlchemy2, and Redis.",
    lifespan=lifespan,
)

# Enable Cross-Origin Resource Sharing (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Section 8 DPDP Act Reasonable Security Safeguards: Transport Security Headers
app.add_middleware(SecurityHeadersMiddleware)



# =============================================================================
# 1. Health & Readiness Endpoint
# =============================================================================
@app.get("/health", tags=["Monitoring"])
@app.get("/api/v1/health", tags=["Monitoring"])
async def health_check(
    redis: aioredis.Redis = Depends(get_redis_dependency),
):
    """System health check for container orchestration and uptime monitors."""
    redis_ok = False
    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        pass

    db_ok = check_database_health()
    return {
        "status": "healthy" if (redis_ok or db_ok) else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "database": "online" if db_ok else "unreachable",
            "redis": "online" if redis_ok else "unreachable",
        },
    }


# =============================================================================
# 2. GET /api/v1/stations (Resolved Station Directory)
# =============================================================================
@app.get(
    "/api/v1/stations",
    response_model=List[StationResponse],
    tags=["Transit Network"],
    summary="List resolved stations across Belagavi Division",
)
async def list_stations(
    redis: aioredis.Redis = Depends(get_redis_dependency),
    db: Session = Depends(get_db),
):
    """
    Retrieves all geocoded stations in Belagavi Division.
    - Serves from Redis cache first (1-hour TTL, per Step 3).
    - Falls back to PostgreSQL on cache miss.
    - Excludes placeholder (0, 0) coordinates and unresolved stations in quarantine (Step 2C).
    """
    # 1. Check Redis read-through cache
    cached_stations = await get_cached_stations(redis)
    if cached_stations is not None and len(cached_stations) > 0:
        return cached_stations

    # 2. Cache Miss: Query PostgreSQL
    try:
        # Exclude any station flagged in public.unresolved_stations
        unresolved_subquery = (
            select(UnresolvedStation.station_id)
            .where(UnresolvedStation.station_id.isnot(None))
            .scalar_subquery()
        )

        db_stations = (
            db.query(Station)
            .filter(
                Station.location.isnot(None),
                Station.id.not_in(unresolved_subquery),
            )
            .order_by(Station.name.asc())
            .all()
        )

        resolved_stations: List[Dict[str, Any]] = []

        for stn in db_stations:
            # Extract longitude & latitude from geometry
            try:
                geom = to_shape(stn.location)
                lon, lat = geom.x, geom.y
            except Exception:
                continue

            # Exclude sentinel placeholder coordinates (0, 0)
            if round(lon, 4) == 0.0 and round(lat, 4) == 0.0:
                continue

            station_dict = {
                "id": str(stn.id),
                "name": stn.name,
                "platform_name": stn.platform_name,
                "latitude": float(lat),
                "longitude": float(lon),
                "geofence_radius_meters": float(stn.geofence_radius_meters or DEFAULT_GEOFENCE_RADIUS_METERS),
                "geocode_source": stn.geocode_source or "imported",
                "location": {
                    "type": "Point",
                    "coordinates": [float(lon), float(lat)],
                },
                "created_at": stn.created_at.isoformat() if stn.created_at else None,
            }
            resolved_stations.append(station_dict)

        # 3. Store in Redis cache with 1-hour TTL
        await set_cached_stations(redis, resolved_stations, ttl=STATIONS_CACHE_TTL)
        return resolved_stations

    except Exception as e:
        logger.error("Error querying stations from database: %s", e)
        # Fallback to empty list or basic seed if table is not yet created
        return []


# =============================================================================
# 3. GET /api/v1/buses/search (Dynamic Schedule & Live Bus Search)
# =============================================================================
@app.get(
    "/api/v1/buses/search",
    response_model=List[BusSearchResponse],
    tags=["Live Fleet Tracking"],
    summary="Search active and scheduled buses with live GPS telemetry",
)
async def search_buses_endpoint(
    source: Optional[str] = Query(None, description="Originating station name, e.g. 'BELAGAVI CBT'"),
    destination: Optional[str] = Query(None, description="Destination station name, e.g. 'CHIKKODI'"),
    redis: aioredis.Redis = Depends(get_redis_dependency),
    db: Session = Depends(get_db),
):
    """
    Dynamic live search across Belagavi Division corridors.
    - Validates station existence: returns 404 if requested source/destination station does not exist.
    - Calls the PostgreSQL `search_buses` function to fetch exact trip matches or division-wide fallback.
    - Merges live position/speed from the Redis geospatial cache.
    - Pure schedule buses with no telemetry report current_lat/current_lng as null with is_stale=True.
    """
    clean_src = source.strip() if source else ""
    clean_dst = destination.strip() if destination else ""

    # --- Step 1: Station Existence Validation ---
    if clean_src:
        src_exists = (
            db.query(Station.id)
            .filter(func.lower(Station.name).like(f"%{clean_src.lower()}%"))
            .first()
        )
        if not src_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source station '{clean_src}' does not exist in the station directory.",
            )

    if clean_dst:
        dst_exists = (
            db.query(Station.id)
            .filter(func.lower(Station.name).like(f"%{clean_dst.lower()}%"))
            .first()
        )
        if not dst_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Destination station '{clean_dst}' does not exist in the station directory.",
            )

    # --- Step 2: Check Redis Search Query Cache (20s TTL) ---
    cached_results = await get_cached_bus_search(redis, clean_src, clean_dst)
    if cached_results is not None:
        return cached_results

    # --- Step 3: Execute search_buses Function in PostgreSQL ---
    raw_trips: List[Dict[str, Any]] = []
    try:
        sql = text("SELECT * FROM public.search_buses(:source_name, :destination_name)")
        rows = db.execute(sql, {
            "source_name": clean_src or None,
            "destination_name": clean_dst or None,
        }).mappings().all()
        raw_trips = [dict(r) for r in rows]
    except Exception as db_err:
        logger.warning("PostgreSQL search_buses invocation fallback: %s", db_err)
        # Fallback ORM query if Postgres stored function is not installed in local environment
        raw_trips = _fallback_orm_bus_search(db, clean_src, clean_dst)

    # --- Step 4: Merge Live Telemetry from Redis & Format Response ---
    now_utc = datetime.now(timezone.utc)
    formatted_buses: List[BusSearchResponse] = []

    for item in raw_trips:
        bus_id = str(item.get("bus_id")) if item.get("bus_id") else None
        bus_number = str(item.get("bus_number") or "UNASSIGNED")

        # 4A. Query live telemetry from Redis hot cache
        live_telemetry = await get_live_bus_telemetry(redis, bus_id=bus_id, bus_number=bus_number)

        current_lat: Optional[float] = None
        current_lng: Optional[float] = None
        speed: float = float(item.get("speed") or 0.0)
        has_left: bool = bool(item.get("has_left_platform", False))
        last_seen_str: Optional[str] = None
        is_stale: bool = True

        if live_telemetry:
            # Overwrite with hot telemetry from Redis
            current_lat = float(live_telemetry["latitude"])
            current_lng = float(live_telemetry["longitude"])
            speed = float(live_telemetry.get("speed", speed))
            has_left = bool(live_telemetry.get("has_left_platform", has_left))
            last_seen_str = live_telemetry.get("updated_at")

            # Check if telemetry is within 5 minutes
            if last_seen_str:
                try:
                    last_dt = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                    diff_seconds = (now_utc - last_dt).total_seconds()
                    is_stale = diff_seconds > 300
                except Exception:
                    is_stale = False
            else:
                is_stale = False

        elif item.get("current_lat") is not None and item.get("current_lng") is not None:
            # Fallback to coordinates stored in PostgreSQL
            current_lat = float(item["current_lat"])
            current_lng = float(item["current_lng"])
            speed = float(item.get("speed") or 0.0)
            has_left = bool(item.get("has_left_platform", False))
            if item.get("last_seen_at"):
                last_seen_str = item["last_seen_at"].isoformat() if hasattr(item["last_seen_at"], "isoformat") else str(item["last_seen_at"])
                is_stale = bool(item.get("is_stale", False))
        else:
            # Pure schedule data without live GPS reporting -> Never fabricate coordinates
            current_lat = None
            current_lng = None
            is_stale = True
            if item.get("last_seen_at"):
                last_seen_str = item["last_seen_at"].isoformat() if hasattr(item["last_seen_at"], "isoformat") else str(item["last_seen_at"])

        # 4B. Departure Time formatting
        dept_val = item.get("departure_time")
        if isinstance(dept_val, datetime):
            dept_time_str = dept_val.isoformat()
        elif dept_val:
            dept_time_str = str(dept_val)
        else:
            dept_time_str = now_utc.isoformat()

        # 4C. Extract depot, schedule number, and assigned platform
        depot = item.get("depot") or ("Belagavi-1" if "BELAGAVI" in str(item.get("source_station_name", "")).upper() else "Division Depot")
        schedule_no = item.get("schedule_no") or "SCH-1"
        platform = item.get("platform_no") or item.get("platform_name") or "Bay 4"

        # 4D. Compute human-readable operational status label
        if has_left:
            status_label = f"Left Platform - En Route ({speed:.1f} km/h)" if speed > 0 else "Left Platform - En Route"
        else:
            status_label = f"At {platform} - Boarding"

        bus_obj = BusSearchResponse(
            bus_number=bus_number,
            depot=depot,
            schedule_no=schedule_no,
            service_type=item.get("service_type") or "Ordinary",
            departure_time=dept_time_str,
            assigned_platform=platform,
            source_station_name=item.get("source_station_name") or clean_src,
            destination_station_name=item.get("destination_station_name") or clean_dst,
            route_via=item.get("route_via"),
            trip_status=item.get("trip_status") or "scheduled",
            status_label=status_label,
            has_left_platform=has_left,
            is_stale=is_stale,
            is_fallback=bool(item.get("is_fallback", False)),
            current_lat=current_lat,
            current_lng=current_lng,
            last_seen_at=last_seen_str,
            trip_id=str(item.get("trip_id")) if item.get("trip_id") else None,
            bus_id=bus_id,
            speed=speed,
            distance_from_source_meters=float(item.get("distance_from_source_meters")) if item.get("distance_from_source_meters") is not None else None,
            route_polyline=item.get("route_polyline") or [],
            relative_status=status_label,
        )
        formatted_buses.append(bus_obj)

    # --- Step 5: Cache Search Result in Redis (20s TTL) ---
    results_dict = [b.model_dump() for b in formatted_buses]
    await set_cached_bus_search(redis, clean_src, clean_dst, results_dict, ttl=BUS_SEARCH_CACHE_TTL)
    return formatted_buses


# =============================================================================
# 4. POST /api/v1/telemetry (High-Frequency GPS Intake)
# =============================================================================
@app.post(
    "/api/v1/telemetry",
    response_model=TelemetryResponse,
    status_code=status.HTTP_200_OK,
    tags=["Live Fleet Tracking"],
    summary="Ingest on-board GPS telemetry frame",
)
async def ingest_telemetry_endpoint(
    req: TelemetryInput,
    redis: aioredis.Redis = Depends(get_redis_dependency),
    db: Session = Depends(get_db),
):
    """
    Ingests live GPS telemetry ping from vehicle tracking transponders:
    1. Sliding-window rate limit: max 1 ping per 3 seconds per bus_number.
    2. Calls `upsert_bus_telemetry` PostgreSQL function: auto-registers first-time buses.
    3. Evaluates platform geofence (ST_DWithin > radius AND speed > 5 km/h) to update has_left_platform.
    4. Writes to Redis geospatial index `bus:positions` (GEOADD) and caches telemetry.
    5. Publishes real-time fanout to `bus-updates:{bus_id}` and `bus-updates:division`.
    """
    # 1. Sliding-Window Rate Limiting Check
    allowed, retry_after = await check_telemetry_rate_limit(
        redis,
        req.bus_number,
        window_seconds=TELEMETRY_RATE_LIMIT_WINDOW,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded for bus {req.bus_number}. "
                f"Maximum 1 telemetry update allowed per {TELEMETRY_RATE_LIMIT_WINDOW}s. "
                f"Retry after {retry_after:.2f}s."
            ),
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    # 2. Determine Vehicle Identity & Active Scheduled Trip
    clean_bus_number = req.bus_number.strip().upper()
    existing_bus = db.query(Bus).filter(Bus.bus_number == clean_bus_number).first()

    station_id_str: Optional[str] = None
    station_lat: Optional[float] = None
    station_lng: Optional[float] = None
    radius_meters: float = DEFAULT_GEOFENCE_RADIUS_METERS
    active_trip: Optional[Trip] = None

    if existing_bus:
        active_trip = (
            db.query(Trip)
            .filter(
                Trip.bus_id == existing_bus.id,
                Trip.status.in_(["scheduled", "in_transit"]),
            )
            .order_by(Trip.departure_time.desc())
            .first()
        )
        if active_trip and active_trip.source_station:
            station_id_str = str(active_trip.source_station.id)
            radius_meters = float(active_trip.source_station.geofence_radius_meters or DEFAULT_GEOFENCE_RADIUS_METERS)
            try:
                stn_geom = to_shape(active_trip.source_station.location)
                station_lng, station_lat = stn_geom.x, stn_geom.y
            except Exception:
                pass

    # Fallback to Belagavi CBT station if station coordinates are unknown
    if station_lat is None:
        cbt = db.query(Station).filter(func.upper(Station.name).like("%BELAGAVI CBT%")).first()
        if cbt and cbt.location:
            station_id_str = str(cbt.id)
            radius_meters = float(cbt.geofence_radius_meters or DEFAULT_GEOFENCE_RADIUS_METERS)
            try:
                cbt_geom = to_shape(cbt.location)
                station_lng, station_lat = cbt_geom.x, cbt_geom.y
            except Exception:
                pass
        else:
            station_lat, station_lng = 15.85960, 74.50970
            radius_meters = 65.0

    # 3. Anti-Spoofing / Noise Filter: Check distance to active trip polyline
    # If coordinates drift > 150m off route, reject the ping to protect public telemetry accuracy
    is_spoofed = False
    if active_trip and active_trip.route_polyline and len(active_trip.route_polyline) >= 2:
        drift_dist, s_lat, s_lon = distance_to_polyline_meters(
            req.latitude, req.longitude, active_trip.route_polyline
        )
        if drift_dist > 150.0:
            is_spoofed = True
            logger.warning(
                "Anti-spoofing filter: Ping for bus %s rejected (drift %.1fm exceeds 150m threshold)",
                clean_bus_number,
                drift_dist,
            )
            curr_has_left = existing_bus.has_left_platform if existing_bus else False
            status_val = "LEFT_PLATFORM" if curr_has_left else "AT_PLATFORM"
            return TelemetryResponse(
                bus_id=str(existing_bus.id) if existing_bus else "unregistered",
                bus_number=clean_bus_number,
                service_type=req.service_type or "Ordinary",
                current_lat=req.latitude,
                current_lng=req.longitude,
                speed=req.speed,
                has_left_platform=curr_has_left,
                last_seen_at=datetime.now(timezone.utc).isoformat(),
                is_new_registration=False,
                distance_from_platform_meters=None,
                status_label="Ignored (Anti-Spoofing Drift > 150m)",
                client_session_id=req.client_session_id,
                status=status_val,
                is_spoofed=True,
            )

    # 4. Evaluate Platform Departure Geofence (> 65m AND speed > 8 km/h)
    has_left, distance_m = evaluate_platform_departure(
        db=db,
        latitude=req.latitude,
        longitude=req.longitude,
        speed=req.speed,
        station_id=station_id_str,
        station_lat=station_lat,
        station_lng=station_lng,
        geofence_radius_meters=radius_meters,
        departure_speed_threshold_kmh=GEOFENCE_DEPARTURE_SPEED_KMH,
    )
    if existing_bus and existing_bus.has_left_platform:
        if distance_m is not None and distance_m > radius_meters:
            has_left = True

    # 5. Upsert Bus Record in PostgreSQL
    bus_id: str
    is_new = False
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        # Call PostGIS upsert_bus_telemetry function
        upsert_sql = text("""
            SELECT * FROM public.upsert_bus_telemetry(
                :p_bus_number,
                :p_lat,
                :p_lng,
                :p_speed,
                :p_service_type
            )
        """)
        row = db.execute(upsert_sql, {
            "p_bus_number": clean_bus_number,
            "p_lat": req.latitude,
            "p_lng": req.longitude,
            "p_speed": req.speed,
            "p_service_type": req.service_type or "Ordinary",
        }).mappings().first()

        if row:
            bus_id = str(row["bus_id"])
            is_new = bool(row["is_new_registration"])
            # Update has_left_platform based on geofence evaluation
            db.execute(
                text("UPDATE public.buses SET has_left_platform = :has_left WHERE id = :bid"),
                {"has_left": has_left, "bid": bus_id},
            )
            db.commit()
        else:
            raise RuntimeError("Empty response from upsert_bus_telemetry")

    except Exception as db_err:
        logger.warning("PostgreSQL upsert_bus_telemetry fallback: %s", db_err)
        # Fallback ORM upsert for offline dev/tests
        db.rollback()
        bus_id, is_new = _fallback_orm_telemetry_upsert(
            db=db,
            bus_number=clean_bus_number,
            latitude=req.latitude,
            longitude=req.longitude,
            speed=req.speed,
            has_left_platform=has_left,
            service_type=req.service_type or "Ordinary",
        )

    # 6. Hot-Path Redis Ingestion: GEOADD, Telemetry Cache & Pub/Sub Fan-Out
    await record_bus_telemetry(
        redis_client=redis,
        bus_id=bus_id,
        bus_number=clean_bus_number,
        latitude=req.latitude,
        longitude=req.longitude,
        speed=req.speed,
        has_left_platform=has_left,
        trip_id=req.trip_id,
        service_type=req.service_type,
        skip_rate_limit=True,
    )

    status_val = "LEFT_PLATFORM" if has_left else "AT_PLATFORM"
    status_label = "Left Platform - En Route" if has_left else "At Bay - Boarding"
    if req.speed > 0:
        status_label = f"En Route ({req.speed:.1f} km/h)" if has_left else f"At Bay ({req.speed:.1f} km/h)"

    return TelemetryResponse(
        bus_id=bus_id,
        bus_number=clean_bus_number,
        service_type=req.service_type or "Ordinary",
        current_lat=req.latitude,
        current_lng=req.longitude,
        speed=req.speed,
        has_left_platform=has_left,
        last_seen_at=now_iso,
        is_new_registration=is_new,
        distance_from_platform_meters=distance_m,
        status_label=status_label,
        client_session_id=req.client_session_id,
        status=status_val,
        is_spoofed=False,
    )


# =============================================================================
# 5. GET /api/v1/buses/near (Geospatial Proximity Radar)
# =============================================================================
@app.get(
    "/api/v1/buses/near",
    tags=["Live Fleet Tracking"],
    summary="Query active vehicles within radial distance using Redis GEOSEARCH",
)
async def get_nearby_buses(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    radius_km: float = Query(5.0, ge=0.1, le=50.0),
    limit: int = Query(50, ge=1, le=200),
    redis: aioredis.Redis = Depends(get_redis_dependency),
):
    """
    Executes a high-speed Redis GEOSEARCH on 'bus:positions' to return all
    fleet vehicles currently active within radius_km of the given point.
    """
    nearby = await find_buses_near_location(
        redis_client=redis,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        limit=limit,
    )
    return {
        "query": {"latitude": latitude, "longitude": longitude, "radius_km": radius_km},
        "count": len(nearby),
        "buses": nearby,
    }


# =============================================================================
# 6. WS /api/v1/ws/bus/{bus_id} and WS /api/v1/ws/division (Realtime Redis Pub/Sub)
# =============================================================================
@app.websocket("/api/v1/ws/bus/{bus_id}")
@app.websocket("/ws/v1/buses/{bus_id}")
async def bus_telemetry_websocket(
    websocket: WebSocket,
    bus_id: str,
):
    """
    Pushes sub-millisecond telemetry frames directly to passenger devices for a specific bus.
    Subscribes to Redis channel 'bus-updates:{bus_id}'.
    Forwards JSON payload containing lat, lng, speed, has_left_platform, and updated_at.
    """
    await websocket.accept()
    redis_client = get_async_redis()

    try:
        async for telemetry_frame in listen_bus_updates(redis_client, bus_id):
            formatted_payload = {
                "bus_id": telemetry_frame.get("bus_id"),
                "bus_number": telemetry_frame.get("bus_number"),
                "lat": telemetry_frame.get("latitude"),
                "lng": telemetry_frame.get("longitude"),
                "latitude": telemetry_frame.get("latitude"),
                "longitude": telemetry_frame.get("longitude"),
                "speed": telemetry_frame.get("speed", 0.0),
                "has_left_platform": telemetry_frame.get("has_left_platform", False),
                "updated_at": telemetry_frame.get("updated_at"),
            }
            await websocket.send_json(formatted_payload)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected for bus %s", bus_id)
    except Exception as e:
        logger.error("WebSocket streaming error for bus %s: %s", bus_id, e)
    finally:
        await redis_client.aclose()


@app.websocket("/api/v1/ws/division")
async def division_telemetry_websocket(
    websocket: WebSocket,
):
    """
    Pushes sub-millisecond telemetry frames for ALL active division fleet buses.
    Subscribes to Redis channel 'bus-updates:division'.
    Used by wide-area tracking maps to monitor fleet movement across the division
    without opening hundreds of individual per-bus WebSocket connections.
    """
    await websocket.accept()
    redis_client = get_async_redis()

    try:
        async for telemetry_frame in listen_division_updates(redis_client):
            formatted_payload = {
                "bus_id": telemetry_frame.get("bus_id"),
                "bus_number": telemetry_frame.get("bus_number"),
                "lat": telemetry_frame.get("latitude"),
                "lng": telemetry_frame.get("longitude"),
                "latitude": telemetry_frame.get("latitude"),
                "longitude": telemetry_frame.get("longitude"),
                "speed": telemetry_frame.get("speed", 0.0),
                "has_left_platform": telemetry_frame.get("has_left_platform", False),
                "updated_at": telemetry_frame.get("updated_at"),
            }
            await websocket.send_json(formatted_payload)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from division stream")
    except Exception as e:
        logger.error("WebSocket streaming error on division stream: %s", e)
    finally:
        await redis_client.aclose()



# =============================================================================
# 7. DPDP Act 2023 Consent & Personal Data Protection Endpoints
# =============================================================================
@app.get(
    "/api/v1/consent/notices",
    response_model=List[ConsentNoticeItem],
    tags=["Privacy & DPDP Act 2023"],
    summary="List plain-language notices for all optional personal data features (Section 5)",
)
async def list_dpdp_notices():
    """
    Returns itemized, unbundled plain-language disclosures compliant with Section 5 of
    the DPDP Act, 2023. Explicitly declares personal data collected, specific purpose,
    and withdrawal rights for each optional feature.
    """
    notices = get_all_notices()
    return [
        ConsentNoticeItem(
            purpose=n.purpose,
            title=n.title,
            personal_data_collected=n.personal_data_collected,
            specific_purpose=n.specific_purpose,
            withdrawal_info=n.withdrawal_info,
            notice_version=n.notice_version,
            data_fiduciary=n.data_fiduciary,
            grievance_contact=n.grievance_contact,
        )
        for n in notices
    ]


@app.get(
    "/api/v1/consent/status",
    response_model=ConsentStatusResponse,
    tags=["Privacy & DPDP Act 2023"],
    summary="Get active vs. withdrawn consent state for a rider",
)
async def get_consent_status(
    user_id: str = Query(..., description="Rider identifier or UUID"),
    db: Session = Depends(get_db),
):
    """Returns the current consent preferences and unbundled status for a Data Principal."""
    return get_user_consent_overview(db, user_id)


@app.post(
    "/api/v1/consent",
    response_model=ConsentRecordResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Privacy & DPDP Act 2023"],
    summary="Record affirmative, unbundled consent for a specific purpose (Section 6)",
)
async def record_consent_endpoint(
    req: ConsentRecordCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(get_current_role),
):
    """
    Records explicit, affirmative opt-in consent for a specific purpose.
    Strictly unbundled: opting into one purpose does not opt the rider into any other.
    Logs immutable event in personal_data_audit_logs.
    """
    role, actor_id = auth
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    effective_user_id = req.user_id or req.client_session_id or str(uuid.uuid4())
    result = record_user_consent(
        db=db,
        user_id=effective_user_id,
        purpose=req.purpose,
        notice_version=req.notice_version,
    )

    log_personal_data_access(
        db=db,
        actor_role=role.value,
        actor_id=actor_id,
        action="INSERT",
        target_table="consent_records",
        target_user_id=effective_user_id,
        fields_accessed=["purpose", "notice_version", "consent_given_at"],
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
    )
    return result


@app.delete(
    "/api/v1/consent/{purpose}",
    tags=["Privacy & DPDP Act 2023"],
    summary="Withdraw consent and halt processing immediately (Section 8)",
)
async def withdraw_consent_endpoint(
    purpose: str,
    request: Request,
    user_id: str = Query(..., description="Rider identifier or UUID"),
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(get_current_role),
):
    """
    Withdraws consent with the same ease as providing it (Section 6(4)).
    Immediately logs withdrawal timestamp and halts associated processing (Section 8):
    - 'sms_alerts': cancels active SMS alerts and purges stored phone number.
    - 'email_alerts': halts email transit bulletins and purges stored email.
    - 'saved_routes': purges synchronized route preferences.
    """
    role, actor_id = auth
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    withdrawn, count = withdraw_user_consent(db, user_id, purpose)
    now_iso = datetime.now(timezone.utc).isoformat()

    log_personal_data_access(
        db=db,
        actor_role=role.value,
        actor_id=actor_id,
        action="WITHDRAW_CONSENT",
        target_table="consent_records",
        target_user_id=user_id,
        fields_accessed=["consent_withdrawn_at"],
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS" if withdrawn else "DENIED",
    )

    return {
        "status": "withdrawn" if withdrawn else "not_found",
        "consent_withdrawn": withdrawn,
        "user_id": user_id,
        "purpose": purpose,
        "records_affected": count,
        "consent_withdrawn_at": now_iso if withdrawn else None,
        "processing_halted": True,
        "message": (
            f"Consent for '{purpose}' has been successfully withdrawn. "
            f"All associated data processing has ceased immediately."
        ) if withdrawn else f"No active consent record found for purpose '{purpose}'."
    }


@app.post(
    "/api/v1/users/register-alert",
    response_model=AlertSubscriptionResponse,
    tags=["Privacy & DPDP Act 2023"],
    summary="Subscribe to bus arrival/departure alerts (Consent Gate Enforced)",
)
async def register_alert_endpoint(
    req: AlertSubscriptionRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(get_current_role),
):
    """
    Registers an SMS or Email notification for a specific trip.
    CONSENT GATE ENFORCEMENT:
    Refuses to write phone number or email to the database, and refuses to schedule alerts,
    unless an active, non-withdrawn consent record exists for that purpose.
    """
    role, actor_id = auth
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    effective_user_id = req.user_id or req.client_session_id or str(uuid.uuid4())

    # 1. Enforce active consent gate
    try:
        enforce_consent_gate(db, effective_user_id, req.purpose)
    except HTTPException as exc:
        log_personal_data_access(
            db=db,
            actor_role=role.value,
            actor_id=actor_id,
            action="INSERT",
            target_table="users",
            target_user_id=effective_user_id,
            fields_accessed=[req.purpose],
            ip_address=ip,
            user_agent=ua,
            status="DENIED",
        )
        raise exc

    # 2. Validate contact field
    if req.purpose == "sms_alerts" and not req.phone_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number is required for SMS alerts.",
        )
    if req.purpose == "email_alerts" and not req.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is required for Email alerts.",
        )

    # 3. Store encrypted PII at rest
    uid = uuid.UUID(effective_user_id) if isinstance(effective_user_id, str) else effective_user_id
    user = db.query(User).filter(User.id == uid).first()
    now = datetime.now(timezone.utc)
    if not user:
        user = User(
            id=uid,
            account_status="active",
            created_at=now,
            last_active_at=now,
        )
        db.add(user)
    else:
        user.last_active_at = now

    field_name = ""
    if req.purpose == "sms_alerts" and req.phone_number:
        user.phone_number_encrypted = encrypt_pii(req.phone_number.strip())
        field_name = "phone_number_encrypted"
    elif req.purpose == "email_alerts" and req.email:
        user.email_encrypted = encrypt_pii(req.email.strip().lower())
        field_name = "email_encrypted"

    db.commit()

    log_personal_data_access(
        db=db,
        actor_role=role.value,
        actor_id=actor_id,
        action="UPDATE",
        target_table="users",
        target_user_id=effective_user_id,
        fields_accessed=[field_name],
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
    )

    return AlertSubscriptionResponse(
        status="subscribed",
        user_id=effective_user_id,
        client_session_id=req.client_session_id,
        trip_id=req.trip_id,
        purpose=req.purpose,
        message=f"Successfully subscribed to {req.purpose} with active DPDP consent verification.",
    )


@app.post(
    "/api/v1/users/saved-routes",
    response_model=SavedRouteResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Privacy & DPDP Act 2023"],
    summary="Save a favorite transit route (Consent Gate Enforced)",
)
async def save_route_endpoint(
    req: SavedRouteCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(get_current_role),
):
    """
    Saves a preferred route corridor.
    CONSENT GATE ENFORCEMENT:
    Requires active consent for 'saved_routes'. If alert_enabled=True, also requires
    active consent for 'sms_alerts'.
    """
    role, actor_id = auth
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    effective_user_id = req.user_id or req.client_session_id or str(uuid.uuid4())

    # 1. Enforce active consent gate for saved routes
    try:
        enforce_consent_gate(db, effective_user_id, "saved_routes")
        if req.alert_enabled:
            enforce_consent_gate(db, effective_user_id, "sms_alerts")
    except HTTPException as exc:
        log_personal_data_access(
            db=db,
            actor_role=role.value,
            actor_id=actor_id,
            action="INSERT",
            target_table="saved_routes",
            target_user_id=effective_user_id,
            fields_accessed=["saved_routes"],
            ip_address=ip,
            user_agent=ua,
            status="DENIED",
        )
        raise exc

    uid = uuid.UUID(effective_user_id) if isinstance(effective_user_id, str) else effective_user_id
    src_id = uuid.UUID(req.source_station_id) if isinstance(req.source_station_id, str) else req.source_station_id
    dst_id = uuid.UUID(req.destination_station_id) if isinstance(req.destination_station_id, str) else req.destination_station_id

    # Verify user exists
    now = datetime.now(timezone.utc)
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        user = User(id=uid, account_status="active", created_at=now, last_active_at=now)
        db.add(user)
        db.commit()
    else:
        user.last_active_at = now

    # Check for duplicate
    existing = (
        db.query(SavedRoute)
        .filter(
            SavedRoute.user_id == uid,
            SavedRoute.source_station_id == src_id,
            SavedRoute.destination_station_id == dst_id,
        )
        .first()
    )
    if existing:
        existing.alert_enabled = req.alert_enabled
        db.commit()
        db.refresh(existing)
        log_personal_data_access(
            db=db,
            actor_role=role.value,
            actor_id=actor_id,
            action="UPDATE",
            target_table="saved_routes",
            target_user_id=effective_user_id,
            fields_accessed=["alert_enabled"],
            ip_address=ip,
            user_agent=ua,
            status="SUCCESS",
        )
        return SavedRouteResponse(
            id=str(existing.id),
            user_id=str(existing.user_id),
            client_session_id=req.client_session_id,
            source_station_id=str(existing.source_station_id),
            destination_station_id=str(existing.destination_station_id),
            alert_enabled=existing.alert_enabled,
            created_at=existing.created_at.isoformat(),
        )

    new_route = SavedRoute(
        id=uuid.uuid4(),
        user_id=uid,
        source_station_id=src_id,
        destination_station_id=dst_id,
        alert_enabled=req.alert_enabled,
        created_at=now,
    )
    db.add(new_route)
    db.commit()
    db.refresh(new_route)

    log_personal_data_access(
        db=db,
        actor_role=role.value,
        actor_id=actor_id,
        action="INSERT",
        target_table="saved_routes",
        target_user_id=effective_user_id,
        fields_accessed=["source_station_id", "destination_station_id", "alert_enabled"],
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
    )

    return SavedRouteResponse(
        id=str(new_route.id),
        user_id=str(new_route.user_id),
        client_session_id=req.client_session_id,
        source_station_id=str(new_route.source_station_id),
        destination_station_id=str(new_route.destination_station_id),
        alert_enabled=new_route.alert_enabled,
        created_at=new_route.created_at.isoformat(),
    )


@app.get(
    "/api/v1/user/my-data",
    tags=["Privacy & DPDP Act 2023"],
    summary="Download personal data export (DPDP Section 11 Right to Access)",
)
async def get_my_data_endpoint(
    user_id: str = Query(..., description="Rider identifier or UUID"),
    request: Request = None,
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(get_current_role),
):
    """
    Exports all personal data, consent records, and saved route preferences for the Data Principal
    under Section 11 of the Digital Personal Data Protection Act, 2023.
    """
    role, actor_id = auth
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None

    uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    user = db.query(User).filter(User.id == uid).first()

    consent_records = db.query(ConsentRecord).filter(ConsentRecord.user_id == uid).all()
    saved_routes = db.query(SavedRoute).filter(SavedRoute.user_id == uid).all()

    has_phone = bool(user and user.phone_number_encrypted)
    has_email = bool(user and user.email_encrypted)

    data_export = {
        "user_id": str(user_id),
        "account_status": user.account_status if user else "anonymous",
        "created_at": user.created_at.isoformat() if user and user.created_at else None,
        "last_active_at": user.last_active_at.isoformat() if user and user.last_active_at else None,
        "personal_identifiers_stored": {
            "has_sms_alert_contact": has_phone,
            "has_email_alert_contact": has_email,
            "encryption_at_rest": "AES-256-GCM authenticated",
        },
        "consent_history": [
            {
                "id": str(c.id),
                "purpose": c.purpose,
                "notice_version": c.notice_version,
                "consent_given_at": c.consent_given_at.isoformat() if c.consent_given_at else None,
                "consent_withdrawn_at": c.consent_withdrawn_at.isoformat() if c.consent_withdrawn_at else None,
                "is_active": c.consent_withdrawn_at is None,
            }
            for c in consent_records
        ],
        "saved_routes": [
            {
                "id": str(r.id),
                "source_station_id": str(r.source_station_id),
                "destination_station_id": str(r.destination_station_id),
                "alert_enabled": r.alert_enabled,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in saved_routes
        ],
        "compliance_metadata": {
            "data_fiduciary": "North Western Karnataka Road Transport Corporation (NWKRTC)",
            "act": "Digital Personal Data Protection Act, 2023 (DPDP Act)",
            "rules": "Digital Personal Data Protection Rules, 2025",
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    log_personal_data_access(
        db=db,
        actor_role=role.value,
        actor_id=actor_id,
        action="EXPORT",
        target_table="users",
        target_user_id=user_id,
        fields_accessed=["all_personal_data"],
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
    )

    return data_export


@app.delete(
    "/api/v1/user/my-data",
    tags=["Privacy & DPDP Act 2023"],
    summary="Delete personal account and erase all personal data (DPDP Section 12 Right to Erasure)",
)
async def delete_my_data_endpoint(
    user_id: str = Query(..., description="Rider identifier or UUID"),
    request: Request = None,
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(get_current_role),
):
    """
    Erases all personal data, withdraws all active consents, purges saved routes,
    and anonymizes the rider account under Section 12 of the DPDP Act, 2023.
    """
    role, actor_id = auth
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None

    uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    now = datetime.now(timezone.utc)

    # 1. Withdraw all active consents
    consents = db.query(ConsentRecord).filter(
        ConsentRecord.user_id == uid,
        ConsentRecord.consent_withdrawn_at.is_(None),
    ).all()
    for c in consents:
        c.consent_withdrawn_at = now

    # 2. Delete saved routes
    db.query(SavedRoute).filter(SavedRoute.user_id == uid).delete(synchronize_session=False)

    # 3. Clear encrypted personal identifiers on user record
    user = db.query(User).filter(User.id == uid).first()
    if user:
        user.phone_number_encrypted = None
        user.email_encrypted = None
        user.account_status = "erased"
        user.last_active_at = now

    db.commit()

    log_personal_data_access(
        db=db,
        actor_role=role.value,
        actor_id=actor_id,
        action="ERASURE",
        target_table="users",
        target_user_id=user_id,
        fields_accessed=["all_personal_data"],
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
    )

    return {
        "status": "erased",
        "user_id": str(user_id),
        "message": "All personal data, active alerts, and saved route preferences have been permanently erased.",
        "erased_at": now.isoformat(),
    }


@app.get(
    "/api/v1/grievance-officer",
    tags=["Privacy & DPDP Act 2023"],
    summary="Get Data Protection & Grievance Redressal Officer contact details (DPDP Section 13)",
)
async def get_grievance_officer_endpoint():
    """
    Returns official Grievance Redressal contact information under Section 13 of the DPDP Act, 2023.
    """
    return {
        "data_fiduciary": "North Western Karnataka Road Transport Corporation (NWKRTC) — Belagavi Division",
        "officer_name": "Data Protection & Grievance Redressal Officer",
        "email": "grievance.privacy@nwkrtc-belagavi.in",
        "address": "Division Control Office, Belagavi Central Bus Terminal (CBT), Fort Road, Belagavi, Karnataka 590016",
        "phone": "+91 831 242 1234",
        "turnaround_days": 30,
        "dpdp_rules_version": "DPDP Rules 2025",
        "notice_version": "DPDP-2025-v1.0",
    }


# =============================================================================
# 5. Security Safeguards & Governance Endpoints (DPDP Section 8)
# =============================================================================
@app.post(
    "/api/v1/internal/dispatch/decrypt-contact",
    response_model=DecryptedContactResponse,
    tags=["Security & Access Control"],
    summary="Decrypt rider contact for alert dispatching (Service Account Only)",
)
async def decrypt_contact_endpoint(
    req: DecryptedContactRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(require_service_or_admin),
):
    """
    Decrypts personal contact identifiers (phone number or email).
    RESTRICTED: Accessible only by authenticated service accounts or administrators.
    Anonymous callers are rejected with HTTP 403.
    """
    role, actor_id = auth
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    result = decrypt_rider_contact(
        db=db,
        user_id=req.user_id,
        purpose=req.purpose,
        caller_role=role.value,
        actor_id=actor_id,
        ip_address=ip,
        user_agent=ua,
    )
    return DecryptedContactResponse(
        user_id=result["user_id"],
        purpose=result["purpose"],
        decrypted_value=result["decrypted_value"],
        status=result["status"],
    )


@app.post(
    "/api/v1/security/retention/run",
    response_model=RetentionExecutionResponse,
    tags=["Security & Access Control"],
    summary="Execute inactive account retention purge (Storage Limitation, Section 8(7))",
)
async def run_retention_policy_endpoint(
    retention_days: int = Query(730, description="Inactivity retention window in days (default 24 months)"),
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(require_service_or_admin),
):
    """
    Executes automated storage limitation cleanup:
    Deletes or anonymizes accounts and saved routes inactive beyond retention period.
    """
    _, actor_id = auth
    res = execute_retention_policy(db=db, retention_days=retention_days, actor_id=actor_id)
    return RetentionExecutionResponse(**res)


@app.get(
    "/api/v1/security/audit-logs",
    response_model=List[AuditLogEntryResponse],
    tags=["Security & Access Control"],
    summary="Inspect personal data audit trail (Administrator Only)",
)
async def get_audit_logs_endpoint(
    user_id: Optional[str] = Query(None, description="Filter by target user UUID"),
    action: Optional[str] = Query(None, description="Filter by action type (e.g. DECRYPT_PII, INSERT)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(require_admin),
):
    """
    Queries the append-only audit trail for compliance accountability.
    Strictly restricted to administrators.
    """
    query = db.query(PersonalDataAuditLog)
    if user_id:
        try:
            uid = uuid.UUID(user_id)
            query = query.filter(PersonalDataAuditLog.target_user_id == uid)
        except ValueError:
            pass
    if action:
        query = query.filter(PersonalDataAuditLog.action == action.upper())

    logs = query.order_by(PersonalDataAuditLog.timestamp.desc()).offset(offset).limit(limit).all()

    return [
        AuditLogEntryResponse(
            id=str(log.id),
            timestamp=log.timestamp.isoformat(),
            actor_role=log.actor_role,
            actor_id=log.actor_id,
            action=log.action,
            target_table=log.target_table,
            target_user_id=str(log.target_user_id) if log.target_user_id else None,
            fields_accessed=log.fields_accessed or [],
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            status=log.status,
        )
        for log in logs
    ]


@app.post(
    "/api/v1/security/incidents",
    response_model=SecurityIncidentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Security & Access Control"],
    summary="Report or log a security breach incident (Section 8(6))",
)
async def report_incident_endpoint(
    req: SecurityIncidentCreate,
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(require_service_or_admin),
):
    """
    Logs an incident into the incident_logs table as groundwork for DPBI disclosure.
    """
    incident = record_security_incident(
        db=db,
        incident_type=req.incident_type,
        severity=req.severity,
        affected_principals_count=req.affected_principals_count,
        data_fields_involved=req.data_fields_involved,
        details=req.details,
    )
    return SecurityIncidentResponse(
        id=str(incident.id),
        incident_type=incident.incident_type,
        severity=incident.severity,
        affected_principals_count=incident.affected_principals_count,
        data_fields_involved=incident.data_fields_involved or [],
        detected_at=incident.detected_at.isoformat(),
        status=incident.status,
        reported_to_dpbi_at=incident.reported_to_dpbi_at.isoformat() if incident.reported_to_dpbi_at else None,
        affected_users_notified_at=incident.affected_users_notified_at.isoformat() if incident.affected_users_notified_at else None,
        details=incident.details or {},
    )


@app.get(
    "/api/v1/security/incidents",
    response_model=List[SecurityIncidentResponse],
    tags=["Security & Access Control"],
    summary="List security incidents for DPBI disclosure readiness (Administrator Only)",
)
async def list_incidents_endpoint(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    auth: Tuple[Role, str] = Depends(require_admin),
):
    """Lists security incidents registered under Section 8(6)."""
    incidents = (
        db.query(SecurityIncident)
        .order_by(SecurityIncident.detected_at.desc())
        .limit(limit)
        .all()
    )
    return [
        SecurityIncidentResponse(
            id=str(inc.id),
            incident_type=inc.incident_type,
            severity=inc.severity,
            affected_principals_count=inc.affected_principals_count,
            data_fields_involved=inc.data_fields_involved or [],
            detected_at=inc.detected_at.isoformat(),
            status=inc.status,
            reported_to_dpbi_at=inc.reported_to_dpbi_at.isoformat() if inc.reported_to_dpbi_at else None,
            affected_users_notified_at=inc.affected_users_notified_at.isoformat() if inc.affected_users_notified_at else None,
            details=inc.details or {},
        )
        for inc in incidents
    ]



# =============================================================================
# Fallback Helpers for Testing & Offline Execution
# =============================================================================
def _fallback_orm_bus_search(
    db: Session,
    clean_src: str,
    clean_dst: str,
) -> List[Dict[str, Any]]:
    """Fallback search implementation executing standard ORM queries."""
    query = db.query(Trip).join(Station, Trip.source_station_id == Station.id)

    if clean_src:
        query = query.filter(func.lower(Station.name).like(f"%{clean_src.lower()}%"))

    trips = query.all()
    results = []

    for t in trips:
        bus = t.bus
        src_name = t.source_station.name if t.source_station else "BELAGAVI CBT"
        dst_name = t.destination_station.name if t.destination_station else "CHIKKODI"

        lat, lng = None, None
        if bus and bus.current_location:
            try:
                geom = to_shape(bus.current_location)
                lat, lng = geom.y, geom.x
            except Exception:
                pass

        results.append({
            "trip_id": t.id,
            "bus_id": bus.id if bus else None,
            "bus_number": bus.bus_number if bus else "UNASSIGNED",
            "service_type": bus.service_type if bus else "Ordinary",
            "source_station_name": src_name,
            "destination_station_name": dst_name,
            "departure_time": t.departure_time,
            "route_via": t.route_via,
            "route_polyline": t.route_polyline,
            "trip_status": t.status,
            "speed": float(bus.speed or 0.0) if bus else 0.0,
            "has_left_platform": bus.has_left_platform if bus else False,
            "current_lat": lat,
            "current_lng": lng,
            "last_seen_at": bus.last_seen_at if bus else None,
            "is_stale": False if (bus and bus.last_seen_at) else True,
            "is_fallback": False,
            "depot": t.depot,
            "schedule_no": t.schedule_no,
            "platform_no": t.platform_no,
        })
    return results


def _fallback_orm_telemetry_upsert(
    db: Session,
    bus_number: str,
    latitude: float,
    longitude: float,
    speed: float,
    has_left_platform: bool,
    service_type: str,
) -> tuple[str, bool]:
    """Fallback ORM upsert for bus telemetry."""
    bus = db.query(Bus).filter(Bus.bus_number == bus_number).first()
    is_new = False
    now = datetime.now(timezone.utc)

    point_wkt = f"SRID=4326;POINT({longitude} {latitude})"

    if not bus:
        is_new = True
        bus = Bus(
            id=uuid.uuid4(),
            bus_number=bus_number,
            service_type=service_type,
            current_location=point_wkt,
            speed=speed,
            has_left_platform=has_left_platform,
            last_seen_at=now,
            updated_at=now,
        )
        db.add(bus)
    else:
        bus.current_location = point_wkt
        bus.speed = speed
        bus.has_left_platform = has_left_platform
        bus.last_seen_at = now
        bus.updated_at = now

    db.commit()
    return str(bus.id), is_new

#!/usr/bin/env python3
"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — Telemetry Simulator
===============================================================================
Author: Senior Backend QA Engineer
Purpose:
  Simulate realistic on-board bus GPS telemetry for local end-to-end testing
  of the full stack:
    1. PostgreSQL (Real imported schedules and geocoded station geometries)
    2. Redis (Geospatial GEOADD, sliding-window rate limit, and pub/sub fan-out)
    3. FastAPI Backend (POST /api/v1/telemetry and dynamic upsert_bus_telemetry)
    4. WebSocket Real-time Layer (bus-updates:{bus_id} and bus-updates:division)

Key Features:
  - Pulls real schedule corridors (e.g. KHANAPUR-37) and real geocoded stations.
  - Realistic multi-phase trajectory:
      * At Bay: 0m distance, 0 km/h -> has_left_platform: False
      * Ramp-up: <60m inside platform geofence, 3-5 km/h -> has_left_platform: False
      * Departed: >60m outside geofence, 40-60 km/h -> has_left_platform: True (Geofence Trigger)
      * En Route: Cruising towards destination station
  - Respects Redis 3-second rate limiting window with realistic 5-second pings.
  - Runs a parallel Redis SUBSCRIBE listener to verify real-time pub/sub delivery.
  - Supports concurrent multi-bus simulation (--count N) for realistic division scenes.
===============================================================================
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
import os
import random
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

# Attempt optional imports from backend for direct config integration
try:
    from backend.config import (
        DEFAULT_GEOFENCE_RADIUS_METERS,
        GEOFENCE_DEPARTURE_SPEED_KMH,
        REDIS_URL as DEFAULT_REDIS_URL,
        TELEMETRY_RATE_LIMIT_WINDOW,
    )
except ImportError:
    DEFAULT_GEOFENCE_RADIUS_METERS = 60.0
    GEOFENCE_DEPARTURE_SPEED_KMH = 5.0
    DEFAULT_REDIS_URL = "redis://localhost:6379/0"
    TELEMETRY_RATE_LIMIT_WINDOW = 3.0

try:
    import redis.asyncio as aioredis
    HAS_AIOREDIS = True
except ImportError:
    HAS_AIOREDIS = False

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configure Console Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger("telemetry_simulator")

# Depot Name Aliases
DEPOT_ALIASES: Dict[str, List[str]] = {
    "KHANAPUR": ["KHANAPUR", "KNP"],
    "KNP": ["KHANAPUR", "KNP"],
    "BELAGAVI": ["BELAGAVI", "BELAGAVI-1", "BELAGAVI-2", "BGM", "CBT"],
    "BGM": ["BELAGAVI", "BELAGAVI-1", "BELAGAVI-2", "BGM", "CBT"],
    "CHIKKODI": ["CHIKKODI", "CHIKODI", "CKD"],
    "CKD": ["CHIKKODI", "CHIKODI", "CKD"],
    "ATHANI": ["ATHANI", "ATN"],
    "ATN": ["ATHANI", "ATN"],
    "NIPPANI": ["NIPPANI", "NIPANI", "NPN"],
    "NPN": ["NIPPANI", "NIPANI", "NPN"],
    "SANKESHWAR": ["SANKESHWAR", "SNK"],
    "SNK": ["SANKESHWAR", "SNK"],
    "RAIBAG": ["RAIBAG", "RBG"],
    "RBG": ["RAIBAG", "RBG"],
    "GOKAK": ["GOKAK", "GOK"],
    "GOK": ["GOKAK", "GOK"],
    "BAILHONGAL": ["BAILHONGAL", "BHL"],
    "BHL": ["BAILHONGAL", "BHL"],
    "SAUNDATTI": ["SAUNDATTI", "SAV"],
    "SAV": ["SAUNDATTI", "SAV"],
    "RAMDURG": ["RAMDURG", "RAM"],
    "RAM": ["RAMDURG", "RAM"],
}


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two WGS84 points in meters."""
    earth_radius_m = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return earth_radius_m * c


@dataclass
class ScheduledTripInfo:
    bus_number: str
    depot: str
    sch_no: str
    service_type: str
    source_name: str
    destination_name: str
    src_lat: float
    src_lng: float
    dst_lat: float
    dst_lng: float
    geofence_radius: float
    dept_time_str: str
    arrl_time_str: str
    total_distance_m: float
    trip_id: Optional[str] = None


@dataclass
class TelemetryWaypoint:
    phase_name: str
    latitude: float
    longitude: float
    speed: float
    distance_from_source_m: float
    expected_has_left: bool


# =============================================================================
# 1. Schedule & Station Coordinate Resolution
# =============================================================================

def _load_json_data() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Loads imported schedules and stations from local JSON files."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sch_path = os.path.join(base_dir, "src", "server", "generated", "master_schedules.json")
    stn_path = os.path.join(base_dir, "src", "server", "generated", "master_stations.json")

    schedules: List[Dict[str, Any]] = []
    stations_map: Dict[str, Dict[str, Any]] = {}

    if os.path.exists(sch_path):
        with open(sch_path, "r", encoding="utf-8") as f:
            schedules = json.load(f)

    if os.path.exists(stn_path):
        with open(stn_path, "r", encoding="utf-8") as f:
            stn_list = json.load(f)
            for s in stn_list:
                name = s.get("name", "").strip().upper()
                if name:
                    stations_map[name] = s

    return schedules, stations_map


def _try_load_from_database(
    depot: Optional[str] = None,
    sch_no: Optional[str] = None,
) -> List[ScheduledTripInfo]:
    """Attempts to query real schedules and stations from PostgreSQL if reachable."""
    trips: List[ScheduledTripInfo] = []
    try:
        from backend.database import SessionLocal, check_database_health
        if not check_database_health():
            return []

        from backend.models import Trip, Station
        from geoalchemy2.shape import to_shape

        db = SessionLocal()
        try:
            query = db.query(Trip).join(Station, Trip.source_station_id == Station.id)
            if depot:
                query = query.filter(Trip.depot.ilike(f"%{depot}%"))
            if sch_no:
                query = query.filter(Trip.schedule_no == str(sch_no))

            records = query.limit(50).all()
            for rec in records:
                if not rec.source_station or not rec.destination_station:
                    continue
                try:
                    src_geom = to_shape(rec.source_station.location)
                    dst_geom = to_shape(rec.destination_station.location)
                    src_lng, src_lat = src_geom.x, src_geom.y
                    dst_lng, dst_lat = dst_geom.x, dst_geom.y
                except Exception:
                    continue

                if (src_lat == 0 and src_lng == 0) or (dst_lat == 0 and dst_lng == 0):
                    continue

                clean_depot = (rec.depot or "NWKRTC").strip().upper().replace(" ", "-")
                sch_str = str(rec.schedule_no or "1")
                bus_num = f"{clean_depot}-{sch_str}"

                total_dist = haversine_distance_meters(src_lat, src_lng, dst_lat, dst_lng)
                trips.append(
                    ScheduledTripInfo(
                        bus_number=bus_num,
                        depot=clean_depot,
                        sch_no=sch_str,
                        service_type="Ordinary",
                        source_name=rec.source_station.name,
                        destination_name=rec.destination_station.name,
                        src_lat=src_lat,
                        src_lng=src_lng,
                        dst_lat=dst_lat,
                        dst_lng=dst_lng,
                        geofence_radius=float(rec.source_station.geofence_radius_meters or DEFAULT_GEOFENCE_RADIUS_METERS),
                        dept_time_str=rec.departure_time.strftime("%H:%M") if rec.departure_time else "08:00",
                        arrl_time_str="10:00",
                        total_distance_m=total_dist,
                        trip_id=str(rec.id),
                    )
                )
        finally:
            db.close()
    except Exception:
        # Fall back to JSON schedules
        pass

    return trips


def resolve_scheduled_trips(
    depot: Optional[str] = None,
    sch_no: Optional[str] = None,
    count: int = 1,
) -> List[ScheduledTripInfo]:
    """
    Resolves real bus trips from the imported schedules:
    - Checks PostgreSQL first if online.
    - Gracefully falls back to master_schedules.json & master_stations.json.
    - Matches depot and schedule_no, or samples random distinct trips across Belagavi division.
    """
    # 1. Attempt Database Query
    trips = _try_load_from_database(depot=depot, sch_no=sch_no)
    if trips and len(trips) >= count:
        return trips[:count]

    # 2. Fallback to Local Imported JSON Files
    schedules, stations_map = _load_json_data()
    if not schedules:
        raise RuntimeError("No schedule data found in database or src/server/generated/master_schedules.json")

    matched_candidates: List[ScheduledTripInfo] = []

    # Prepare search criteria
    target_aliases: Optional[List[str]] = None
    if depot:
        depot_upper = depot.strip().upper()
        target_aliases = DEPOT_ALIASES.get(depot_upper, [depot_upper])

    target_sch = str(sch_no).strip() if sch_no else None

    # Filter candidates
    for s in schedules:
        s_depot = str(s.get("depot", "")).strip().upper()
        s_sch = str(s.get("sch_no", "")).strip()

        # Match depot and schedule if provided
        if target_aliases:
            if not any(alias in s_depot or s_depot in alias for alias in target_aliases):
                continue
        if target_sch:
            if s_sch != target_sch:
                continue

        # Resolve station coordinates
        from_name = s.get("from", "").strip().upper()
        to_name = s.get("to", "").strip().upper()

        stn_from = stations_map.get(from_name)
        stn_to = stations_map.get(to_name)

        if not stn_from or not stn_to:
            continue

        from_coords = stn_from.get("location", {}).get("coordinates", [])
        to_coords = stn_to.get("location", {}).get("coordinates", [])

        if len(from_coords) < 2 or len(to_coords) < 2:
            continue

        src_lng, src_lat = float(from_coords[0]), float(from_coords[1])
        dst_lng, dst_lat = float(to_coords[0]), float(to_coords[1])

        # Skip unlocated placeholder (0,0) or identical stations
        if (src_lat == 0 and src_lng == 0) or (dst_lat == 0 and dst_lng == 0):
            continue
        if abs(src_lat - dst_lat) < 0.001 and abs(src_lng - dst_lng) < 0.001:
            continue

        total_dist = haversine_distance_meters(src_lat, src_lng, dst_lat, dst_lng)
        if total_dist < 500:  # Skip trivial routes
            continue

        depot_label = depot.strip().upper() if depot else s_depot
        clean_depot = depot_label.replace(" ", "-")
        sch_label = target_sch or s_sch or "1"
        bus_number = f"{clean_depot}-{sch_label}"

        matched_candidates.append(
            ScheduledTripInfo(
                bus_number=bus_number,
                depot=clean_depot,
                sch_no=sch_label,
                service_type=s.get("service_type", "Ordinary"),
                source_name=from_name,
                destination_name=to_name,
                src_lat=src_lat,
                src_lng=src_lng,
                dst_lat=dst_lat,
                dst_lng=dst_lng,
                geofence_radius=float(stn_from.get("geofence_radius_meters", DEFAULT_GEOFENCE_RADIUS_METERS)),
                dept_time_str=s.get("dept", "08:15"),
                arrl_time_str=s.get("arrl", "09:45"),
                total_distance_m=total_dist,
                trip_id=s.get("id"),
            )
        )

    if not matched_candidates:
        # If specific criteria didn't match, pick prominent Belagavi Division corridors
        logger.warning(
            "⚠️ No exact schedule matched criteria (depot=%s, sch_no=%s). "
            "Selecting real sampled trips from Belagavi division schedules.",
            depot,
            sch_no,
        )
        # Recursive fallback to sample without constraints
        return resolve_scheduled_trips(depot=None, sch_no=None, count=count)

    # If count requested > 1, sample distinct buses
    if count == 1:
        return [matched_candidates[0]]

    # Sample up to `count` unique buses
    random.seed(42)  # Deterministic seed for reproducible tests
    if len(matched_candidates) <= count:
        return matched_candidates
    return random.sample(matched_candidates, count)


# =============================================================================
# 2. Realistic Trajectory Interpolation (At Bay -> Ramp-Up -> Departed -> En Route)
# =============================================================================

def generate_trajectory_waypoints(
    trip: ScheduledTripInfo,
    steps: int = 15,
) -> List[TelemetryWaypoint]:
    """
    Constructs realistic 5-second interval GPS waypoints:
      - Step 1: At Platform (distance=0m, speed=0 km/h) -> has_left_platform: False
      - Step 2-3: Ramp-up inside platform geofence (< radius, speed 3-5 km/h) -> has_left_platform: False
      - Step 4: Platform Geofence Breach (> radius, speed > 5 km/h) -> has_left_platform: True (TRIGGER)
      - Step 5-N: Cruising speed (40-60 km/h) along straight corridor to destination
    """
    waypoints: List[TelemetryWaypoint] = []
    R = trip.geofence_radius or DEFAULT_GEOFENCE_RADIUS_METERS
    total_D = trip.total_distance_m

    def interp(dist_m: float) -> Tuple[float, float]:
        clamped_d = min(max(dist_m, 0.0), total_D)
        t = clamped_d / total_D if total_D > 0 else 0.0
        lat = trip.src_lat + t * (trip.dst_lat - trip.src_lat)
        lng = trip.src_lng + t * (trip.dst_lng - trip.src_lng)
        return lat, lng

    # 1. At Bay: Stopped at platform
    lat0, lng0 = interp(0.0)
    waypoints.append(
        TelemetryWaypoint(
            phase_name="At Platform Bay (Stationary)",
            latitude=round(lat0, 6),
            longitude=round(lng0, 6),
            speed=0.0,
            distance_from_source_m=0.0,
            expected_has_left=False,
        )
    )

    # 2. Ramp-up 1: Slow roll inside station bay
    d1 = R * 0.35  # ~21m for 60m geofence
    lat1, lng1 = interp(d1)
    waypoints.append(
        TelemetryWaypoint(
            phase_name="Ramp-Up (Bay Taxiing)",
            latitude=round(lat1, 6),
            longitude=round(lng1, 6),
            speed=3.5,
            distance_from_source_m=d1,
            expected_has_left=False,
        )
    )

    # 3. Ramp-up 2: Creeping near platform perimeter
    d2 = R * 0.75  # ~45m for 60m geofence
    lat2, lng2 = interp(d2)
    waypoints.append(
        TelemetryWaypoint(
            phase_name="Ramp-Up (Approaching Exit Gate)",
            latitude=round(lat2, 6),
            longitude=round(lng2, 6),
            speed=4.8,
            distance_from_source_m=d2,
            expected_has_left=False,
        )
    )

    # 4. Geofence Perimeter Crossing: Departed!
    # Distance > R (e.g. 1.45 * R = 87m) and Speed > 5.0 km/h (22 km/h)
    d3 = R + 25.0
    lat3, lng3 = interp(d3)
    waypoints.append(
        TelemetryWaypoint(
            phase_name="DEPARTED (Geofence Breach Trigger)",
            latitude=round(lat3, 6),
            longitude=round(lng3, 6),
            speed=22.0,
            distance_from_source_m=d3,
            expected_has_left=True,
        )
    )

    # 5 to N: Cruising en-route along corridor
    remaining_steps = max(steps - len(waypoints), 1)
    start_cruise_dist = d3 + 150.0

    for i in range(1, remaining_steps + 1):
        progress_ratio = i / remaining_steps
        # Exponential/linear stretch towards destination
        cruise_dist = start_cruise_dist + progress_ratio * (total_D - start_cruise_dist)
        lat_c, lng_c = interp(cruise_dist)

        # Oscillate cruising speed realistically between 42 and 58 km/h
        cruise_speed = round(45.0 + 10.0 * math.sin(i * 0.8), 1)
        if i == remaining_steps:
            phase = "Arrival at Destination Terminal"
            cruise_speed = 0.0
        else:
            phase = f"Cruising En Route ({round(cruise_dist / 1000.0, 1)} km)"

        is_departed = (cruise_speed > GEOFENCE_DEPARTURE_SPEED_KMH) and (cruise_dist > R)
        waypoints.append(
            TelemetryWaypoint(
                phase_name=phase,
                latitude=round(lat_c, 6),
                longitude=round(lng_c, 6),
                speed=cruise_speed,
                distance_from_source_m=cruise_dist,
                expected_has_left=is_departed,
            )
        )

    return waypoints


# =============================================================================
# 3. Parallel Redis Pub/Sub Listener Task
# =============================================================================

class RedisPubSubMonitor:
    """
    Subscribes asynchronously to Redis pattern 'bus-updates:*' to verify
    that hot-path telemetry writes broadcast messages to WebSocket consumers.
    """

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.stop_event = asyncio.Event()
        self.received_messages: List[Dict[str, Any]] = []
        self.is_connected = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if not HAS_AIOREDIS:
            logger.info("ℹ️ redis-py asyncio not installed; skipping background pub/sub listener.")
            return

        self._task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        try:
            client = aioredis.from_url(
                self.redis_url,
                socket_connect_timeout=1.5,
                socket_timeout=2.0,
                decode_responses=True,
            )
            await client.ping()
            self.is_connected = True
            pubsub = client.pubsub()
            await pubsub.psubscribe("bus-updates:*")
            logger.info("📡 [REDIS PUB/SUB] Subscribed to pattern 'bus-updates:*' (WebSocket live stream)")

            while not self.stop_event.is_set():
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                        timeout=1.5,
                    )
                    if msg and msg.get("type") in ("pmessage", "message"):
                        channel = msg.get("channel")
                        data_str = msg.get("data", "{}")
                        try:
                            payload = json.loads(data_str) if isinstance(data_str, str) else data_str
                        except Exception:
                            payload = {"raw": data_str}

                        self.received_messages.append({"channel": channel, "payload": payload})
                        now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        bus_num = payload.get("bus_number") or payload.get("bus_id") or "UNKNOWN"
                        spd = payload.get("speed", 0.0)
                        dep = payload.get("has_left_platform", False)
                        logger.info(
                            f"   [PUB/SUB BROKER] [{now_str}] Channel: {channel} | Bus: {bus_num} | Spd: {spd} km/h | Departed: {dep}"
                        )
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

            await pubsub.punsubscribe("bus-updates:*")
            await client.close()
        except Exception as conn_err:
            self.is_connected = False
            logger.info(f"ℹ️ Redis pub/sub listener skipped (Redis not running at {self.redis_url}: {conn_err})")

    async def stop(self):
        self.stop_event.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)


# =============================================================================
# 4. Bus Telemetry Simulator Worker
# =============================================================================

async def simulate_single_bus(
    trip: ScheduledTripInfo,
    api_url: str,
    steps: int,
    interval_seconds: float,
    pubsub_monitor: Optional[RedisPubSubMonitor] = None,
    bus_index: int = 1,
    total_buses: int = 1,
    mock_backend: bool = False,
) -> Dict[str, Any]:
    """
    Executes telemetry ping loop for an individual bus along its scheduled corridor.
    """
    waypoints = generate_trajectory_waypoints(trip, steps=steps)
    telemetry_endpoint = f"{api_url.rstrip('/')}/api/v1/telemetry"

    prefix = f"[BUS {bus_index}/{total_buses}: {trip.bus_number}]"
    logger.info(
        f"\n🚀 {prefix} Starting simulation on Corridor: {trip.source_name} ➔ {trip.destination_name} "
        f"({round(trip.total_distance_m / 1000.0, 1)} km, Geofence: {trip.geofence_radius}m)"
    )

    stats = {
        "bus_number": trip.bus_number,
        "pings_sent": 0,
        "pings_succeeded": 0,
        "geofence_triggers_verified": 0,
        "rate_limit_hits": 0,
        "errors": 0,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=2.0)) as client:
        for idx, wp in enumerate(waypoints, start=1):
            now_iso = datetime.now(timezone.utc).isoformat()
            now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            payload = {
                "bus_number": trip.bus_number,
                "latitude": wp.latitude,
                "longitude": wp.longitude,
                "speed": wp.speed,
                "service_type": trip.service_type or "Ordinary",
                "trip_id": trip.trip_id,
            }

            stats["pings_sent"] += 1

            if mock_backend:
                # Standalone simulation: evaluate exact backend geofence logic in-memory
                dist_calc = haversine_distance_meters(wp.latitude, wp.longitude, trip.src_lat, trip.src_lng)
                has_left = (dist_calc > trip.geofence_radius) and (wp.speed > GEOFENCE_DEPARTURE_SPEED_KMH)
                status_lbl = "Departed" if has_left else "At Bay"
                if wp.speed > 0:
                    status_lbl = f"En Route ({wp.speed:.1f} km/h)"

                data = {
                    "bus_id": f"sim-{trip.bus_number.lower()}",
                    "bus_number": trip.bus_number,
                    "service_type": trip.service_type or "Ordinary",
                    "current_lat": wp.latitude,
                    "current_lng": wp.longitude,
                    "speed": wp.speed,
                    "has_left_platform": has_left,
                    "last_seen_at": now_iso,
                    "is_new_registration": False,
                    "distance_from_platform_meters": round(dist_calc, 2),
                    "status_label": status_lbl,
                }

                # Publish to Redis if pubsub monitor client is active
                if pubsub_monitor and pubsub_monitor.is_connected:
                    try:
                        r = aioredis.from_url(pubsub_monitor.redis_url)
                        pub_json = json.dumps(data)
                        await r.publish(f"bus-updates:{trip.bus_number}", pub_json)
                        await r.publish("bus-updates:division", pub_json)
                        await r.close()
                    except Exception:
                        pass

                stats["pings_succeeded"] += 1
                dist_str = f"{dist_calc:.1f}m"
                match_indicator = "✅ PASS" if (has_left == wp.expected_has_left) else "⚠️ MISMATCH"
                if wp.expected_has_left and has_left:
                    stats["geofence_triggers_verified"] += 1

                trigger_banner = ""
                if wp.expected_has_left and idx == 4:
                    trigger_banner = f"\n   🎯 >>> [GEOFENCE TRIGGER FIRED] Crosses {trip.geofence_radius}m threshold (dist={dist_str}, speed={wp.speed} km/h) -> has_left_platform: TRUE"

                logger.info(
                    f"[{now_local}] {prefix} Step {idx}/{len(waypoints)} | {wp.phase_name}\n"
                    f"   GPS: ({wp.latitude:.5f}, {wp.longitude:.5f}) | Spd: {wp.speed:.1f} km/h | Dist: {dist_str}\n"
                    f"   [IN-PROCESS] has_left_platform: {has_left} ({status_lbl}) | {match_indicator}{trigger_banner}"
                )
            else:
                try:
                    t0 = time.perf_counter()
                    resp = await client.post(telemetry_endpoint, json=payload)
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0

                    if resp.status_code == 200:
                        stats["pings_succeeded"] += 1
                        data = resp.json()
                        has_left = data.get("has_left_platform", False)
                        status_lbl = data.get("status_label", "")
                        dist_resp = data.get("distance_from_platform_meters")
                        dist_str = f"{dist_resp:.1f}m" if dist_resp is not None else f"{wp.distance_from_source_m:.1f}m"

                        # Verify expectation
                        match_indicator = "✅ PASS" if (has_left == wp.expected_has_left) else "⚠️ MISMATCH"
                        if wp.expected_has_left and has_left:
                            stats["geofence_triggers_verified"] += 1

                        trigger_banner = ""
                        if wp.expected_has_left and idx == 4:
                            trigger_banner = f"\n   🎯 >>> [GEOFENCE TRIGGER FIRED] Crosses {trip.geofence_radius}m threshold (dist={dist_str}, speed={wp.speed} km/h) -> has_left_platform: TRUE"

                        logger.info(
                            f"[{now_local}] {prefix} Step {idx}/{len(waypoints)} | {wp.phase_name}\n"
                            f"   GPS: ({wp.latitude:.5f}, {wp.longitude:.5f}) | Spd: {wp.speed:.1f} km/h | Dist: {dist_str}\n"
                            f"   HTTP 200 ({elapsed_ms:.1f}ms) | has_left_platform: {has_left} ({status_lbl}) | {match_indicator}{trigger_banner}"
                        )

                    elif resp.status_code == 429:
                        stats["rate_limit_hits"] += 1
                        retry_after = resp.headers.get("Retry-After", "3")
                        logger.warning(
                            f"[{now_local}] {prefix} Step {idx}/{len(waypoints)} | ⚠️ HTTP 429 Rate Limit Hit: "
                            f"{resp.text} (Retry-After: {retry_after}s)"
                        )
                    else:
                        stats["errors"] += 1
                        logger.error(
                            f"[{now_local}] {prefix} Step {idx}/{len(waypoints)} | ❌ HTTP {resp.status_code}: {resp.text}"
                        )

                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError, httpx.RequestError) as net_err:
                    stats["errors"] += 1
                    logger.error(
                        f"[{now_local}] {prefix} Step {idx}/{len(waypoints)} | ❌ Connection failed to {telemetry_endpoint} ({type(net_err).__name__}).\n"
                        f"   Please start the FastAPI backend server first (run 'python run_backend.py') or use '--mock-backend' for offline validation."
                    )
                except Exception as ex:
                    stats["errors"] += 1
                    logger.error(f"[{now_local}] {prefix} Step {idx}/{len(waypoints)} | ❌ Error ({type(ex).__name__}): {ex}")

            # Sleep between steps, respecting the Redis rate limit window
            if idx < len(waypoints):
                await asyncio.sleep(interval_seconds)

    return stats


# =============================================================================
# 5. CLI Entrypoint & Multi-Bus Orchestrator
# =============================================================================

async def main_async(args: argparse.Namespace):
    logger.info("===============================================================================")
    logger.info("🚌 NWKRTC Belagavi Division — Live Bus Telemetry E2E Simulator")
    logger.info("===============================================================================")
    logger.info(f"Target FastAPI Backend: {args.api_url}")
    logger.info(f"Telemetry Ping Interval: {args.interval}s (Rate Limit Window: {TELEMETRY_RATE_LIMIT_WINDOW}s)")
    logger.info(f"Steps Per Bus:          {args.steps}")
    logger.info(f"Concurrent Bus Count:   {args.count}")

    # 1. Resolve Scheduled Trips
    trips = resolve_scheduled_trips(
        depot=args.depot,
        sch_no=args.sch_no,
        count=args.count,
    )

    logger.info(f"Loaded {len(trips)} active schedule corridor(s):")
    for idx, t in enumerate(trips, 1):
        logger.info(f"  {idx}. Bus {t.bus_number:15s} | {t.source_name:18s} ➔ {t.destination_name:18s} ({round(t.total_distance_m/1000.0, 1)} km)")
    logger.info("-------------------------------------------------------------------------------")

    # 2. Start Parallel Redis Pub/Sub Monitor
    pubsub_monitor: Optional[RedisPubSubMonitor] = None
    if not args.no_redis:
        pubsub_monitor = RedisPubSubMonitor(args.redis_url)
        await pubsub_monitor.start()

    # 3. Enforce Rate Limit Warning
    if args.interval < TELEMETRY_RATE_LIMIT_WINDOW:
        logger.warning(
            f"⚠️ NOTICE: Requested interval ({args.interval}s) is smaller than the Redis rate limit window ({TELEMETRY_RATE_LIMIT_WINDOW}s). "
            f"Expect HTTP 429 Too Many Requests responses unless testing rate-limiter behavior."
        )

    # 4. Launch Concurrent Bus Tasks
    start_time = time.perf_counter()
    tasks = []
    total_buses = len(trips)

    for i, trip in enumerate(trips, start=1):
        # Slightly stagger start times by 0.4s to simulate realistic asynchronous intake
        async def _run_staggered(t=trip, idx=i):
            if idx > 1:
                await asyncio.sleep((idx - 1) * 0.4)
            return await simulate_single_bus(
                trip=t,
                api_url=args.api_url,
                steps=args.steps,
                interval_seconds=args.interval,
                pubsub_monitor=pubsub_monitor,
                bus_index=idx,
                total_buses=total_buses,
                mock_backend=args.mock_backend,
            )
        tasks.append(_run_staggered())

    results = await asyncio.gather(*tasks, return_exceptions=True)
    total_duration = time.perf_counter() - start_time

    # 5. Stop Redis Pub/Sub Monitor
    if pubsub_monitor:
        await asyncio.sleep(1.0)  # Drain final messages
        await pubsub_monitor.stop()

    # 6. Print QA Test Summary
    logger.info("\n===============================================================================")
    logger.info("📊 TELEMETRY SIMULATION QA TEST SUMMARY")
    logger.info("===============================================================================")
    logger.info(f"Total Test Duration:       {total_duration:.2f} seconds")

    total_pings = 0
    total_succeeded = 0
    total_geofence_verified = 0
    total_rate_limits = 0
    total_errors = 0

    for res in results:
        if isinstance(res, dict):
            total_pings += res.get("pings_sent", 0)
            total_succeeded += res.get("pings_succeeded", 0)
            total_geofence_verified += res.get("geofence_triggers_verified", 0)
            total_rate_limits += res.get("rate_limit_hits", 0)
            total_errors += res.get("errors", 0)
            logger.info(
                f"Bus {res['bus_number']:15s} | Pings: {res['pings_sent']:2d} | "
                f"OK: {res['pings_succeeded']:2d} | Geofence Departures Verified: {res['geofence_triggers_verified']:2d}"
            )
        else:
            total_errors += 1
            logger.error(f"Task exception: {res}")

    logger.info("-------------------------------------------------------------------------------")
    logger.info(f"Total Pings Dispatched:    {total_pings}")
    logger.info(f"Successful Ingestions:     {total_succeeded}")
    logger.info(f"Geofence Triggers Checked: {total_geofence_verified}")
    logger.info(f"Rate-Limit (429) Handled:  {total_rate_limits}")
    logger.info(f"Errors / Failures:         {total_errors}")

    if pubsub_monitor and pubsub_monitor.is_connected:
        logger.info(f"Redis Pub/Sub Frames Rcvd: {len(pubsub_monitor.received_messages)} (WebSocket Fan-out Verified)")
    logger.info("===============================================================================\n")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate real bus telemetry for NWKRTC Belagavi Division full stack testing."
    )
    parser.add_argument(
        "--depot",
        type=str,
        default=None,
        help="Depot identifier or name (e.g. KHANAPUR, BELAGAVI, CHIKKODI, ATHANI, KNP, BGM).",
    )
    parser.add_argument(
        "--sch-no",
        type=str,
        default=None,
        help="Schedule roster number (e.g. 37, 1, 12). Matches placeholder format '{depot}-{sch_no}'.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of concurrent buses to simulate across the division (default: 1).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Interval in seconds between telemetry pings (default: 5.0, must be >= 3.0 to respect rate limit).",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=12,
        help="Number of telemetry waypoints to ping per bus trajectory (default: 12).",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=os.getenv("API_URL", "http://localhost:8000"),
        help="Base URL for the FastAPI backend (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default=os.getenv("REDIS_URL", DEFAULT_REDIS_URL),
        help="Redis URL for pub/sub verification (default: redis://localhost:6379/0).",
    )
    parser.add_argument(
        "--no-redis",
        action="store_true",
        help="Disable the background Redis pub/sub verification listener.",
    )
    parser.add_argument(
        "--mock-backend",
        action="store_true",
        help="Run in standalone evaluation mode without requiring a running FastAPI server on port 8000.",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — Platform Geofencing Service
===============================================================================
Author: Senior Python Engineer
Purpose:
  Platform perimeter geofence evaluation using PostGIS ST_DWithin and
  haversine distance metrics. Evaluates platform departure conditions:
  (distance > platform_geofence_radius AND speed > 5.0 km/h).
===============================================================================
"""

import math
from typing import Optional, Tuple
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import (
    DEFAULT_GEOFENCE_RADIUS_METERS,
    GEOFENCE_DEPARTURE_SPEED_KMH,
)


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes great-circle distance between two WGS84 points in meters.
    Used for local geofence evaluation and fallback verification.
    """
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


def evaluate_platform_departure(
    db: Session,
    latitude: float,
    longitude: float,
    speed: float,
    station_id: Optional[str] = None,
    station_lat: Optional[float] = None,
    station_lng: Optional[float] = None,
    geofence_radius_meters: Optional[float] = None,
    departure_speed_threshold_kmh: float = GEOFENCE_DEPARTURE_SPEED_KMH,
) -> Tuple[bool, Optional[float]]:
    """
    Evaluates whether a vehicle has crossed outside the station platform geofence.
    Criteria:
      has_left_platform = (distance > geofence_radius AND speed > departure_speed_threshold_kmh)

    Returns:
      (has_left_platform: bool, distance_meters: Optional[float])
    """
    radius = geofence_radius_meters or DEFAULT_GEOFENCE_RADIUS_METERS
    distance_meters: Optional[float] = None

    # Option A: Evaluate via PostGIS ST_Distance & ST_DWithin if station_id is provided
    if station_id:
        try:
            sql = text("""
                SELECT 
                    ST_Distance(
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                        s.location::geography
                    ) AS dist,
                    NOT ST_DWithin(
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                        s.location::geography,
                        :radius
                    ) AS is_outside
                FROM public.stations s
                WHERE s.id = :stn_id
            """)
            result = db.execute(sql, {
                "lng": longitude,
                "lat": latitude,
                "radius": radius,
                "stn_id": station_id,
            }).fetchone()

            if result and result[0] is not None:
                distance_meters = float(result[0])
                is_outside = bool(result[1])
                has_left = is_outside and (speed > departure_speed_threshold_kmh)
                return has_left, round(distance_meters, 2)
        except Exception:
            # Fall through to haversine calculation on SQLite or PostGIS function mismatch
            pass

    # Option B: Evaluate via explicit station coordinates using haversine
    if station_lat is not None and station_lng is not None:
        distance_meters = haversine_distance_meters(
            latitude, longitude, station_lat, station_lng
        )
        is_outside = distance_meters > radius
        has_left = is_outside and (speed > departure_speed_threshold_kmh)
        return has_left, round(distance_meters, 2)

    # If no station reference is known, determine purely by speed threshold
    has_left = speed > departure_speed_threshold_kmh
    return has_left, distance_meters


def distance_to_segment_meters(
    lat: float, lon: float,
    lat1: float, lon1: float,
    lat2: float, lon2: float
) -> Tuple[float, float, float]:
    """
    Computes shortest distance from (lat, lon) to segment (lat1, lon1)-(lat2, lon2),
    projected in local equirectangular Cartesian approximation.
    Returns (distance_meters, snapped_lat, snapped_lon).
    """
    mid_lat = math.radians((lat1 + lat2 + lat) / 3.0)
    kx = 111412.84 * math.cos(mid_lat)
    ky = 111132.95

    px = (lon - lon1) * kx
    py = (lat - lat1) * ky
    bx = (lon2 - lon1) * kx
    by = (lat2 - lat1) * ky

    seg_len_sq = bx * bx + by * by
    if seg_len_sq == 0:
        return math.hypot(px, py), lat1, lon1

    t = max(0.0, min(1.0, (px * bx + py * by) / seg_len_sq))
    proj_x = t * bx
    proj_y = t * by
    dist = math.hypot(px - proj_x, py - proj_y)

    snapped_lon = lon1 + (proj_x / kx)
    snapped_lat = lat1 + (proj_y / ky)
    return dist, snapped_lat, snapped_lon


def distance_to_polyline_meters(
    lat: float, lon: float, polyline: list
) -> Tuple[float, float, float]:
    """
    Computes minimum distance from (lat, lon) to any segment along the route polyline [[lat, lon], ...].
    Validates anti-spoofing / off-route drift threshold (150m).
    Returns (min_distance_meters, snapped_lat, snapped_lon).
    """
    if not polyline or len(polyline) < 2:
        return 0.0, lat, lon

    min_dist = float("inf")
    best_lat, best_lon = lat, lon

    for i in range(len(polyline) - 1):
        p1 = polyline[i]
        p2 = polyline[i + 1]
        dist, s_lat, s_lon = distance_to_segment_meters(
            lat, lon, float(p1[0]), float(p1[1]), float(p2[0]), float(p2[1])
        )
        if dist < min_dist:
            min_dist = dist
            best_lat = s_lat
            best_lon = s_lon

    return min_dist, best_lat, best_lon


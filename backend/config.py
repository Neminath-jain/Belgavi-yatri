"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — Redis Configuration & Key Schema
===============================================================================
Author: Senior Backend Infrastructure Engineer
Purpose:
  Centralized Redis configuration, connection parameters, key naming conventions,
  TTL constants, and rate-limiting rules for high-throughput live bus telemetry.
===============================================================================
"""

import os
from typing import Final

# -----------------------------------------------------------------------------
# 1. Connection Settings
# -----------------------------------------------------------------------------
DATABASE_URL: Final[str] = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/postgres",
)

REDIS_HOST: Final[str] = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: Final[int] = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB: Final[int] = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD: Final[str | None] = os.getenv("REDIS_PASSWORD", None)
REDIS_URL: Final[str] = os.getenv(
    "REDIS_URL",
    f"redis://{f':{REDIS_PASSWORD}@' if REDIS_PASSWORD else ''}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
)

# Connection Pool Defaults
REDIS_POOL_MAX_CONNECTIONS: Final[int] = int(os.getenv("REDIS_POOL_MAX_CONNECTIONS", "50"))
REDIS_SOCKET_TIMEOUT: Final[float] = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2.5"))
REDIS_CONNECT_TIMEOUT: Final[float] = float(os.getenv("REDIS_CONNECT_TIMEOUT", "3.0"))

# CORS Configuration
CORS_ORIGINS: Final[list[str]] = os.getenv("CORS_ORIGINS", "*").split(",")

# Geofencing Constants (Belagavi CBT Bay Geofence: 65m, Departure threshold: 8 km/h)
DEFAULT_GEOFENCE_RADIUS_METERS: Final[float] = float(os.getenv("DEFAULT_GEOFENCE_RADIUS_METERS", "65.0"))
GEOFENCE_DEPARTURE_SPEED_KMH: Final[float] = float(os.getenv("GEOFENCE_DEPARTURE_SPEED_KMH", "8.0"))

# -----------------------------------------------------------------------------
# 2. TTL Constants (in seconds)
# -----------------------------------------------------------------------------
# GET /api/v1/stations: rarely changes, invalidated on importer/geocoder execution
STATIONS_CACHE_TTL: Final[int] = int(os.getenv("STATIONS_CACHE_TTL", "3600"))  # 1 hour

# GET /api/v1/buses/search: changes frequently as buses move along corridors
BUS_SEARCH_CACHE_TTL: Final[int] = int(os.getenv("BUS_SEARCH_CACHE_TTL", "20"))  # 20 seconds (15-30s range)

# Hot telemetry cache per bus: expires after 24 hours of inactivity
BUS_TELEMETRY_TTL: Final[int] = int(os.getenv("BUS_TELEMETRY_TTL", "86400"))  # 24 hours

# Write-behind stream retention (approx 2 hours of buffer)
WRITE_BEHIND_STREAM_MAXLEN: Final[int] = int(os.getenv("WRITE_BEHIND_STREAM_MAXLEN", "50000"))

# -----------------------------------------------------------------------------
# 3. Rate Limiting Constants
# -----------------------------------------------------------------------------
# POST /api/v1/telemetry: max 1 update per 3 seconds per bus
TELEMETRY_RATE_LIMIT_WINDOW: Final[float] = 3.0  # seconds
TELEMETRY_RATE_LIMIT_MAX_REQUESTS: Final[int] = 1

# -----------------------------------------------------------------------------
# 4. Redis Key-Naming Conventions
# -----------------------------------------------------------------------------
class RedisKeys:
    """
    Standardized, namespace-isolated key naming conventions.
    All keys adhere to: ksrtc:<domain>:<entity>[:<identifier>]
    """

    # Geospatial Index (GEOADD) containing current coordinates for all active buses
    # Structure: ZSET (Geospatial) -> member: bus_id, score: geohash
    BUS_POSITIONS_GEO: Final[str] = "bus:positions"

    # Pub/Sub Channels
    # Channel for per-bus updates consumed by FastAPI WebSockets: bus-updates:{bus_id}
    @staticmethod
    def bus_channel(bus_id: str) -> str:
        return f"bus-updates:{bus_id}"

    # Division-wide fanout channel (e.g. Belagavi CBT radar overview)
    DIVISION_UPDATES_CHANNEL: Final[str] = "bus-updates:division"

    # Telemetry State Hash / String (stores speed, last_seen, platform status)
    @staticmethod
    def bus_telemetry(bus_id: str) -> str:
        return f"bus:telemetry:{bus_id}"

    # Caching: Stations List
    STATIONS_CACHE: Final[str] = "cache:stations:all"

    # Caching: Bus Search Results per (source, destination) query
    @staticmethod
    def bus_search_cache(source: str, destination: str) -> str:
        s = source.strip().lower() if source else "any"
        d = destination.strip().lower() if destination else "any"
        return f"cache:search:{s}:{d}"

    # Rate Limiting: Sliding Window key per bus_number
    @staticmethod
    def rate_limit_telemetry(bus_number: str) -> str:
        clean_no = bus_number.strip().upper().replace(" ", "-")
        return f"ratelimit:telemetry:{clean_no}"

    # Write-behind buffer stream for asynchronous Postgres persistence
    WRITE_BEHIND_STREAM: Final[str] = "stream:telemetry:write_behind"
    WRITE_BEHIND_CONSUMER_GROUP: Final[str] = "group:pg_writer"


# -----------------------------------------------------------------------------
# 5. DPDP Act 2023 Reasonable Security Safeguards & Access Control
# -----------------------------------------------------------------------------
SERVICE_ACCOUNT_API_KEY: Final[str] = os.getenv(
    "SERVICE_ACCOUNT_API_KEY",
    "dev-service-key-belagavi",
)
ADMIN_API_KEY: Final[str] = os.getenv(
    "ADMIN_API_KEY",
    "dev-admin-key-belagavi",
)
DPDP_RETENTION_PERIOD_DAYS: Final[int] = int(
    os.getenv("DPDP_RETENTION_PERIOD_DAYS", "730")
)  # 24 months storage limitation
DPDP_PII_SECRET: Final[bytes] = os.getenv(
    "DPDP_PII_SECRET",
    "ksrtc-belagavi-dpdp-pii-encryption-salt-2025",
).encode("utf-8")
ENFORCE_HSTS: Final[bool] = os.getenv("ENFORCE_HSTS", "true").lower() in ("true", "1", "yes")


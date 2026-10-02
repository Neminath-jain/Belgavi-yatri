"""
Comprehensive integration and functional tests for the FastAPI backend endpoints:
  1. GET /health
  2. GET /api/v1/stations (Excludes unresolved stations and (0,0) placeholders, verifies Redis caching)
  3. GET /api/v1/buses/search (404 on unknown stations, fallback on no direct route, merges Redis live telemetry)
  4. POST /api/v1/telemetry (Sliding-window rate limit, auto-registration, ST_DWithin geofence, Redis GEOADD)
"""

import asyncio
from datetime import datetime, timezone, timedelta
import sqlite3
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from geoalchemy2.admin.dialects import sqlite as gsqlite
import fakeredis.aioredis as fake_aio
import shapely.wkt
import shapely.wkb

from backend.config import RedisKeys
from backend.database import Base, get_db
from backend.main import app
from backend.models import Bus, Station, Trip, UnresolvedStation
from backend.redis_client import get_redis_dependency
from backend.redis_service import record_bus_telemetry

# -----------------------------------------------------------------------------
# SQLite SpatiaLite Simulation for Standalone Testing
# -----------------------------------------------------------------------------
gsqlite.after_create = lambda *a, **k: None
gsqlite.before_create = lambda *a, **k: None


@compiles(Geometry, "sqlite")
def compile_geom_sqlite(type_, compiler, **kw):
    return "TEXT"


def _sqlite_to_ewkb(val):
    if not val:
        return None
    if isinstance(val, bytes):
        return val if len(val) > 0 else None
    val_str = str(val)
    if "POINT" in val_str:
        wkt = val_str.split(";")[-1]
        geom = shapely.wkt.loads(wkt)
        return shapely.wkb.dumps(geom)
    return str(val).encode("utf-8")


class TestFastAPIEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an in-memory SQLite database for standalone testing
        from sqlalchemy.pool import StaticPool
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def setup_sqlite_spatial_functions(conn, rec):
            if isinstance(conn, sqlite3.Connection):
                conn.create_function("GeomFromEWKT", 1, lambda v: v)
                conn.create_function("ST_GeomFromEWKT", 1, lambda v: v)
                conn.create_function("AsEWKB", 1, _sqlite_to_ewkb)
                conn.create_function("AsBinary", 1, _sqlite_to_ewkb)

        Base.metadata.create_all(cls.engine)
        cls.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=cls.engine
        )

    def setUp(self):
        self.db = self.TestingSessionLocal()
        # Clean database tables
        self.db.query(UnresolvedStation).delete()
        self.db.query(Trip).delete()
        self.db.query(Bus).delete()
        self.db.query(Station).delete()
        self.db.commit()

        # Create an isolated in-memory fakeredis client for each test
        self.fake_redis = fake_aio.FakeRedis(decode_responses=True)

        # Dependency Overrides
        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        async def override_get_redis():
            yield self.fake_redis

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_redis_dependency] = override_get_redis

        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.clear()
        asyncio.run(self.fake_redis.flushall())
        asyncio.run(self.fake_redis.aclose())

    # =========================================================================
    # 1. Health Endpoint Tests
    # =========================================================================
    def test_health_check(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("services", data)

    # =========================================================================
    # 2. GET /api/v1/stations Tests
    # =========================================================================
    def test_get_stations_exclusion_and_caching(self):
        """
        Verify:
          1. Resolved stations are listed.
          2. Placeholder (0, 0) coordinates are excluded.
          3. Stations present in unresolved_stations are excluded.
          4. Results are cached in Redis.
        """
        # A. Normal resolved station
        stn1 = Station(
            id=uuid.uuid4(),
            name="BELAGAVI CBT",
            platform_name="Bay 1",
            location=WKTElement("POINT(74.5065 15.8573)", srid=4326),
            geofence_radius_meters=65.0,
            geocode_source="manual_override",
        )
        # B. Second resolved station
        stn2 = Station(
            id=uuid.uuid4(),
            name="CHIKKODI",
            platform_name="Bay 2",
            location=WKTElement("POINT(74.5960 16.4300)", srid=4326),
            geofence_radius_meters=60.0,
            geocode_source="nominatim:station",
        )
        # C. Station with placeholder coordinates (0, 0) -> MUST BE EXCLUDED
        stn_placeholder = Station(
            id=uuid.uuid4(),
            name="PLACEHOLDER STOP",
            location=WKTElement("POINT(0 0)", srid=4326),
            geofence_radius_meters=60.0,
            geocode_source=None,
        )
        # D. Station in unresolved_stations quarantine -> MUST BE EXCLUDED
        stn_unresolved = Station(
            id=uuid.uuid4(),
            name="UNRESOLVED TOWN",
            location=WKTElement("POINT(74.9000 16.0000)", srid=4326),
            geofence_radius_meters=60.0,
            geocode_source="unresolved_osm",
        )
        self.db.add_all([stn1, stn2, stn_placeholder, stn_unresolved])
        self.db.commit()

        # Add stn_unresolved to quarantine table
        unresolved_record = UnresolvedStation(
            id=uuid.uuid4(),
            station_id=stn_unresolved.id,
            name="UNRESOLVED TOWN",
            attempted_query="UNRESOLVED TOWN",
            reason="Ambiguous state centroid match",
        )
        self.db.add(unresolved_record)
        self.db.commit()

        # 1. First call: Cache miss -> queries DB and populates Redis
        resp1 = self.client.get("/api/v1/stations")
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()

        station_names = [s["name"] for s in data1]
        self.assertIn("BELAGAVI CBT", station_names)
        self.assertIn("CHIKKODI", station_names)
        self.assertNotIn("PLACEHOLDER STOP", station_names)
        self.assertNotIn("UNRESOLVED TOWN", station_names)
        self.assertEqual(len(data1), 2)

        # Check GeoJSON format
        cbt = next(s for s in data1 if s["name"] == "BELAGAVI CBT")
        self.assertEqual(cbt["location"]["type"], "Point")
        self.assertAlmostEqual(cbt["location"]["coordinates"][0], 74.5065, places=3)
        self.assertAlmostEqual(cbt["location"]["coordinates"][1], 15.8573, places=3)

        # Verify Redis now contains the cached JSON string
        cached_raw = asyncio.run(self.fake_redis.get(RedisKeys.STATIONS_CACHE))
        self.assertIsNotNone(cached_raw)

        # 2. Second call: Cache hit from Redis
        resp2 = self.client.get("/api/v1/stations")
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(len(data2), 2)

    # =========================================================================
    # 3. GET /api/v1/buses/search Tests
    # =========================================================================
    def test_search_buses_nonexistent_station_404(self):
        """Requirement: return clear 404 error if requested station does not exist in directory."""
        stn = Station(
            id=uuid.uuid4(),
            name="BELAGAVI CBT",
            location=WKTElement("POINT(74.5065 15.8573)", srid=4326),
        )
        self.db.add(stn)
        self.db.commit()

        # A. Non-existent source station
        resp = self.client.get("/api/v1/buses/search?source=UNKNOWN_NONEXISTENT_STATION")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("Source station 'UNKNOWN_NONEXISTENT_STATION' does not exist", resp.json()["detail"])

        # B. Non-existent destination station
        resp = self.client.get("/api/v1/buses/search?source=BELAGAVI%20CBT&destination=MARS_TERMINAL")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("Destination station 'MARS_TERMINAL' does not exist", resp.json()["detail"])

    def test_search_buses_pure_schedule_no_gps_fabrication(self):
        """
        Requirement: if a bus has no live telemetry yet, return current_lat/current_lng as null
        and is_stale = true rather than fabricating a position.
        """
        stn1 = Station(
            id=uuid.uuid4(),
            name="BELAGAVI CBT",
            platform_name="Bay 1",
            location=WKTElement("POINT(74.5065 15.8573)", srid=4326),
        )
        stn2 = Station(
            id=uuid.uuid4(),
            name="CHIKKODI",
            platform_name="Bay 2",
            location=WKTElement("POINT(74.5960 16.4300)", srid=4326),
        )
        bus = Bus(
            id=uuid.uuid4(),
            bus_number="KA-22-F-1890",
            service_type="Vegadhoot",
            current_location=None,  # No GPS position reported yet
            speed=0.0,
            has_left_platform=False,
            last_seen_at=None,
        )
        trip = Trip(
            id=uuid.uuid4(),
            bus_id=bus.id,
            source_station_id=stn1.id,
            destination_station_id=stn2.id,
            departure_time=datetime.now(timezone.utc) + timedelta(minutes=15),
            route_via="Sankeshwar",
            status="scheduled",
            depot="Belagavi-1",
            schedule_no="SCH-12",
        )
        self.db.add_all([stn1, stn2, bus, trip])
        self.db.commit()

        resp = self.client.get("/api/v1/buses/search?source=BELAGAVI%20CBT&destination=CHIKKODI")
        self.assertEqual(resp.status_code, 200)
        results = resp.json()
        self.assertGreaterEqual(len(results), 1)

        bus_res = results[0]
        self.assertEqual(bus_res["bus_number"], "KA-22-F-1890")
        self.assertIsNone(bus_res["current_lat"])
        self.assertIsNone(bus_res["current_lng"])
        self.assertTrue(bus_res["is_stale"])
        self.assertFalse(bus_res["has_left_platform"])
        self.assertEqual(bus_res["depot"], "Belagavi-1")
        self.assertEqual(bus_res["schedule_no"], "SCH-12")

    def test_search_buses_merges_redis_live_telemetry(self):
        """
        Requirement: merge in live position/speed from Redis geospatial cache where available.
        """
        stn1 = Station(
            id=uuid.uuid4(),
            name="BELAGAVI CBT",
            location=WKTElement("POINT(74.5065 15.8573)", srid=4326),
        )
        stn2 = Station(
            id=uuid.uuid4(),
            name="ATHANI",
            location=WKTElement("POINT(75.0592 16.7328)", srid=4326),
        )
        bus_id = uuid.uuid4()
        bus = Bus(
            id=bus_id,
            bus_number="KA-22-F-1904",
            service_type="Rajahamsa",
            current_location=None,
            speed=0.0,
            has_left_platform=False,
        )
        trip = Trip(
            id=uuid.uuid4(),
            bus_id=bus.id,
            source_station_id=stn1.id,
            destination_station_id=stn2.id,
            departure_time=datetime.now(timezone.utc) - timedelta(minutes=20),
            status="in_transit",
            depot="Athani",
            schedule_no="SCH-55",
        )
        self.db.add_all([stn1, stn2, bus, trip])
        self.db.commit()

        # Seed hot telemetry in Redis for this bus
        asyncio.run(
            record_bus_telemetry(
                redis_client=self.fake_redis,
                bus_id=str(bus_id),
                bus_number="KA-22-F-1904",
                latitude=16.1280,
                longitude=74.5290,
                speed=72.0,
                has_left_platform=True,
            )
        )

        resp = self.client.get("/api/v1/buses/search?source=BELAGAVI%20CBT&destination=ATHANI")
        self.assertEqual(resp.status_code, 200)
        results = resp.json()
        self.assertGreaterEqual(len(results), 1)

        bus_res = results[0]
        self.assertEqual(bus_res["bus_number"], "KA-22-F-1904")
        self.assertAlmostEqual(bus_res["current_lat"], 16.1280, places=3)
        self.assertAlmostEqual(bus_res["current_lng"], 74.5290, places=3)
        self.assertEqual(bus_res["speed"], 72.0)
        self.assertTrue(bus_res["has_left_platform"])
        self.assertFalse(bus_res["is_stale"])
        self.assertIn("En Route", bus_res["status_label"])

    # =========================================================================
    # 4. POST /api/v1/telemetry Tests
    # =========================================================================
    def test_post_telemetry_auto_registration_and_redis_ingest(self):
        """
        Requirement:
          - First-time bus reporting is auto-registered.
          - Position written to Redis geospatial index.
          - Returns 200 OK.
        """
        payload = {
            "bus_number": "KA-22-F-9999",
            "latitude": 15.8580,
            "longitude": 74.5070,
            "speed": 0.0,
        }
        resp = self.client.post("/api/v1/telemetry", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["bus_number"], "KA-22-F-9999")
        self.assertTrue(data["is_new_registration"])
        self.assertFalse(data["has_left_platform"])

        # Check vehicle exists in database
        bus_in_db = self.db.query(Bus).filter(Bus.bus_number == "KA-22-F-9999").first()
        self.assertIsNotNone(bus_in_db)

        # Check vehicle exists in Redis geospatial index
        pos = asyncio.run(self.fake_redis.geopos(RedisKeys.BUS_POSITIONS_GEO, "KA-22-F-9999"))
        self.assertIsNotNone(pos)
        self.assertIsNotNone(pos[0])

    def test_post_telemetry_rate_limiting(self):
        """
        Requirement: rate-limited via Redis (max 1 update per 3 seconds per bus).
        Rapid consecutive pings must return HTTP 429 Too Many Requests.
        """
        payload = {
            "bus_number": "KA-22-F-1892",
            "latitude": 15.8573,
            "longitude": 74.5065,
            "speed": 10.0,
        }

        # First request succeeds
        resp1 = self.client.post("/api/v1/telemetry", json=payload)
        self.assertEqual(resp1.status_code, 200)

        # Immediate second request is blocked by sliding-window rate limiter
        resp2 = self.client.post("/api/v1/telemetry", json=payload)
        self.assertEqual(resp2.status_code, 429)
        self.assertIn("Rate limit exceeded", resp2.json()["detail"])
        self.assertIn("Retry-After", resp2.headers)

    def test_post_telemetry_geofence_departure(self):
        """
        Requirement:
          Run geofence check (ST_DWithin / haversine, > configurable radius AND speed > 5 km/h)
          to update has_left_platform.
        """
        # Create station at (15.8573, 74.5065) with 60m radius
        stn = Station(
            id=uuid.uuid4(),
            name="BELAGAVI CBT",
            location=WKTElement("POINT(74.5065 15.8573)", srid=4326),
            geofence_radius_meters=60.0,
        )
        bus_id = uuid.uuid4()
        bus = Bus(
            id=bus_id,
            bus_number="KA-22-F-5555",
            service_type="Ordinary",
            has_left_platform=False,
        )
        trip = Trip(
            id=uuid.uuid4(),
            bus_id=bus.id,
            source_station_id=stn.id,
            destination_station_id=stn.id,
            departure_time=datetime.now(timezone.utc),
            status="scheduled",
        )
        self.db.add_all([stn, bus, trip])
        self.db.commit()

        # Telemetry ping at point ~200m away with speed 35 km/h (> 5 km/h)
        payload = {
            "bus_number": "KA-22-F-5555",
            "latitude": 15.8590,
            "longitude": 74.5080,
            "speed": 35.0,
        }
        resp = self.client.post("/api/v1/telemetry", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["has_left_platform"])
        self.assertEqual(data["status_label"], "En Route (35.0 km/h)")


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for Pydantic transit models and data transfer validation.
"""

import unittest
from pydantic import ValidationError
from backend.schemas import (
    BusSearchResponse,
    TelemetryInput,
    TelemetryResponse,
    StationResponse,
)


class TestSchemas(unittest.TestCase):
    def test_telemetry_input_valid(self):
        payload = {
            "bus_number": "KA-22-F-1892",
            "latitude": 15.8573,
            "longitude": 74.5065,
            "speed": 42.5,
        }
        obj = TelemetryInput(**payload)
        self.assertEqual(obj.bus_number, "KA-22-F-1892")
        self.assertEqual(obj.latitude, 15.8573)
        self.assertEqual(obj.longitude, 74.5065)
        self.assertEqual(obj.speed, 42.5)
        self.assertEqual(obj.service_type, "Ordinary")
        self.assertIsNone(obj.client_session_id)

    def test_telemetry_input_with_client_session_id(self):
        payload = {
            "bus_number": "KA-22-F-1892",
            "latitude": 15.8573,
            "longitude": 74.5065,
            "speed": 40.0,
            "client_session_id": "cbt-dev-uuid-12345",
        }
        obj = TelemetryInput(**payload)
        self.assertEqual(obj.client_session_id, "cbt-dev-uuid-12345")

    def test_telemetry_input_invalid_latitude(self):
        with self.assertRaises(ValidationError):
            TelemetryInput(
                bus_number="KA-22-F-1892",
                latitude=95.0,  # Invalid: > 90
                longitude=74.5065,
                speed=20.0,
            )

    def test_telemetry_input_invalid_speed(self):
        with self.assertRaises(ValidationError):
            TelemetryInput(
                bus_number="KA-22-F-1892",
                latitude=15.8573,
                longitude=74.5065,
                speed=-5.0,  # Invalid: < 0
            )

    def test_bus_search_response_pure_schedule_no_gps(self):
        """Pure schedule with no live telemetry: current_lat/current_lng must be None and is_stale True."""
        resp = BusSearchResponse(
            bus_number="KA-22-F-1890",
            depot="Belagavi-1",
            schedule_no="SCH-42",
            service_type="Vegadhoot",
            departure_time="2026-09-14T08:30:00Z",
            assigned_platform="Bay 4 — Chikkodi Line",
            source_station_name="BELAGAVI CBT",
            destination_station_name="CHIKKODI",
            route_via="Sankeshwar",
            trip_status="scheduled",
            status_label="At Bay",
            has_left_platform=False,
            is_stale=True,
            is_fallback=False,
            current_lat=None,
            current_lng=None,
            last_seen_at=None,
        )
        self.assertIsNone(resp.current_lat)
        self.assertIsNone(resp.current_lng)
        self.assertTrue(resp.is_stale)
        self.assertFalse(resp.has_left_platform)
        self.assertEqual(resp.status_label, "At Bay")

    def test_bus_search_response_with_live_gps(self):
        resp = BusSearchResponse(
            bus_number="KA-22-F-1892",
            depot="Belagavi-1",
            schedule_no="SCH-10",
            service_type="Airavat Club Class",
            departure_time="2026-09-14T07:15:00Z",
            assigned_platform="Bay 1 — Express Departure",
            source_station_name="BELAGAVI CBT",
            destination_station_name="VIJAYAPURA",
            route_via="Gokak Falls -> Mudhol",
            trip_status="in_transit",
            status_label="En Route (68.5 km/h)",
            has_left_platform=True,
            is_stale=False,
            is_fallback=False,
            current_lat=16.1750,
            current_lng=74.8450,
            last_seen_at="2026-09-14T07:45:00Z",
            speed=68.5,
        )
        self.assertEqual(resp.current_lat, 16.1750)
        self.assertEqual(resp.current_lng, 74.8450)
        self.assertFalse(resp.is_stale)
        self.assertTrue(resp.has_left_platform)

    def test_station_response_geojson_format(self):
        station = StationResponse(
            id="stn-1",
            name="BELAGAVI CBT",
            platform_name="Bay 1",
            latitude=15.8573,
            longitude=74.5065,
            geofence_radius_meters=65.0,
            geocode_source="manual_override",
            location={
                "type": "Point",
                "coordinates": [74.5065, 15.8573],
            },
        )
        self.assertEqual(station.location["type"], "Point")
        self.assertEqual(station.location["coordinates"], [74.5065, 15.8573])


if __name__ == "__main__":
    unittest.main()

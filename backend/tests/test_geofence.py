"""
Unit tests for platform geofence calculations and departure determination.
"""

import unittest
from backend.geofence import haversine_distance_meters, evaluate_platform_departure


class TestGeofence(unittest.TestCase):
    def test_haversine_distance_zero(self):
        # Same coordinates -> 0 distance
        dist = haversine_distance_meters(15.8573, 74.5065, 15.8573, 74.5065)
        self.assertAlmostEqual(dist, 0.0, places=2)

    def test_haversine_distance_known_points(self):
        # Belagavi CBT (15.8573, 74.5065) to nearby junction (~150m away)
        dist = haversine_distance_meters(15.8573, 74.5065, 15.8584, 74.5072)
        self.assertTrue(120 < dist < 170)

    def test_geofence_at_bay_inside_radius(self):
        """Bus inside platform radius (e.g. 25m < 60m) regardless of speed is not departed."""
        # 25m distance from station
        has_left, dist = evaluate_platform_departure(
            db=None,
            latitude=15.8574,
            longitude=74.5066,
            speed=0.0,
            station_lat=15.8573,
            station_lng=74.5065,
            geofence_radius_meters=60.0,
            departure_speed_threshold_kmh=5.0,
        )
        self.assertFalse(has_left)
        self.assertIsNotNone(dist)
        self.assertLess(dist, 60.0)

    def test_geofence_outside_radius_low_speed_drift(self):
        """Bus outside radius (e.g. 150m) but stationary / crawling (speed <= 5 km/h) -> not departed."""
        has_left, dist = evaluate_platform_departure(
            db=None,
            latitude=15.8584,
            longitude=74.5072,
            speed=3.5,  # Crawling / GPS drift <= 5 km/h
            station_lat=15.8573,
            station_lng=74.5065,
            geofence_radius_meters=60.0,
            departure_speed_threshold_kmh=5.0,
        )
        self.assertFalse(has_left)
        self.assertGreater(dist, 60.0)

    def test_geofence_outside_radius_high_speed_departed(self):
        """Bus outside radius (150m) and speed > 5 km/h (e.g. 25 km/h) -> has_left_platform is True."""
        has_left, dist = evaluate_platform_departure(
            db=None,
            latitude=15.8584,
            longitude=74.5072,
            speed=25.0,  # Speed > 5 km/h
            station_lat=15.8573,
            station_lng=74.5065,
            geofence_radius_meters=60.0,
            departure_speed_threshold_kmh=5.0,
        )
        self.assertTrue(has_left)
        self.assertGreater(dist, 60.0)


if __name__ == "__main__":
    unittest.main()

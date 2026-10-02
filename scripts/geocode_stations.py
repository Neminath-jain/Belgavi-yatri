#!/usr/bin/env python3
"""
===============================================================================
KSRTC Belagavi Division — Automated Station Geocoding & Pipeline Tool
===============================================================================
Author: Senior Data Engineer
Purpose:
  1. Identifies stations with missing/placeholder locations in Supabase PostgreSQL/PostGIS.
  2. Resolves coordinates via manual CSV overrides first.
  3. Geocodes remaining stops via OpenStreetMap Nominatim (geopy) with district-biased queries.
  4. Applies strict 1 req/sec rate limits, User-Agent, and exponential backoff.
  5. Rejects broad administrative centroid guesses, filing low-confidence records into
     `unresolved_stations` for manual review.
  6. Idempotent and fully re-runnable.
===============================================================================
"""

import os
import sys
import time
import csv
import re
import argparse
import logging
from typing import Dict, Tuple, Optional, Any

import psycopg2
from psycopg2.extras import RealDictCursor
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable, GeocoderRateLimited

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("geocode_stations")


# Place types considered specific enough for transit stops
SPECIFIC_PLACE_TYPES = {
    "bus_stop",
    "station",
    "stop",
    "halt",
    "village",
    "hamlet",
    "town",
    "suburb",
    "neighbourhood",
    "locality",
    "residential",
    "road",
    "commercial",
    "isolated_dwelling",
}

# Broad geographical types considered "low-confidence" guesses
BROAD_REGION_TYPES = {
    "administrative",
    "state_district",
    "state",
    "country",
    "region",
    "county",
}


def clean_station_name_for_query(raw_name: str) -> str:
    """
    Clean transit operational annotations like '(RD)', '(KPL)', 'BAY 1',
    numbers, and extra whitespace to maximize geocoding hit rate.
    """
    cleaned = raw_name.strip()
    # Remove parenthesized codes: e.g. "Shahu Ngr (RD)" -> "Shahu Ngr"
    cleaned = re.sub(r"\(.*?\)", "", cleaned).strip()
    # Remove trailing suffixes like "-SDNR", "-VTM", " X"
    cleaned = re.sub(r"[-/](SDNR|VTM|SCH|KPL)\b", "", cleaned, flags=re.IGNORECASE).strip()
    # Expand common transit abbreviations
    cleaned = re.sub(r"\bNgr\b", "Nagar", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bCol\b", "Colony", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bHosp\b", "Hospital", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def load_manual_overrides(csv_path: str) -> Dict[str, Tuple[float, float]]:
    """
    Load manual coordinate overrides from CSV (station_name,latitude,longitude).
    Key is normalized (lowercased, stripped).
    """
    overrides: Dict[str, Tuple[float, float]] = {}
    if not os.path.exists(csv_path):
        logger.warning("Manual override CSV not found at: %s. Proceeding without overrides.", csv_path)
        return overrides

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                name = row["station_name"].strip().lower()
                lat = float(row["latitude"].strip())
                lng = float(row["longitude"].strip())
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    overrides[name] = (lat, lng)
            except (ValueError, KeyError) as e:
                logger.warning("Skipping invalid override row %s: %s", row, e)

    logger.info("Loaded %d manual station coordinate overrides from %s", len(overrides), csv_path)
    return overrides


def ensure_database_schema(conn) -> None:
    """
    Ensure the `geocode_source` column on `stations` and the
    `unresolved_stations` quarantine table exist.
    """
    with conn.cursor() as cur:
        # Add geocode_source tracking column if absent
        cur.execute("""
            ALTER TABLE public.stations 
            ADD COLUMN IF NOT EXISTS geocode_source TEXT;
        """)

        # Quarantine table for low-confidence or missing matches
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.unresolved_stations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                station_id UUID REFERENCES public.stations(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                attempted_query TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_unresolved_station UNIQUE (station_id)
            );
        """)
    conn.commit()


def query_unresolved_stations(conn):
    """
    Fetch stations that still hold placeholder coordinates (NULL or sentinel 0,0).
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name
            FROM public.stations
            WHERE location IS NULL 
               OR (ST_X(location) = 0 AND ST_Y(location) = 0)
            ORDER BY name ASC;
        """)
        return cur.fetchall()


def update_station_location(conn, station_id: str, lat: float, lng: float, source: str) -> None:
    """
    Update the PostGIS Point (SRID 4326) and remove from unresolved table if present.
    Note: PostGIS ST_MakePoint takes (longitude, latitude).
    """
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE public.stations
            SET location = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                geocode_source = %s
            WHERE id = %s;
        """, (lng, lat, source, station_id))

        # Clear from unresolved table if it previously existed
        cur.execute("""
            DELETE FROM public.unresolved_stations
            WHERE station_id = %s;
        """, (station_id,))
    conn.commit()


def record_unresolved_station(conn, station_id: str, name: str, query: str, reason: str) -> None:
    """
    Insert or update low-confidence / failed match into unresolved_stations table.
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO public.unresolved_stations (station_id, name, attempted_query, reason)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (station_id) DO UPDATE
            SET attempted_query = EXCLUDED.attempted_query,
                reason = EXCLUDED.reason,
                created_at = now();
        """, (station_id, name, query, reason))
    conn.commit()


def geocode_with_backoff(
    geolocator: Nominatim,
    query: str,
    max_retries: int = 3
) -> Optional[Any]:
    """
    Call Nominatim geocoder with exponential backoff on timeouts/rate limits.
    """
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(1.1)  # Strict compliance with Nominatim 1 req/sec policy
            location = geolocator.geocode(query, exactly_one=True, addressdetails=True)
            return location
        except (GeocoderTimedOut, GeocoderUnavailable) as e:
            backoff = 2 ** attempt
            logger.warning("Geocoder timeout/unavailable for '%s' (attempt %d/%d). Retrying in %ds... Error: %s",
                           query, attempt, max_retries, backoff, e)
            time.sleep(backoff)
        except GeocoderRateLimited:
            backoff = 5 * attempt
            logger.warning("Rate limit encountered for '%s'. Backing off for %ds...", query, backoff)
            time.sleep(backoff)
        except Exception as e:
            logger.error("Unexpected geocoding error for '%s': %s", query, e)
            return None
    return None


def run_geocoding_pipeline(
    database_url: str,
    overrides_csv: str,
    user_agent: str = "ksrtc_belagavi_transit_geocoder/1.0 (contact@ksrtc-belagavi.in)",
) -> None:
    """
    Main idempotent execution pipeline.
    """
    start_time = time.time()
    logger.info("Connecting to Supabase PostgreSQL database...")

    try:
        conn = psycopg2.connect(database_url)
    except Exception as e:
        logger.error("Database connection failed: %s", e)
        sys.exit(1)

    try:
        ensure_database_schema(conn)
        overrides = load_manual_overrides(overrides_csv)

        unresolved_rows = query_unresolved_stations(conn)
        total_pending = len(unresolved_rows)
        logger.info("Found %d stations with missing/placeholder locations.", total_pending)

        if total_pending == 0:
            logger.info("All stations in database already have valid geographic coordinates. Nothing to do.")
            return

        geolocator = Nominatim(user_agent=user_agent, timeout=8)

        count_manual = 0
        count_auto = 0
        count_unresolved = 0

        for idx, row in enumerate(unresolved_rows, start=1):
            stn_id = row["id"]
            raw_name = row["name"].strip()
            norm_key = raw_name.lower()

            logger.info("[%d/%d] Processing station: '%s'", idx, total_pending, raw_name)

            # --- STEP 1: Check Manual Overrides CSV ---
            if norm_key in overrides:
                lat, lng = overrides[norm_key]
                update_station_location(conn, stn_id, lat, lng, "manual_override")
                logger.info("  -> RESOLVED via manual override: (%f, %f)", lat, lng)
                count_manual += 1
                continue

            # --- STEP 2: Construct Biased Geocoding Query ---
            clean_name = clean_station_name_for_query(raw_name)
            query = f"{clean_name}, Belagavi district, Karnataka, India"

            # Execute Geocoding
            loc_result = geocode_with_backoff(geolocator, query)

            # Secondary fallback without district constraint if no hit
            if not loc_result:
                secondary_query = f"{clean_name}, Karnataka, India"
                logger.info("  -> No match for primary query. Trying secondary: '%s'", secondary_query)
                loc_result = geocode_with_backoff(geolocator, secondary_query)
                if loc_result:
                    query = secondary_query

            # --- STEP 3: Confidence & Match Quality Verification ---
            if not loc_result:
                reason = "No match returned by Nominatim geocoder"
                record_unresolved_station(conn, stn_id, raw_name, query, reason)
                logger.warning("  -> UNRESOLVED: %s", reason)
                count_unresolved += 1
                continue

            raw_props = loc_result.raw or {}
            place_type = raw_props.get("type", "unknown")
            place_class = raw_props.get("class", "unknown")
            display_name = loc_result.address or ""

            # Check if match is merely a broad district or state polygon (low confidence)
            is_broad_region = (
                place_type in BROAD_REGION_TYPES
                or place_class in ("boundary", "place")
                and clean_name.lower() not in raw_props.get("name", "").lower()
            )

            # Check bounding box size (if bounding box covers > 0.5 degrees, it's a broad area, not a bus stop)
            bbox = raw_props.get("boundingbox", [])
            is_large_bbox = False
            if len(bbox) == 4:
                try:
                    lat_span = abs(float(bbox[1]) - float(bbox[0]))
                    lon_span = abs(float(bbox[3]) - float(bbox[2]))
                    if lat_span > 0.35 or lon_span > 0.35:
                        is_large_bbox = True
                except ValueError:
                    pass

            if is_broad_region or is_large_bbox:
                reason = f"Low confidence broad area match: type={place_type}, class={place_class} ('{display_name}')"
                record_unresolved_station(conn, stn_id, raw_name, query, reason)
                logger.warning("  -> REJECTED broad match: %s", reason)
                count_unresolved += 1
                continue

            # --- STEP 4: High Confidence Match: Update Station ---
            lat = loc_result.latitude
            lng = loc_result.longitude
            source_tag = f"nominatim:{place_class}:{place_type}"

            update_station_location(conn, stn_id, lat, lng, source_tag)
            logger.info("  -> RESOLVED via %s: (%f, %f) — %s", source_tag, lat, lng, display_name[:65])
            count_auto += 1

        # --- STEP 5: Final Execution Summary ---
        elapsed = time.time() - start_time
        print("\n" + "=" * 70)
        print("  KSRTC BELAGAVI STATION GEOCODING PIPELINE SUMMARY")
        print("=" * 70)
        print(f"  Total Stations Processed:        {total_pending}")
        print(f"  Resolved via Manual Overrides:   {count_manual}")
        print(f"  Resolved Automatically (OSM):    {count_auto}")
        print(f"  Unresolved (Logged for Review):  {count_unresolved}")
        print(f"  Total Execution Time:            {elapsed:.2f} seconds")
        print("=" * 70)
        # Invalidate Redis station cache so read endpoints immediately pick up new locations
        if count_manual > 0 or count_auto > 0:
            try:
                sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
                from backend.redis_service import invalidate_stations_cache
                deleted = invalidate_stations_cache()
                if deleted:
                    print("  Redis Cache: Successfully invalidated 'cache:stations:all'.")
            except Exception as cache_err:
                logger.debug("Redis station cache invalidation skipped or unavailable: %s", cache_err)

        if count_unresolved > 0:
            print("  Note: Check the 'public.unresolved_stations' database table or add")
            print(f"  missing stops to '{overrides_csv}' and rerun this script.")
        print("=" * 70 + "\n")

    finally:
        conn.close()
        logger.info("Database connection closed.")


def main():
    parser = argparse.ArgumentParser(
        description="Geocode KSRTC Belagavi stations with PostGIS, Nominatim, and manual overrides."
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/postgres",
        ),
        help="PostgreSQL connection URI (defaults to DATABASE_URL env var).",
    )
    parser.add_argument(
        "--overrides",
        default=os.path.join(
            os.path.dirname(__file__), "..", "data", "station_overrides.csv"
        ),
        help="Path to manual override CSV file.",
    )
    parser.add_argument(
        "--user-agent",
        default="ksrtc_belagavi_transit_geocoder/1.0 (contact@ksrtc-belagavi.in)",
        help="Custom User-Agent for OpenStreetMap Nominatim compliance.",
    )

    args = parser.parse_args()
    run_geocoding_pipeline(
        database_url=args.db_url,
        overrides_csv=args.overrides,
        user_agent=args.user_agent,
    )


if __name__ == "__main__":
    main()

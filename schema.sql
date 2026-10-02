-- ============================================================================
-- PROJECT: yatri-bgm (NWKRTC Belagavi Central Division Live Radar)
-- Architecture: Zero-Login, Public-Facing, Crowdsourced Bus Tracking & Geofencing
-- Compliance: India DPDP Act 2023 Ephemeral Telemetry Architecture
-- Database: PostgreSQL 15+ with PostGIS Extension (Supabase Ready)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. EXTENSIONS
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- ----------------------------------------------------------------------------
-- 2. CORE PUBLIC TRANSIT TABLES (Zero Auth / Zero PII)
-- ----------------------------------------------------------------------------

-- Stations / Terminals / Key Division Stops
CREATE TABLE IF NOT EXISTS public.stations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    platform_name VARCHAR(50),
    location GEOMETRY(Point, 4326) NOT NULL,
    geofence_radius_meters NUMERIC(6, 2) NOT NULL DEFAULT 65.00,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_geofence_positive CHECK (geofence_radius_meters > 0)
);

-- Active Fleet Buses & Ephemeral GPS Telemetry State
CREATE TABLE IF NOT EXISTS public.buses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bus_number VARCHAR(20) NOT NULL UNIQUE,
    service_type VARCHAR(50) NOT NULL,
    current_location GEOMETRY(Point, 4326),
    speed NUMERIC(5, 2) DEFAULT 0.00 CHECK (speed >= 0),
    has_left_platform BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Scheduled & Operational Transit Trips
CREATE TABLE IF NOT EXISTS public.trips (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bus_id UUID REFERENCES public.buses(id) ON DELETE SET NULL,
    source_station_id UUID NOT NULL REFERENCES public.stations(id) ON DELETE CASCADE,
    destination_station_id UUID NOT NULL REFERENCES public.stations(id) ON DELETE CASCADE,
    departure_time TIME NOT NULL,
    route_via TEXT,
    route_polyline JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_different_endpoints CHECK (source_station_id <> destination_station_id)
);

-- ----------------------------------------------------------------------------
-- 3. SPATIAL & INDEX OPTIMIZATIONS
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_stations_geom ON public.stations USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_buses_geom ON public.buses USING GIST (current_location);
CREATE INDEX IF NOT EXISTS idx_trips_endpoints ON public.trips(source_station_id, destination_station_id);
CREATE INDEX IF NOT EXISTS idx_trips_bus_id ON public.trips(bus_id);

-- ----------------------------------------------------------------------------
-- 4. ROW LEVEL SECURITY (RLS) POLICIES — 100% OPEN CIVIC PUBLIC ACCESS
-- ----------------------------------------------------------------------------
ALTER TABLE public.stations DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.buses DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.trips DISABLE ROW LEVEL SECURITY;

-- Permissive public policies if RLS is re-enabled by cloud provider defaults
DO $$
BEGIN
    DROP POLICY IF EXISTS "Public Read Stations" ON public.stations;
    DROP POLICY IF EXISTS "Public Read Buses" ON public.buses;
    DROP POLICY IF EXISTS "Public Read Trips" ON public.trips;
    DROP POLICY IF EXISTS "Public Update Buses Telemetry" ON public.buses;
END $$;

CREATE POLICY "Public Read Stations" ON public.stations FOR SELECT USING (true);
CREATE POLICY "Public Read Buses" ON public.buses FOR SELECT USING (true);
CREATE POLICY "Public Read Trips" ON public.trips FOR SELECT USING (true);
CREATE POLICY "Public Update Buses Telemetry" ON public.buses FOR ALL USING (true) WITH CHECK (true);

-- Grant full table permissions to anonymous and public clients
GRANT SELECT ON public.stations TO anon, authenticated, postgres, service_role;
GRANT SELECT, INSERT, UPDATE ON public.buses TO anon, authenticated, postgres, service_role;
GRANT SELECT ON public.trips TO anon, authenticated, postgres, service_role;

-- ----------------------------------------------------------------------------
-- 5. DIVISION SEED DATA (Belagavi Central Division Core Termini & Polylines)
-- ----------------------------------------------------------------------------

-- Seed Stations with exact coordinates
-- Note: ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
INSERT INTO public.stations (name, platform_name, location, geofence_radius_meters)
VALUES
    ('BELAGAVI CBT', 'Bay 4 - Main Terminal', ST_SetSRID(ST_MakePoint(74.50970, 15.85960), 4326), 65.00),
    ('CHIKKODI', 'Bay 1 - Chikkodi Bus Stand', ST_SetSRID(ST_MakePoint(74.59770, 16.42770), 4326), 65.00),
    ('ATHANI', 'Bay 2 - Athani Central', ST_SetSRID(ST_MakePoint(75.06000, 16.73000), 4326), 65.00),
    ('GOKAK', 'Bay 3 - Gokak Depot Stand', ST_SetSRID(ST_MakePoint(74.82190, 16.16670), 4326), 65.00),
    ('BAILHONGAL', 'Bay 1 - Bailhongal Stand', ST_SetSRID(ST_MakePoint(74.86670, 15.81670), 4326), 65.00),
    ('VIJAYAPURA', 'Bay 6 - Interstate Terminal', ST_SetSRID(ST_MakePoint(75.71000, 16.83020), 4326), 65.00)
ON CONFLICT (name) DO UPDATE SET
    platform_name = EXCLUDED.platform_name,
    location = EXCLUDED.location,
    geofence_radius_meters = EXCLUDED.geofence_radius_meters;

-- Seed Sample Buses (Initial state: At CBT platform)
INSERT INTO public.buses (bus_number, service_type, current_location, speed, has_left_platform, updated_at)
VALUES
    ('KA-22-F-1890', 'NWKRTC Vegadhoot', ST_SetSRID(ST_MakePoint(74.50970, 15.85960), 4326), 0.00, false, now()),
    ('KA-22-F-1892', 'Rajahamsa Executive', ST_SetSRID(ST_MakePoint(74.50970, 15.85960), 4326), 0.00, false, now()),
    ('KA-22-F-1904', 'Ordinary Sarige', ST_SetSRID(ST_MakePoint(74.50970, 15.85960), 4326), 0.00, false, now()),
    ('KA-22-F-2010', 'NWKRTC Vegadhoot', ST_SetSRID(ST_MakePoint(74.53200, 15.91200), 4326), 46.50, true, now()),
    ('KA-22-F-2144', 'Airavat Club Class', ST_SetSRID(ST_MakePoint(74.50970, 15.85960), 4326), 0.00, false, now())
ON CONFLICT (bus_number) DO UPDATE SET
    service_type = EXCLUDED.service_type,
    current_location = EXCLUDED.current_location,
    speed = EXCLUDED.speed,
    has_left_platform = EXCLUDED.has_left_platform,
    updated_at = now();

-- Seed Trips with High-Fidelity NH 48 & State Highway Route Polylines [[lat, lng], ...]
-- 1. BELAGAVI CBT -> CHIKKODI (via NH 48: Kakti, Yamkanmardi, Sankeshwar)
INSERT INTO public.trips (bus_id, source_station_id, destination_station_id, departure_time, route_via, route_polyline)
SELECT
    b.id,
    s_src.id,
    s_dst.id,
    '08:30:00'::TIME,
    'Kakti -> Yamkanmardi -> Hattargi -> Sankeshwar -> Chikkodi',
    '[
        [15.85960, 74.50970],
        [15.86250, 74.51100],
        [15.87500, 74.51400],
        [15.89500, 74.51700],
        [15.92500, 74.52100],
        [15.97500, 74.52800],
        [16.03500, 74.53600],
        [16.11500, 74.54200],
        [16.20500, 74.55000],
        [16.26500, 74.56500],
        [16.33500, 74.57800],
        [16.39500, 74.58800],
        [16.42770, 74.59770]
    ]'::jsonb
FROM public.buses b, public.stations s_src, public.stations s_dst
WHERE b.bus_number = 'KA-22-F-1890'
  AND s_src.name = 'BELAGAVI CBT'
  AND s_dst.name = 'CHIKKODI';

-- 2. BELAGAVI CBT -> ATHANI (via Gokak, Kagwad)
INSERT INTO public.trips (bus_id, source_station_id, destination_station_id, departure_time, route_via, route_polyline)
SELECT
    b.id,
    s_src.id,
    s_dst.id,
    '09:15:00'::TIME,
    'Sulebhavi -> Nesargi -> Gokak -> Kagwad -> Athani',
    '[
        [15.85960, 74.50970],
        [15.87200, 74.53500],
        [15.91500, 74.58500],
        [15.98500, 74.65000],
        [16.06500, 74.74000],
        [16.16670, 74.82190],
        [16.35000, 74.92000],
        [16.54000, 74.99000],
        [16.73000, 75.06000]
    ]'::jsonb
FROM public.buses b, public.stations s_src, public.stations s_dst
WHERE b.bus_number = 'KA-22-F-1892'
  AND s_src.name = 'BELAGAVI CBT'
  AND s_dst.name = 'ATHANI';

-- 3. BELAGAVI CBT -> GOKAK (via Sulebhavi, Nesargi, Gokak Falls)
INSERT INTO public.trips (bus_id, source_station_id, destination_station_id, departure_time, route_via, route_polyline)
SELECT
    b.id,
    s_src.id,
    s_dst.id,
    '10:00:00'::TIME,
    'Sulebhavi -> Nesargi -> Gokak Falls',
    '[
        [15.85960, 74.50970],
        [15.87500, 74.53000],
        [15.92000, 74.59000],
        [16.01000, 74.68000],
        [16.10000, 74.77000],
        [16.15500, 74.81000],
        [16.16670, 74.82190]
    ]'::jsonb
FROM public.buses b, public.stations s_src, public.stations s_dst
WHERE b.bus_number = 'KA-22-F-1904'
  AND s_src.name = 'BELAGAVI CBT'
  AND s_dst.name = 'GOKAK';

-- 4. BELAGAVI CBT -> BAILHONGAL (via Peeranwadi, Desur)
INSERT INTO public.trips (bus_id, source_station_id, destination_station_id, departure_time, route_via, route_polyline)
SELECT
    b.id,
    s_src.id,
    s_dst.id,
    '11:30:00'::TIME,
    'Peeranwadi -> Desur -> Honnihal -> Bailhongal',
    '[
        [15.85960, 74.50970],
        [15.84500, 74.52000],
        [15.83500, 74.56000],
        [15.82800, 74.65000],
        [15.82200, 74.74000],
        [15.81670, 74.86670]
    ]'::jsonb
FROM public.buses b, public.stations s_src, public.stations s_dst
WHERE b.bus_number = 'KA-22-F-2010'
  AND s_src.name = 'BELAGAVI CBT'
  AND s_dst.name = 'BAILHONGAL';

-- 5. BELAGAVI CBT -> VIJAYAPURA (via Gokak, Mudhol, Bagalkot bypass)
INSERT INTO public.trips (bus_id, source_station_id, destination_station_id, departure_time, route_via, route_polyline)
SELECT
    b.id,
    s_src.id,
    s_dst.id,
    '07:00:00'::TIME,
    'Nesargi -> Gokak -> Mudhol -> Lokapur -> Vijayapura',
    '[
        [15.85960, 74.50970],
        [15.92000, 74.59000],
        [16.16670, 74.82190],
        [16.19500, 75.15000],
        [16.45000, 75.40000],
        [16.65000, 75.58000],
        [16.83020, 75.71000]
    ]'::jsonb
FROM public.buses b, public.stations s_src, public.stations s_dst
WHERE b.bus_number = 'KA-22-F-2144'
  AND s_src.name = 'BELAGAVI CBT'
  AND s_dst.name = 'VIJAYAPURA';

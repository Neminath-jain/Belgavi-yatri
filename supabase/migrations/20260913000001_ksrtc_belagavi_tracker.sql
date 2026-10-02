-- ============================================================================
-- KSRTC Belagavi Division Bus Tracking System — PostGIS Database Architecture
-- Compliant with Digital Personal Data Protection (DPDP) Act 2023 / Rules 2025
-- Dynamic Telemetry Ingestion & Division-Wide Search Engine
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. EXTENSIONS
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "postgis";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ----------------------------------------------------------------------------
-- 2. CORE TRANSIT TELEMETRY TABLES (Non-Personal Public Data)
-- ----------------------------------------------------------------------------

-- Stations / Depots / Termini in Belagavi Division
CREATE TABLE IF NOT EXISTS public.stations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    platform_name TEXT,
    location GEOMETRY(Point, 4326) NOT NULL,
    geofence_radius_meters NUMERIC(6, 2) NOT NULL DEFAULT 60.00,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_geofence_positive CHECK (geofence_radius_meters > 0)
);

-- Real-time Bus Telemetry & Fleet State (Dynamically populated & updated)
CREATE TABLE IF NOT EXISTS public.buses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bus_number TEXT NOT NULL UNIQUE,
    service_type TEXT NOT NULL CHECK (service_type IN ('Vegadhoot', 'Rajahamsa', 'Ordinary', 'Airavat Club Class')),
    current_location GEOMETRY(Point, 4326),
    speed NUMERIC(5, 2) DEFAULT 0.00 CHECK (speed >= 0),
    has_left_platform BOOLEAN NOT NULL DEFAULT false,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Scheduled & Active Trips
CREATE TABLE IF NOT EXISTS public.trips (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bus_id UUID REFERENCES public.buses(id) ON DELETE SET NULL,
    source_station_id UUID NOT NULL REFERENCES public.stations(id) ON DELETE RESTRICT,
    destination_station_id UUID NOT NULL REFERENCES public.stations(id) ON DELETE RESTRICT,
    departure_time TIMESTAMPTZ NOT NULL,
    route_via TEXT,
    route_polyline JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'in_transit', 'arrived', 'delayed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_different_stations CHECK (source_station_id <> destination_station_id)
);

-- ----------------------------------------------------------------------------
-- 3. RIDER-FACING TABLES (DPDP Act 2023 / Rules 2025 Guarded)
-- NOTE: Populated strictly upon explicit, affirmative opt-in by Data Principal.
-- PII fields (phone, email) are stored as encrypted BYTEA.
-- ----------------------------------------------------------------------------

-- Registered Users opting into personal features
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number_encrypted BYTEA,
    email_encrypted BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    account_status TEXT NOT NULL DEFAULT 'active' CHECK (account_status IN ('active', 'suspended', 'erased'))
);

-- Saved Route Preferences & Alert Subscriptions
CREATE TABLE IF NOT EXISTS public.saved_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    source_station_id UUID NOT NULL REFERENCES public.stations(id) ON DELETE CASCADE,
    destination_station_id UUID NOT NULL REFERENCES public.stations(id) ON DELETE CASCADE,
    alert_enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_route UNIQUE (user_id, source_station_id, destination_station_id)
);

-- Explicit DPDP Notice & Consent Audit Log (Section 6 DPDP Act 2023)
CREATE TABLE IF NOT EXISTS public.consent_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('sms_alerts', 'saved_routes', 'push_notifications', 'analytics')),
    consent_given_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consent_withdrawn_at TIMESTAMPTZ,
    notice_version TEXT NOT NULL DEFAULT 'DPDP-2025-v1.0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Data Principal Rights Processing Log (Section 11-14: Access, Correction, Erasure)
CREATE TABLE IF NOT EXISTS public.data_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    request_type TEXT NOT NULL CHECK (request_type IN ('access', 'correction', 'erasure')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'rejected')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- ----------------------------------------------------------------------------
-- 4. SPATIAL & PERFORMANCE INDEXES
-- ----------------------------------------------------------------------------

-- PostGIS GiST Indexes
CREATE INDEX IF NOT EXISTS idx_stations_location_gist ON public.stations USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_buses_location_gist ON public.buses USING GIST (current_location);

-- B-Tree foreign key & lookups
CREATE INDEX IF NOT EXISTS idx_stations_name ON public.stations(name);
CREATE INDEX IF NOT EXISTS idx_buses_last_seen ON public.buses(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_trips_bus_id ON public.trips(bus_id);
CREATE INDEX IF NOT EXISTS idx_trips_stations ON public.trips(source_station_id, destination_station_id);
CREATE INDEX IF NOT EXISTS idx_trips_departure ON public.trips(departure_time);
CREATE INDEX IF NOT EXISTS idx_saved_routes_user ON public.saved_routes(user_id);
CREATE INDEX IF NOT EXISTS idx_consent_records_user ON public.consent_records(user_id);
CREATE INDEX IF NOT EXISTS idx_data_requests_user ON public.data_requests(user_id);

-- ----------------------------------------------------------------------------
-- 5. SPATIAL DATABASE FUNCTIONS & TELEMETRY ENGINE
-- ----------------------------------------------------------------------------

-- Function: Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_buses_updated_at ON public.buses;
CREATE TRIGGER trg_buses_updated_at
BEFORE UPDATE ON public.buses
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

/**
 * check_platform_departure
 * Determines if a bus has crossed outside the geofence perimeter of a station platform.
 */
CREATE OR REPLACE FUNCTION public.check_platform_departure(
    p_bus_id UUID,
    p_station_id UUID
)
RETURNS TABLE (
    has_departed BOOLEAN,
    distance_meters NUMERIC(8, 2),
    current_speed NUMERIC(5, 2),
    station_name TEXT,
    platform_name TEXT
) AS $$
DECLARE
    v_bus_loc GEOMETRY(Point, 4326);
    v_bus_speed NUMERIC(5, 2);
    v_station_loc GEOMETRY(Point, 4326);
    v_radius NUMERIC(6, 2);
    v_dist NUMERIC(8, 2);
    v_sname TEXT;
    v_pname TEXT;
    v_departed BOOLEAN;
BEGIN
    SELECT current_location, speed 
    INTO v_bus_loc, v_bus_speed
    FROM public.buses 
    WHERE id = p_bus_id;

    IF NOT FOUND OR v_bus_loc IS NULL THEN
        RAISE EXCEPTION 'Bus ID % not found or location telemetry unavailable', p_bus_id;
    END IF;

    SELECT location, geofence_radius_meters, name, platform_name
    INTO v_station_loc, v_radius, v_sname, v_pname
    FROM public.stations 
    WHERE id = p_station_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Station ID % not found', p_station_id;
    END IF;

    v_dist := ST_Distance(v_bus_loc::geography, v_station_loc::geography);
    v_departed := NOT ST_DWithin(v_bus_loc::geography, v_station_loc::geography, v_radius);

    IF v_departed THEN
        UPDATE public.buses 
        SET has_left_platform = true 
        WHERE id = p_bus_id;
    END IF;

    RETURN QUERY SELECT 
        v_departed,
        ROUND(v_dist, 2),
        v_bus_speed,
        v_sname,
        v_pname;
END;
$$ LANGUAGE plpgsql;

/**
 * upsert_bus_telemetry
 * Dynamic ingestion engine: auto-registers buses on first ping, updates coordinates,
 * calculates platform departure geofence, and refreshes last_seen_at.
 */
CREATE OR REPLACE FUNCTION public.upsert_bus_telemetry(
    p_bus_number TEXT,
    p_lat DOUBLE PRECISION,
    p_lng DOUBLE PRECISION,
    p_speed NUMERIC DEFAULT 0.00,
    p_service_type TEXT DEFAULT 'Ordinary'
)
RETURNS TABLE (
    bus_id UUID,
    bus_number TEXT,
    service_type TEXT,
    current_lat DOUBLE PRECISION,
    current_lng DOUBLE PRECISION,
    speed NUMERIC,
    has_left_platform BOOLEAN,
    last_seen_at TIMESTAMPTZ,
    is_new_registration BOOLEAN
) AS $$
DECLARE
    v_bus_id UUID;
    v_is_new BOOLEAN := false;
    v_current_loc GEOMETRY(Point, 4326);
    v_has_left BOOLEAN;
    v_trip_source_station_id UUID;
    v_source_station_loc GEOMETRY(Point, 4326);
    v_geofence_radius NUMERIC(6, 2);
BEGIN
    v_current_loc := ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326);

    -- 1. Check if bus already exists
    SELECT id, has_left_platform 
    INTO v_bus_id, v_has_left
    FROM public.buses
    WHERE buses.bus_number = TRIM(UPPER(p_bus_number));

    IF v_bus_id IS NULL THEN
        -- Auto-register new bus dynamically
        v_is_new := true;
        INSERT INTO public.buses (
            bus_number,
            service_type,
            current_location,
            speed,
            has_left_platform,
            last_seen_at,
            updated_at
        )
        VALUES (
            TRIM(UPPER(p_bus_number)),
            COALESCE(p_service_type, 'Ordinary'),
            v_current_loc,
            COALESCE(p_speed, 0.00),
            false,
            now(),
            now()
        )
        RETURNING id, has_left_platform INTO v_bus_id, v_has_left;
    ELSE
        -- Evaluate geofence departure if bus has an active or scheduled departure today
        SELECT t.source_station_id INTO v_trip_source_station_id
        FROM public.trips t
        WHERE t.bus_id = v_bus_id AND t.status IN ('scheduled', 'in_transit')
        ORDER BY t.departure_time DESC
        LIMIT 1;

        IF v_trip_source_station_id IS NOT NULL THEN
            SELECT location, geofence_radius_meters 
            INTO v_source_station_loc, v_geofence_radius
            FROM public.stations 
            WHERE id = v_trip_source_station_id;

            IF v_source_station_loc IS NOT NULL THEN
                v_has_left := NOT ST_DWithin(v_current_loc::geography, v_source_station_loc::geography, v_geofence_radius);
            END IF;
        END IF;

        -- Update existing bus telemetry
        UPDATE public.buses
        SET
            current_location = v_current_loc,
            speed = COALESCE(p_speed, buses.speed),
            has_left_platform = COALESCE(v_has_left, buses.has_left_platform),
            last_seen_at = now(),
            updated_at = now()
        WHERE id = v_bus_id;
    END IF;

    RETURN QUERY
    SELECT 
        b.id,
        b.bus_number,
        b.service_type,
        ST_Y(b.current_location)::DOUBLE PRECISION,
        ST_X(b.current_location)::DOUBLE PRECISION,
        b.speed,
        b.has_left_platform,
        b.last_seen_at,
        v_is_new
    FROM public.buses b
    WHERE b.id = v_bus_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

/**
 * search_buses
 * Dynamic live search across stations, buses, and trips.
 * If exact route exists, returns matching trips with live telemetry.
 * If NO trip matches, returns all active division buses for today so riders never hit a dead end.
 */
CREATE OR REPLACE FUNCTION public.search_buses(
    source_name TEXT DEFAULT NULL,
    destination_name TEXT DEFAULT NULL
)
RETURNS TABLE (
    trip_id UUID,
    bus_id UUID,
    bus_number TEXT,
    service_type TEXT,
    source_station_name TEXT,
    destination_station_name TEXT,
    departure_time TIMESTAMPTZ,
    route_via TEXT,
    route_polyline JSONB,
    trip_status TEXT,
    speed NUMERIC,
    has_left_platform BOOLEAN,
    distance_from_source_meters NUMERIC(10, 2),
    current_lat DOUBLE PRECISION,
    current_lng DOUBLE PRECISION,
    last_seen_at TIMESTAMPTZ,
    is_stale BOOLEAN,
    is_fallback BOOLEAN
) AS $$
DECLARE
    v_clean_src TEXT := TRIM(COALESCE(source_name, ''));
    v_clean_dst TEXT := TRIM(COALESCE(destination_name, ''));
    v_exact_match_count INTEGER := 0;
BEGIN
    -- Check if exact/partial station pair match exists
    IF v_clean_src <> '' OR v_clean_dst <> '' THEN
        SELECT COUNT(*)
        INTO v_exact_match_count
        FROM public.trips t
        JOIN public.stations s_src ON t.source_station_id = s_src.id
        JOIN public.stations s_dst ON t.destination_station_id = s_dst.id
        WHERE (v_clean_src = '' OR s_src.name ILIKE '%' || v_clean_src || '%')
          AND (v_clean_dst = '' OR s_dst.name ILIKE '%' || v_clean_dst || '%');
    END IF;

    -- CASE A: Exact or partial station query matched active/scheduled trips
    IF v_exact_match_count > 0 THEN
        RETURN QUERY
        SELECT
            t.id AS trip_id,
            b.id AS bus_id,
            COALESCE(b.bus_number, 'UNASSIGNED') AS bus_number,
            COALESCE(b.service_type, 'Ordinary') AS service_type,
            s_src.name AS source_station_name,
            s_dst.name AS destination_station_name,
            t.departure_time,
            t.route_via,
            t.route_polyline,
            t.status AS trip_status,
            COALESCE(b.speed, 0.00) AS speed,
            COALESCE(b.has_left_platform, false) AS has_left_platform,
            CASE 
                WHEN b.current_location IS NOT NULL THEN
                    ROUND(ST_Distance(b.current_location::geography, s_src.location::geography)::numeric, 2)
                ELSE NULL
            END AS distance_from_source_meters,
            CASE WHEN b.current_location IS NOT NULL THEN ST_Y(b.current_location)::DOUBLE PRECISION ELSE NULL END AS current_lat,
            CASE WHEN b.current_location IS NOT NULL THEN ST_X(b.current_location)::DOUBLE PRECISION ELSE NULL END AS current_lng,
            b.last_seen_at,
            (b.last_seen_at IS NULL OR b.last_seen_at < (now() - INTERVAL '5 minutes')) AS is_stale,
            false AS is_fallback
        FROM public.trips t
        JOIN public.stations s_src ON t.source_station_id = s_src.id
        JOIN public.stations s_dst ON t.destination_station_id = s_dst.id
        LEFT JOIN public.buses b ON t.bus_id = b.id
        WHERE (v_clean_src = '' OR s_src.name ILIKE '%' || v_clean_src || '%')
          AND (v_clean_dst = '' OR s_dst.name ILIKE '%' || v_clean_dst || '%')
        ORDER BY t.departure_time ASC;

    -- CASE B: No match found (or blank search) — return all active/scheduled division trips for today
    ELSE
        RETURN QUERY
        SELECT
            t.id AS trip_id,
            b.id AS bus_id,
            COALESCE(b.bus_number, 'UNASSIGNED') AS bus_number,
            COALESCE(b.service_type, 'Ordinary') AS service_type,
            s_src.name AS source_station_name,
            s_dst.name AS destination_station_name,
            t.departure_time,
            t.route_via,
            t.route_polyline,
            t.status AS trip_status,
            COALESCE(b.speed, 0.00) AS speed,
            COALESCE(b.has_left_platform, false) AS has_left_platform,
            CASE 
                WHEN b.current_location IS NOT NULL THEN
                    ROUND(ST_Distance(b.current_location::geography, s_src.location::geography)::numeric, 2)
                ELSE NULL
            END AS distance_from_source_meters,
            CASE WHEN b.current_location IS NOT NULL THEN ST_Y(b.current_location)::DOUBLE PRECISION ELSE NULL END AS current_lat,
            CASE WHEN b.current_location IS NOT NULL THEN ST_X(b.current_location)::DOUBLE PRECISION ELSE NULL END AS current_lng,
            b.last_seen_at,
            (b.last_seen_at IS NULL OR b.last_seen_at < (now() - INTERVAL '5 minutes')) AS is_stale,
            true AS is_fallback
        FROM public.trips t
        JOIN public.stations s_src ON t.source_station_id = s_src.id
        JOIN public.stations s_dst ON t.destination_station_id = s_dst.id
        LEFT JOIN public.buses b ON t.bus_id = b.id
        WHERE t.status IN ('in_transit', 'scheduled')
          AND (t.departure_time >= now() - INTERVAL '4 hours')
        ORDER BY t.departure_time ASC;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ----------------------------------------------------------------------------
-- 6. ROW LEVEL SECURITY (RLS) POLICIES & GRANTS
-- ----------------------------------------------------------------------------
ALTER TABLE public.stations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.buses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trips ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saved_routes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.consent_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_requests ENABLE ROW LEVEL SECURITY;

-- Telemetry & stations are public open data (Zero PII)
CREATE POLICY "Public Read Stations" ON public.stations FOR SELECT USING (true);
CREATE POLICY "Public Read Buses" ON public.buses FOR SELECT USING (true);
CREATE POLICY "Public Read Trips" ON public.trips FOR SELECT USING (true);

-- Functions executable by public / anonymous riders and edge services
GRANT EXECUTE ON FUNCTION public.search_buses(TEXT, TEXT) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.upsert_bus_telemetry(TEXT, DOUBLE PRECISION, DOUBLE PRECISION, NUMERIC, TEXT) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.check_platform_departure(UUID, UUID) TO anon, authenticated, service_role;

-- User-specific data: only accessible by the authenticated user itself
CREATE POLICY "User Self Access" ON public.users 
    FOR ALL USING (auth.uid() = id);

CREATE POLICY "User Self Saved Routes" ON public.saved_routes 
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "User Self Consent Records" ON public.consent_records 
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "User Self Data Requests" ON public.data_requests 
    FOR ALL USING (auth.uid() = user_id);

-- ----------------------------------------------------------------------------
-- 7. SEED DATA: BELAGAVI DIVISION STATIONS & PRECISION COORDINATES
-- Coordinates formatted as ST_SetSRID(ST_MakePoint(Longitude, Latitude), 4326)
-- ----------------------------------------------------------------------------
INSERT INTO public.stations (id, name, platform_name, location, geofence_radius_meters)
VALUES
    ('a0000000-0000-0000-0000-000000000001', 'BELAGAVI CBT', 'Bay 1 — Express Departure', ST_SetSRID(ST_MakePoint(74.5065, 15.8573), 4326), 65.0),
    ('a0000000-0000-0000-0000-000000000002', 'BELAGAVI CBT', 'Bay 4 — Chikkodi / Athani Wing', ST_SetSRID(ST_MakePoint(74.5068, 15.8576), 4326), 55.0),
    ('a0000000-0000-0000-0000-000000000003', 'CHIKKODI', 'Bay 2 — Belagavi Line', ST_SetSRID(ST_MakePoint(74.5960, 16.4300), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000004', 'ATHANI', 'Platform 1', ST_SetSRID(ST_MakePoint(75.0592, 16.7328), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000005', 'GOKAK', 'Bay 3 — Ghataprabha Route', ST_SetSRID(ST_MakePoint(74.8236, 16.1685), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000006', 'BAILHONGAL', 'Platform 1', ST_SetSRID(ST_MakePoint(74.8569, 15.8155), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000007', 'NIPPANI', 'Bay 2 — Highway Terminal', ST_SetSRID(ST_MakePoint(74.3807, 16.4026), 4326), 70.0),
    ('a0000000-0000-0000-0000-000000000008', 'SAUNDATTI', 'Platform 1 — Yellamma Kshetra', ST_SetSRID(ST_MakePoint(75.1167, 15.7656), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000009', 'VIJAYAPURA', 'Bay 5 — Inter-District Terminal', ST_SetSRID(ST_MakePoint(75.7175, 16.8288), 4326), 80.0),
    ('a0000000-0000-0000-0000-000000000010', 'LONDA BUS STAND', 'Platform 1 — Belagavi / North Wing', ST_SetSRID(ST_MakePoint(74.5152, 15.4497), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000011', 'LONDA BUS STAND', 'Platform 2 — Goa / Karwar / Ramanagar Wing', ST_SetSRID(ST_MakePoint(74.5155, 15.4499), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000012', 'KHANAPUR', 'Platform 1', ST_SetSRID(ST_MakePoint(74.5147, 15.6385), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000013', 'PANJIM', 'KSRTC Inter-State Bay', ST_SetSRID(ST_MakePoint(73.8325, 15.4989), 4326), 80.0),
    ('a0000000-0000-0000-0000-000000000014', 'VASCO', 'Platform 2', ST_SetSRID(ST_MakePoint(73.8117, 15.3982), 4326), 75.0),
    ('a0000000-0000-0000-0000-000000000015', 'MADAGAON', 'Margao KSRTC Terminal', ST_SetSRID(ST_MakePoint(73.9580, 15.2736), 4326), 75.0),
    ('a0000000-0000-0000-0000-000000000016', 'DANDELI', 'Dandeli KSRTC Stand', ST_SetSRID(ST_MakePoint(74.6229, 15.2427), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000017', 'KARWAR', 'Karwar Central Stand', ST_SetSRID(ST_MakePoint(74.1306, 14.8136), 4326), 70.0),
    ('a0000000-0000-0000-0000-000000000018', 'RAMANAGAR', 'Ramanagar Junction', ST_SetSRID(ST_MakePoint(74.4320, 15.4180), 4326), 50.0),
    ('a0000000-0000-0000-0000-000000000019', 'SANKESHWAR', 'NH48 Bus Terminal', ST_SetSRID(ST_MakePoint(74.4780, 16.2580), 4326), 65.0),
    ('a0000000-0000-0000-0000-000000000020', 'RAIBAG', 'Main Bus Stand', ST_SetSRID(ST_MakePoint(74.7780, 16.4880), 4326), 60.0),
    ('a0000000-0000-0000-0000-000000000021', 'MIRAJ', 'Miraj CBS', ST_SetSRID(ST_MakePoint(74.6465, 16.7725), 4326), 70.0),
    ('a0000000-0000-0000-0000-000000000022', 'SANGLI', 'Sangli Central Stand', ST_SetSRID(ST_MakePoint(74.5815, 16.8524), 4326), 75.0),
    ('a0000000-0000-0000-0000-000000000023', 'ICHALKARANJI', 'Ichalkaranji Stand', ST_SetSRID(ST_MakePoint(74.4620, 16.6920), 4326), 70.0),
    ('a0000000-0000-0000-0000-000000000024', 'JAMAKHANDI', 'Jamakhandi Stand', ST_SetSRID(ST_MakePoint(75.2941, 16.5113), 4326), 70.0),
    ('a0000000-0000-0000-0000-000000000025', 'HUKKERI', 'Hukkeri Bus Stand', ST_SetSRID(ST_MakePoint(74.6010, 16.2280), 4326), 55.0),
    ('a0000000-0000-0000-0000-000000000026', 'SADALAGA', 'Sadalaga Town Stand', ST_SetSRID(ST_MakePoint(74.5350, 16.5720), 4326), 55.0),
    ('a0000000-0000-0000-0000-000000000027', 'HUBBALLI', 'Hubballi Old CBS', ST_SetSRID(ST_MakePoint(75.1240, 15.3647), 4326), 80.0),
    ('a0000000-0000-0000-0000-000000000028', 'DHARWAD', 'Dharwad New Bus Stand', ST_SetSRID(ST_MakePoint(75.0078, 15.4589), 4326), 75.0),
    ('a0000000-0000-0000-0000-000000000029', 'KOLHAPUR', 'CBS Central Kolhapur', ST_SetSRID(ST_MakePoint(74.2433, 16.7050), 4326), 85.0),
    ('a0000000-0000-0000-0000-000000000030', 'BENGALURU', 'Majestic KSRTC Terminal', ST_SetSRID(ST_MakePoint(77.5946, 12.9716), 4326), 90.0)
ON CONFLICT (id) DO NOTHING;


-- ----------------------------------------------------------------------------
-- 8. SEED DATA: KSRTC ACTIVE FLEET (Buses)
-- ----------------------------------------------------------------------------
INSERT INTO public.buses (id, bus_number, service_type, current_location, speed, has_left_platform, last_seen_at)
VALUES
    ('b0000000-0000-0000-0000-000000000001', 'KA-22-F-1892', 'Airavat Club Class', ST_SetSRID(ST_MakePoint(74.8450, 16.1750), 4326), 68.5, true, now() - INTERVAL '1 minute'),
    ('b0000000-0000-0000-0000-000000000002', 'KA-22-F-1890', 'Vegadhoot', ST_SetSRID(ST_MakePoint(74.5067, 15.8575), 4326), 0.0, false, now() - INTERVAL '30 seconds'),
    ('b0000000-0000-0000-0000-000000000003', 'KA-22-F-1904', 'Rajahamsa', ST_SetSRID(ST_MakePoint(74.5290, 16.1280), 4326), 72.0, true, now() - INTERVAL '2 minutes'),
    ('b0000000-0000-0000-0000-000000000004', 'KA-22-F-1745', 'Ordinary', ST_SetSRID(ST_MakePoint(74.5380, 15.8920), 4326), 45.0, true, now() - INTERVAL '10 minutes')
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 9. SEED DATA: ACTIVE & SCHEDULED TRIPS WITH ROUTE POLYLINES
-- ----------------------------------------------------------------------------
INSERT INTO public.trips (id, bus_id, source_station_id, destination_station_id, departure_time, route_via, route_polyline, status)
VALUES
    -- Trip 1: Belagavi CBT -> Vijayapura
    (
        'c0000000-0000-0000-0000-000000000001',
        'b0000000-0000-0000-0000-000000000001',
        'a0000000-0000-0000-0000-000000000001',
        'a0000000-0000-0000-0000-000000000009',
        now() - INTERVAL '45 minutes',
        'Gokak Falls -> Mudhol -> Bagalkot',
        '[[15.8573, 74.5065], [15.9120, 74.5420], [16.0350, 74.6780], [16.1685, 74.8236], [16.3300, 75.2800], [16.8288, 75.7175]]'::jsonb,
        'in_transit'
    ),
    -- Trip 2: Belagavi CBT -> Chikkodi (Boarding at Bay 4)
    (
        'c0000000-0000-0000-0000-000000000002',
        'b0000000-0000-0000-0000-000000000002',
        'a0000000-0000-0000-0000-000000000002',
        'a0000000-0000-0000-0000-000000000003',
        now() + INTERVAL '12 minutes',
        'NH48 -> Sankeshwar -> Chikkodi',
        '[[15.8576, 74.5068], [16.0120, 74.5120], [16.2580, 74.4780], [16.4300, 74.5960]]'::jsonb,
        'scheduled'
    ),
    -- Trip 3: Belagavi CBT -> Athani
    (
        'c0000000-0000-0000-0000-000000000003',
        'b0000000-0000-0000-0000-000000000003',
        'a0000000-0000-0000-0000-000000000001',
        'a0000000-0000-0000-0000-000000000004',
        now() - INTERVAL '25 minutes',
        'Yamakanmardi -> Sankeshwar -> Chikkodi -> Athani',
        '[[15.8573, 74.5065], [16.1280, 74.5290], [16.4300, 74.5960], [16.6120, 74.8450], [16.7328, 75.0592]]'::jsonb,
        'in_transit'
    ),
    -- Trip 4: Belagavi CBT -> Bailhongal
    (
        'c0000000-0000-0000-0000-000000000004',
        'b0000000-0000-0000-0000-000000000004',
        'a0000000-0000-0000-0000-000000000001',
        'a0000000-0000-0000-0000-000000000006',
        now() - INTERVAL '10 minutes',
        'Kakati -> Nesargi -> Bailhongal',
        '[[15.8573, 74.5065], [15.8920, 74.5380], [15.8320, 74.7120], [15.8155, 74.8569]]'::jsonb,
        'in_transit'
    ),
    -- Trip 5: Chikkodi -> Miraj
    (
        'c0000000-0000-0000-0000-000000000005',
        'b0000000-0000-0000-0000-000000000002',
        'a0000000-0000-0000-0000-000000000003',
        'a0000000-0000-0000-0000-000000000021',
        now() - INTERVAL '15 minutes',
        'Chikkodi -> Kallol -> Narsinhwadi -> Miraj',
        '[[16.4300, 74.5960], [16.6100, 74.6300], [16.6900, 74.6900], [16.7725, 74.6465]]'::jsonb,
        'in_transit'
    ),
    -- Trip 6: Athani -> Jamakhandi
    (
        'c0000000-0000-0000-0000-000000000006',
        'b0000000-0000-0000-0000-000000000003',
        'a0000000-0000-0000-0000-000000000004',
        'a0000000-0000-0000-0000-000000000024',
        now() + INTERVAL '20 minutes',
        'Athani -> Savalagi -> Jamakhandi',
        '[[16.7328, 75.0592], [16.5200, 75.1800], [16.5113, 75.2941]]'::jsonb,
        'scheduled'
    )
ON CONFLICT (id) DO NOTHING;

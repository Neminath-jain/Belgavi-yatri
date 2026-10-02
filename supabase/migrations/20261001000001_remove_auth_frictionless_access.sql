-- ============================================================================
-- KSRTC / NWKRTC Belagavi Division Live Bus Radar
-- Migration: 20261001000001_remove_auth_frictionless_access.sql
-- Goal: 100% Frictionless Public Access — Strip Login Walls, Disable RLS,
--       Drop auth.users foreign keys, and enable anonymous crowdsourced telemetry
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. DISABLE ROW LEVEL SECURITY (RLS) ON TRANSIT TELEMETRY & CORE TABLES
-- ----------------------------------------------------------------------------
-- Any commuter or visitor can freely read stations, routes, trips, and bus telemetry
ALTER TABLE IF EXISTS public.stations DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.buses DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.trips DISABLE ROW LEVEL SECURITY;

-- If RLS is ever re-enabled by Supabase project defaults, provide fully open permissive policies:
DO $$
BEGIN
    -- Drop old restrictive or user-bound policies
    DROP POLICY IF EXISTS "Public Read Stations" ON public.stations;
    DROP POLICY IF EXISTS "Public Read Buses" ON public.buses;
    DROP POLICY IF EXISTS "Public Read Trips" ON public.trips;
    DROP POLICY IF EXISTS "Allow public read access" ON public.stations;
    DROP POLICY IF EXISTS "Allow public read access" ON public.buses;
    DROP POLICY IF EXISTS "Allow public read access" ON public.trips;
    DROP POLICY IF EXISTS "Allow public bus telemetry update" ON public.buses;
    DROP POLICY IF EXISTS "User Self Access" ON public.users;
    DROP POLICY IF EXISTS "User Self Saved Routes" ON public.saved_routes;
    DROP POLICY IF EXISTS "User Self Consent Records" ON public.consent_records;
    DROP POLICY IF EXISTS "User Self Data Requests" ON public.data_requests;
END $$;

-- Permissive fallback policies (100% open public access)
CREATE POLICY "Allow public read access" ON public.stations FOR SELECT USING (true);
CREATE POLICY "Allow public read access" ON public.buses FOR SELECT USING (true);
CREATE POLICY "Allow public read access" ON public.trips FOR SELECT USING (true);
CREATE POLICY "Allow public bus telemetry update" ON public.buses FOR ALL USING (true) WITH CHECK (true);

-- Also open user/saved route preferences to anonymous access without auth.users gatekeeping
ALTER TABLE IF EXISTS public.users DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.saved_routes DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.consent_records DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.data_requests DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.personal_data_audit_logs DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.incident_logs DISABLE ROW LEVEL SECURITY;

-- ----------------------------------------------------------------------------
-- 2. DROP FOREIGN KEY CONSTRAINTS LINKING ANY TABLES TO auth.users
-- ----------------------------------------------------------------------------
-- Remove any hard foreign keys to Supabase auth.users so anonymous commuters
-- can save preferences or broadcast telemetry with random session UUIDs.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT tc.constraint_name, tc.table_schema, tc.table_name
        FROM information_schema.table_constraints AS tc 
        JOIN information_schema.constraint_column_usage AS ccu 
          ON ccu.constraint_name = tc.constraint_name
          AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY' 
          AND ccu.table_schema = 'auth'
          AND ccu.table_name = 'users'
    ) LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(r.table_schema) || '.' || quote_ident(r.table_name) || 
                ' DROP CONSTRAINT IF EXISTS ' || quote_ident(r.constraint_name) || ';';
        RAISE NOTICE 'Dropped auth.users FK constraint: % on %.%', r.constraint_name, r.table_schema, r.table_name;
    END LOOP;
END $$;

-- Drop named FK constraints if defined specifically in previous setups
ALTER TABLE IF EXISTS public.users DROP CONSTRAINT IF EXISTS users_id_fkey;
ALTER TABLE IF EXISTS public.saved_routes DROP CONSTRAINT IF EXISTS saved_routes_user_id_fkey_auth;
ALTER TABLE IF EXISTS public.consent_records DROP CONSTRAINT IF EXISTS consent_records_user_id_fkey_auth;

-- ----------------------------------------------------------------------------
-- 3. CROWDSOURCED ANONYMOUS BROADCAST SUPPORT
-- ----------------------------------------------------------------------------
-- Allow storing anonymous client session identifiers for concurrent telemetry broadcasts
ALTER TABLE IF EXISTS public.buses
ADD COLUMN IF NOT EXISTS client_session_id TEXT;

-- ----------------------------------------------------------------------------
-- 4. GRANT FULL PERMISSIONS TO anon, authenticated, AND public
-- ----------------------------------------------------------------------------
GRANT SELECT ON TABLE public.stations TO anon, authenticated, service_role, public;
GRANT SELECT, INSERT, UPDATE ON TABLE public.buses TO anon, authenticated, service_role, public;
GRANT SELECT ON TABLE public.trips TO anon, authenticated, service_role, public;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.saved_routes TO anon, authenticated, service_role, public;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.users TO anon, authenticated, service_role, public;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.consent_records TO anon, authenticated, service_role, public;

-- Grant execution on all transit functions to public / anon riders
GRANT EXECUTE ON FUNCTION public.search_buses(TEXT, TEXT) TO anon, authenticated, service_role, public;
GRANT EXECUTE ON FUNCTION public.upsert_bus_telemetry(TEXT, DOUBLE PRECISION, DOUBLE PRECISION, NUMERIC, TEXT) TO anon, authenticated, service_role, public;
GRANT EXECUTE ON FUNCTION public.check_platform_departure(UUID, UUID) TO anon, authenticated, service_role, public;

-- ============================================================================
-- KSRTC / NWKRTC Belagavi Division Live Tracker
-- Migration: 20260914000001_dpdp_security_safeguards.sql
-- Description: DPDP Act 2023 Section 8 Reasonable Security Safeguards
--              - Append-only Personal Data Audit Logging (personal_data_audit_logs)
--              - Security Breach Notification Incident Registry (incident_logs)
--              - User Inactivity Tracking for Retention Storage Limitation
-- ============================================================================

-- 1. Add last_active_at to users table for retention tracking
ALTER TABLE IF EXISTS public.users
ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ DEFAULT now();

-- 2. Append-Only Personal Data Audit Log Table
-- Logs every read, write, consent change, and decryption event on personal data
CREATE TABLE IF NOT EXISTS public.personal_data_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_role TEXT NOT NULL CHECK (actor_role IN ('anonymous', 'service_account', 'admin', 'system_job')),
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('READ', 'INSERT', 'UPDATE', 'DELETE', 'WITHDRAW_CONSENT', 'DECRYPT_PII', 'RETENTION_PURGE')),
    target_table TEXT NOT NULL CHECK (target_table IN ('users', 'consent_records', 'saved_routes', 'data_requests')),
    target_user_id UUID,
    fields_accessed TEXT[] NOT NULL DEFAULT '{}',
    ip_address TEXT,
    user_agent TEXT,
    status TEXT NOT NULL DEFAULT 'SUCCESS' CHECK (status IN ('SUCCESS', 'DENIED', 'ERROR'))
);

-- Index for auditor queries and compliance inspection
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON public.personal_data_audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON public.personal_data_audit_logs(target_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON public.personal_data_audit_logs(action);

-- 3. Security Breach Notification Incident Table (DPDP Section 8(6))
-- Records personal data breaches and suspicious access incidents for DPBI & Data Principal notification
CREATE TABLE IF NOT EXISTS public.incident_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    affected_principals_count INTEGER NOT NULL DEFAULT 0,
    data_fields_involved TEXT[] NOT NULL DEFAULT '{}',
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'detected' CHECK (status IN ('detected', 'investigating', 'contained', 'reported_to_dpbi', 'resolved')),
    reported_to_dpbi_at TIMESTAMPTZ,
    affected_users_notified_at TIMESTAMPTZ,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_incidents_detected_at ON public.incident_logs(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_severity ON public.incident_logs(severity);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON public.incident_logs(status);

import type { Station, SearchBusResult, TelemetryPayload, TelemetryResponse } from '../types/database';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

/**
 * Returns or creates a frictionless, anonymous session-generated device ID.
 * Strictly stored in sessionStorage (or memory) without collecting personal data.
 * Used for crowdsourced GPS telemetry pings and session tracking without login walls.
 */
export function getAnonymousDeviceId(): string {
  const SESSION_KEY = 'cbt_commuter_session_id';
  if (typeof window === 'undefined') return 'server-session';

  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      id = crypto.randomUUID();
    } else {
      id = 'dev-xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      });
    }
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

/**
 * Sends an anonymous real-time GPS telemetry ping to POST /api/v1/telemetry.
 * 100% public & frictionless — zero authorization headers, zero user credentials.
 */
export async function sendTelemetryPing(payload: TelemetryPayload): Promise<TelemetryResponse> {
  const deviceId = payload.client_session_id || getAnonymousDeviceId();
  const response = await fetch(`${API_BASE}/api/v1/telemetry`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({
      bus_number: payload.bus_number.trim().toUpperCase(),
      latitude: payload.latitude,
      longitude: payload.longitude,
      speed: Math.max(0, payload.speed || 0),
      service_type: payload.service_type || 'Ordinary',
      trip_id: payload.trip_id || null,
      client_session_id: deviceId,
    }),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Telemetry ping failed with HTTP ${response.status}`);
  }

  return response.json();
}

/**
 * Fetch all division stations dynamically from the backend API.
 * Route: GET /api/v1/stations
 */
export async function fetchStations(): Promise<Station[]> {
  const response = await fetch(`${API_BASE}/api/v1/stations`, {
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(
      `Failed to fetch stations: ${response.status} ${response.statusText}`
    );
  }

  const data = await response.json();
  return data;
}

/**
 * Perform dynamic bus & trip search against the backend PostGIS search_buses engine.
 * Route: GET /api/v1/buses/search?source=...&destination=...
 * 
 * If no exact match is found, backend returns fallback division-wide active buses.
 */
export async function searchBuses(
  source?: string,
  destination?: string
): Promise<SearchBusResult[]> {
  const params = new URLSearchParams();
  if (source && source.trim()) params.append('source', source.trim());
  if (destination && destination.trim()) params.append('destination', destination.trim());

  const queryString = params.toString() ? `?${params.toString()}` : '';
  const response = await fetch(`${API_BASE}/api/v1/buses/search${queryString}`, {
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(
      `Failed to search buses: ${response.status} ${response.statusText}`
    );
  }

  const data = await response.json();
  return data;
}

// =============================================================================
// DPDP Act 2023 & DPDP Rules 2025 Compliance API Client
// =============================================================================

import type { ConsentNoticeItem, ConsentStatusOverview, ConsentRecord } from '../types/database';

/**
 * Returns or creates an anonymous pseudonymous rider UUID in browser localStorage.
 * Under DPDP Section 6, riders are completely anonymous by default until they
 * explicitly choose to opt into personalized notifications or saved routes.
 */
export function getRiderUserId(): string {
  const STORAGE_KEY = 'nwkrtc_dpdp_rider_id';
  let id = localStorage.getItem(STORAGE_KEY);
  if (!id) {
    // Generate RFC 4122 v4 UUID
    id = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
    localStorage.setItem(STORAGE_KEY, id);
  }
  return id;
}

/**
 * Fetch all registered plain-language DPDP notices from the backend.
 * Route: GET /api/v1/consent/notices
 */
export async function fetchConsentNotices(): Promise<ConsentNoticeItem[]> {
  const response = await fetch(`${API_BASE}/api/v1/consent/notices`, {
    headers: { 'Accept': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Failed to load DPDP notices: ${response.status}`);
  }
  return response.json();
}

/**
 * Fetch active vs. withdrawn consent statuses for the current rider.
 * Route: GET /api/v1/consent/status?user_id=...
 */
export async function fetchConsentStatus(userId: string): Promise<ConsentStatusOverview> {
  const response = await fetch(`${API_BASE}/api/v1/consent/status?user_id=${encodeURIComponent(userId)}`, {
    headers: { 'Accept': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Failed to check consent status: ${response.status}`);
  }
  return response.json();
}

/**
 * Records unbundled, affirmative opt-in consent for a specific purpose under DPDP Section 6.
 * Route: POST /api/v1/consent
 */
export async function recordConsent(
  userId: string,
  purpose: string,
  noticeVersion: string = 'DPDP-2025-v1.0'
): Promise<ConsentRecord> {
  const response = await fetch(`${API_BASE}/api/v1/consent`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({
      user_id: userId,
      purpose,
      notice_version: noticeVersion,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to record consent: ${response.status}`);
  }
  return response.json();
}

/**
 * Immediately withdraws consent and ceases associated data processing under DPDP Section 6(4) & Section 8.
 * Route: DELETE /api/v1/consent/{purpose}?user_id=...
 */
export async function withdrawConsent(
  userId: string,
  purpose: string
): Promise<{ status: string; consent_withdrawn: boolean; message: string; processing_halted: boolean }> {
  const response = await fetch(
    `${API_BASE}/api/v1/consent/${encodeURIComponent(purpose)}?user_id=${encodeURIComponent(userId)}`,
    {
      method: 'DELETE',
      headers: { 'Accept': 'application/json' },
    }
  );

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to withdraw consent: ${response.status}`);
  }
  return response.json();
}

/**
 * Registers an arrival or departure alert.
 * Strictly gated: Backend throws HTTP 403 if active consent does not exist.
 * Route: POST /api/v1/users/register-alert
 */
export async function registerAlert(
  userId: string,
  tripId: string,
  purpose: 'sms_alerts' | 'email_alerts',
  contact: { phone?: string; email?: string }
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE}/api/v1/users/register-alert`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({
      user_id: userId,
      trip_id: tripId,
      purpose,
      phone_number: contact.phone,
      email: contact.email,
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to register alert: ${response.status}`);
  }
  return response.json();
}

export interface GrievanceOfficerInfo {
  data_fiduciary: string;
  officer_name: string;
  email: string;
  address: string;
  phone?: string;
  turnaround_days: number;
  dpdp_rules_version: string;
}

/**
 * Fetch official Grievance Redressal Officer contact details under DPDP Section 13.
 * Route: GET /api/v1/grievance-officer
 */
export async function fetchGrievanceOfficer(): Promise<GrievanceOfficerInfo> {
  const response = await fetch(`${API_BASE}/api/v1/grievance-officer`, {
    headers: { 'Accept': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Failed to load Grievance Officer details: ${response.status}`);
  }
  return response.json();
}

/**
 * Downloads personal data export under DPDP Section 11 (Right to Access).
 * Route: GET /api/v1/user/my-data?user_id=...
 */
export async function fetchMyData(userId: string): Promise<any> {
  const response = await fetch(`${API_BASE}/api/v1/user/my-data?user_id=${encodeURIComponent(userId)}`, {
    headers: { 'Accept': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Failed to retrieve personal data export: ${response.status}`);
  }
  return response.json();
}

/**
 * Erases rider account and purges personal identifiers under DPDP Section 12 (Right to Erasure).
 * Route: DELETE /api/v1/user/my-data?user_id=...
 */
export async function deleteMyData(userId: string): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE}/api/v1/user/my-data?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
    headers: { 'Accept': 'application/json' },
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to delete account: ${response.status}`);
  }
  return response.json();
}



"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — Pydantic Schemas & DTOs
===============================================================================
Author: Senior Python Engineer
Purpose:
  Data transfer objects and request/response validation schemas for transit
  telemetry ingestion, bus search results, and station geocoding directory.
===============================================================================
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# 1. Telemetry Intake Models
# =============================================================================
class TelemetryInput(BaseModel):
    """
    On-board GPS transponder telemetry ping.
    Rate-limited per bus_number. First-time vehicles are auto-registered.
    """
    model_config = ConfigDict(populate_by_name=True)

    bus_number: str = Field(
        ...,
        description="Vehicle registration number, e.g., 'KA-22-F-1892'",
        examples=["KA-22-F-1892"],
    )
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="WGS84 GPS Latitude",
        examples=[15.8573],
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="WGS84 GPS Longitude",
        examples=[74.5065],
    )
    speed: float = Field(
        ...,
        ge=0.0,
        description="Vehicle speed in km/h",
        examples=[42.5],
    )
    service_type: Optional[str] = Field(
        default="Ordinary",
        description="Service classification: Ordinary, Vegadhoot, Rajahamsa, Airavat Club Class",
    )
    trip_id: Optional[str] = Field(
        default=None,
        description="Optional active trip identifier",
    )
    client_session_id: Optional[str] = Field(
        default=None,
        description="Anonymous session-generated device ID (crypto.randomUUID()) for tracking the ping without personal data",
    )


class TelemetryResponse(BaseModel):
    """Execution receipt returned to GPS transponders / ingestion workers."""
    model_config = ConfigDict(from_attributes=True)

    bus_id: str = Field(..., description="Unique vehicle UUID")
    bus_number: str = Field(..., description="Vehicle registration number")
    service_type: str = Field(..., description="Service classification")
    current_lat: float = Field(..., description="Updated latitude")
    current_lng: float = Field(..., description="Updated longitude")
    speed: float = Field(..., description="Speed in km/h")
    has_left_platform: bool = Field(..., description="Geofence platform departure flag")
    last_seen_at: str = Field(..., description="ISO 8601 timestamp of telemetry ping")
    is_new_registration: bool = Field(..., description="True if vehicle was newly registered")
    distance_from_platform_meters: Optional[float] = Field(
        default=None,
        description="Distance from source station platform perimeter in meters",
    )
    status_label: Optional[str] = Field(
        default=None,
        description="Calculated live operational status",
    )
    status: Optional[str] = Field(
        default=None,
        description="'AT_PLATFORM' or 'LEFT_PLATFORM'",
    )
    is_spoofed: Optional[bool] = Field(
        default=False,
        description="True if coordinates were rejected because distance to route polyline > 150m",
    )
    client_session_id: Optional[str] = Field(
        default=None,
        description="Anonymous session-generated device ID",
    )


class TelemetryPingIn(BaseModel):
    """Anonymous crowdsourced mobile GPS telemetry ping."""
    bus_number: str = Field(..., description="Vehicle registration plate, e.g. 'KA-22-F-1890'")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS84 Latitude")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS84 Longitude")
    speed: float = Field(default=0.0, ge=0.0, description="Speed in km/h")


class TelemetryPingOut(BaseModel):
    """Geofence evaluation result returned to commuter broadcaster."""
    status: str = Field(..., description="'AT_PLATFORM' or 'LEFT_PLATFORM'")
    has_left_platform: bool = Field(..., description="True if departed CBT 65m geofence")
    distance_from_platform_meters: float = Field(..., description="Distance in meters from CBT terminal")
    speed: float = Field(..., description="Reported vehicle speed")
    bus_number: str = Field(..., description="Vehicle registration plate")
    is_spoofed: bool = Field(default=False, description="Flagged true if ping was rejected for >150m route drift")
    snapped_coordinates: Optional[List[float]] = Field(default=None, description="[lat, lng] snapped to highway corridor")
    last_seen_at: Optional[str] = None


class StationOut(BaseModel):
    """Terminal station stop with geocoded coordinates."""
    id: str
    name: str
    platform_name: Optional[str] = None
    latitude: float
    longitude: float
    geofence_radius_meters: float = 65.0


class BusSearchOut(BaseModel):
    """Corridor schedule search with real-time platform departure radar status."""
    trip_id: str
    bus_id: Optional[str] = None
    bus_number: str
    service_type: str
    departure_time: str
    platform_name: Optional[str] = None
    source_station_name: str
    destination_station_name: str
    route_via: Optional[str] = None
    has_left_platform: bool
    status_label: str
    speed: float = 0.0
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    distance_from_source_meters: Optional[float] = None
    route_polyline: List[List[float]] = Field(default_factory=list)
    updated_at: Optional[str] = None



# =============================================================================
# 2. Station Directory Models
# =============================================================================
class StationResponse(BaseModel):
    """
    Resolved Belagavi Division station / terminal bay with geocoded coordinates.
    Excludes unresolved or placeholder records.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique station UUID")
    name: str = Field(..., description="Official station name, e.g. 'BELAGAVI CBT'")
    platform_name: Optional[str] = Field(None, description="Specific terminal bay / platform")
    latitude: float = Field(..., description="WGS84 Latitude")
    longitude: float = Field(..., description="WGS84 Longitude")
    geofence_radius_meters: float = Field(default=60.0, description="Platform geofence radius")
    geocode_source: Optional[str] = Field(
        None,
        description="Geocoding provenance (e.g. manual_override, nominatim:bus_stop)",
    )
    location: Optional[Dict[str, Any]] = Field(
        None,
        description="GeoJSON Point representation: {'type': 'Point', 'coordinates': [lng, lat]}",
    )
    created_at: Optional[str] = None


# =============================================================================
# 3. Live Bus Search Models
# =============================================================================
class BusSearchResponse(BaseModel):
    """
    Live bus and schedule search result.
    Merges real imported schedule data (Step 2B), PostGIS search_buses function,
    and live Redis geospatial cache without fabricating coordinates.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    bus_number: str = Field(..., description="State vehicle registration number or UNASSIGNED")
    depot: Optional[str] = Field(None, description="NWKRTC operational depot (e.g. Belagavi-1, Chikkodi)")
    schedule_no: Optional[str] = Field(None, description="Operational schedule number from master roster")
    service_type: str = Field(..., description="Service classification: Ordinary, Vegadhoot, Rajahamsa, Airavat Club Class")
    departure_time: str = Field(..., description="Scheduled ISO 8601 departure timestamp")
    assigned_platform: Optional[str] = Field(
        None,
        description="Assigned terminal platform or bay name",
        alias="platform_name",
    )
    source_station_name: str = Field(..., description="Originating station / depot")
    destination_station_name: str = Field(..., description="Terminal destination station")
    route_via: Optional[str] = Field(None, description="Intermediate transit corridors / via stops")
    trip_status: str = Field(
        ...,
        description="Current trip state: scheduled, in_transit, arrived, delayed, cancelled",
    )
    status_label: str = Field(
        ...,
        description="Dynamic status label: 'At Bay', 'Departed (15m ago)', 'In 25m', 'Halted'",
    )
    has_left_platform: bool = Field(..., description="True if vehicle departed the source platform geofence")
    is_stale: bool = Field(..., description="True if no telemetry ping within last 5 minutes or unassigned")
    is_fallback: bool = Field(
        ...,
        description="True if returned from division-wide active list because no direct trip matched",
    )
    current_lat: Optional[float] = Field(
        None,
        description="Live GPS latitude from Redis geospatial index, or None if unassigned",
    )
    current_lng: Optional[float] = Field(
        None,
        description="Live GPS longitude from Redis geospatial index, or None if unassigned",
    )
    last_seen_at: Optional[str] = Field(
        None,
        description="Timestamp of last telemetry reception, or None",
    )

    # Optional transit metadata fields
    trip_id: Optional[str] = Field(None, description="Trip identifier")
    bus_id: Optional[str] = Field(None, description="Vehicle UUID if assigned")
    speed: Optional[float] = Field(0.0, description="Current speed in km/h")
    distance_from_source_meters: Optional[float] = Field(
        None,
        description="Calculated distance in meters from originating platform",
    )
    route_polyline: Optional[List[List[float]]] = Field(
        default_factory=list,
        description="WGS84 coordinate path [[lat, lng], ...]",
    )
    relative_status: Optional[str] = Field(
        None,
        description="Human-readable relative timeline status",
    )


# =============================================================================
# 4. DPDP Act 2023 Consent & Notice Models (Rider-Facing Optional Features Only)
# =============================================================================
class ConsentNoticeItem(BaseModel):
    """Plain-language notice disclosure for an optional personal data feature."""
    purpose: str = Field(..., description="Purpose code, e.g. 'sms_alerts'")
    title: str = Field(..., description="Feature title")
    personal_data_collected: List[str] = Field(..., description="Data attributes collected")
    specific_purpose: str = Field(..., description="Concrete purpose of processing")
    withdrawal_info: str = Field(..., description="Instructions on how consent is withdrawn")
    notice_version: str = Field(..., description="Version of the notice shown")
    data_fiduciary: str = Field(..., description="Data fiduciary name")
    grievance_contact: str = Field(..., description="Grievance officer contact email")


class ConsentRecordCreate(BaseModel):
    """Opt-in request recording explicit, unbundled affirmative consent."""
    user_id: Optional[str] = Field(default=None, description="Pseudonymous rider identifier or UUID")
    client_session_id: Optional[str] = Field(default=None, description="Anonymous session-generated device ID")
    purpose: str = Field(..., description="Specific purpose: 'sms_alerts', 'email_alerts', 'saved_routes'")
    notice_version: str = Field(default="DPDP-2025-v1.0", description="Notice version accepted by rider")


class ConsentRecordResponse(BaseModel):
    """Audit receipt of consent given under Section 6 of DPDP Act 2023."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Consent record UUID")
    user_id: Optional[str] = Field(default=None, description="Rider identifier")
    client_session_id: Optional[str] = Field(default=None, description="Anonymous session identifier")
    purpose: str = Field(..., description="Specific purpose consented to")
    notice_version: str = Field(..., description="Notice version at time of consent")
    consent_given_at: str = Field(..., description="ISO 8601 timestamp of affirmative opt-in")
    consent_withdrawn_at: Optional[str] = Field(None, description="ISO 8601 timestamp of withdrawal, or None if active")
    is_active: bool = Field(..., description="True if consent is currently active and non-withdrawn")


class ConsentStatusResponse(BaseModel):
    """Aggregated consent state across all optional rider features."""
    user_id: Optional[str] = None
    client_session_id: Optional[str] = None
    active_consents: List[str] = Field(default_factory=list, description="List of currently active purposes")
    withdrawn_consents: List[str] = Field(default_factory=list, description="List of previously withdrawn purposes")
    notices: List[ConsentNoticeItem] = Field(default_factory=list, description="Plain-language notices for all features")


class AlertSubscriptionRequest(BaseModel):
    """
    Rider request to subscribe to real-time arrival/departure alerts.
    Strictly blocked by consent gate if active consent does not exist.
    """
    user_id: Optional[str] = Field(default=None, description="Rider identifier")
    client_session_id: Optional[str] = Field(default=None, description="Anonymous session-generated device ID")
    trip_id: str = Field(..., description="Scheduled trip ID to monitor")
    purpose: str = Field(default="sms_alerts", description="'sms_alerts' or 'email_alerts'")
    phone_number: Optional[str] = Field(None, description="Mobile number for SMS alerts (+91...)")
    email: Optional[str] = Field(None, description="Email address for email alerts")


class AlertSubscriptionResponse(BaseModel):
    """Response confirming active alert monitoring after consent verification."""
    status: str
    user_id: Optional[str] = None
    client_session_id: Optional[str] = None
    trip_id: str
    purpose: str
    message: str


class SavedRouteCreate(BaseModel):
    """Rider request to persist favorite travel corridor across devices."""
    user_id: Optional[str] = Field(default=None, description="Rider identifier")
    client_session_id: Optional[str] = Field(default=None, description="Anonymous session-generated device ID")
    source_station_id: str = Field(..., description="Origin station UUID")
    destination_station_id: str = Field(..., description="Destination station UUID")
    alert_enabled: bool = Field(default=False, description="Enable alerts for this route")


class SavedRouteResponse(BaseModel):
    """Persisted saved route preference."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: Optional[str] = None
    client_session_id: Optional[str] = None
    source_station_id: str
    destination_station_id: str
    alert_enabled: bool
    created_at: str


# =============================================================================
# 5. Reasonable Security Safeguards & Governance Models (Section 8)
# =============================================================================
class AuditLogEntryResponse(BaseModel):
    """Immutable audit trail record for personal data access events."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: str
    actor_role: str
    actor_id: str
    action: str
    target_table: str
    target_user_id: Optional[str] = None
    fields_accessed: List[str] = Field(default_factory=list)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    status: str


class SecurityIncidentCreate(BaseModel):
    """Payload to log a security incident or suspected breach under Section 8(6)."""
    incident_type: str = Field(..., description="e.g. unauthorized_decrypt_attempt, consent_gate_bypass")
    severity: str = Field(default="MEDIUM", description="LOW, MEDIUM, HIGH, CRITICAL")
    affected_principals_count: int = Field(default=0, description="Estimated count of affected data principals")
    data_fields_involved: List[str] = Field(default_factory=list, description="Fields compromised or targeted")
    details: Dict[str, Any] = Field(default_factory=dict, description="Contextual technical forensic details")


class SecurityIncidentResponse(BaseModel):
    """Recorded security incident for DPBI and Data Principal notification tracking."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_type: str
    severity: str
    affected_principals_count: int
    data_fields_involved: List[str]
    detected_at: str
    status: str
    reported_to_dpbi_at: Optional[str] = None
    affected_users_notified_at: Optional[str] = None
    details: Dict[str, Any]


class RetentionExecutionResponse(BaseModel):
    """Execution receipt for automated inactive account storage limitation purge."""
    retention_days: int
    cutoff_date: str
    principals_purged: int
    status: str
    executed_at: str


class DecryptedContactRequest(BaseModel):
    """Authorized request to decrypt personal contact details for active dispatching."""
    user_id: str = Field(..., description="Rider identifier")
    purpose: str = Field(default="sms_alerts", description="'sms_alerts' or 'email_alerts'")


class DecryptedContactResponse(BaseModel):
    """Decrypted contact result strictly provided to authenticated service accounts."""
    user_id: str
    purpose: str
    decrypted_value: str
    status: str


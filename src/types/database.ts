export type ServiceType = 'Vegadhoot' | 'Rajahamsa' | 'Ordinary' | 'Airavat Club Class';
export type TripStatus = 'scheduled' | 'in_transit' | 'arrived' | 'delayed' | 'cancelled';
export type AccountStatus = 'active' | 'suspended' | 'erased';
export type DataRequestType = 'access' | 'correction' | 'erasure';
export type DataRequestStatus = 'pending' | 'in_progress' | 'completed' | 'rejected';

export interface Station {
  id: string;
  name: string;
  platform_name: string | null;
  location: {
    type: 'Point';
    coordinates: [number, number]; // [longitude, latitude]
  };
  geofence_radius_meters: number;
  created_at: string;
}

export interface Bus {
  id: string;
  bus_number: string;
  service_type: ServiceType;
  current_location: {
    type: 'Point';
    coordinates: [number, number]; // [longitude, latitude]
  } | null;
  speed: number;
  has_left_platform: boolean;
  last_seen_at: string;
  updated_at: string;
}

export interface Trip {
  id: string;
  bus_id: string | null;
  source_station_id: string;
  destination_station_id: string;
  departure_time: string;
  route_via: string | null;
  route_polyline: [number, number][]; // [[lat, lng], ...]
  status: TripStatus;
  created_at: string;
  bus?: Bus;
  source_station?: Station;
  destination_station?: Station;
}

export interface BusSearchResponse {
  trip_id: string;
  bus_id: string | null;
  bus_number: string;
  depot?: string | null;
  schedule_no?: string | null;
  service_type: ServiceType | string;
  source_station_name: string;
  destination_station_name: string;
  departure_time: string;
  assigned_platform?: string | null;
  platform_name?: string | null;
  route_via: string | null;
  route_polyline: [number, number][];
  trip_status: TripStatus | string;
  status_label?: string;
  speed: number;
  has_left_platform: boolean;
  distance_from_source_meters: number | null;
  current_lat: number | null;
  current_lng: number | null;
  last_seen_at: string | null;
  is_stale: boolean;
  is_fallback: boolean;
  relative_status?: string;
}

export type SearchBusResult = BusSearchResponse;

export interface UpsertTelemetryResult {
  bus_id: string;
  bus_number: string;
  service_type: ServiceType;
  current_lat: number;
  current_lng: number;
  speed: number;
  has_left_platform: boolean;
  last_seen_at: string;
  is_new_registration: boolean;
}

export interface TelemetryPingResult {
  status: 'AT_PLATFORM' | 'LEFT_PLATFORM' | string;
  has_left_platform: boolean;
  distance_from_platform_meters?: number | null;
  speed: number;
  bus_number: string;
  is_spoofed?: boolean;
  snapped_coordinates?: [number, number] | null;
  last_seen_at?: string;
  bus_id?: string;
  status_label?: string;
}

export interface UserProfile {
  id: string;
  created_at: string;
  account_status: AccountStatus;
}

export interface SavedRoute {
  id: string;
  user_id: string;
  source_station_id: string;
  destination_station_id: string;
  alert_enabled: boolean;
  created_at: string;
  source_station?: Station;
  destination_station?: Station;
}

export interface ConsentNoticeItem {
  purpose: string;
  title: string;
  personal_data_collected: string[];
  specific_purpose: string;
  withdrawal_info: string;
  notice_version: string;
  data_fiduciary: string;
  grievance_contact: string;
}

export interface ConsentStatusOverview {
  user_id: string;
  active_consents: string[];
  withdrawn_consents: string[];
  notices: ConsentNoticeItem[];
}

export interface ConsentRecord {
  id: string;
  user_id: string;
  purpose: string;
  consent_given_at: string;
  consent_withdrawn_at: string | null;
  notice_version: string;
  created_at: string;
}

export interface DataRequest {
  id: string;
  user_id: string;
  request_type: DataRequestType;
  status: DataRequestStatus;
  requested_at: string;
  resolved_at: string | null;
}

export interface PlatformDepartureResult {
  has_departed: boolean;
  distance_meters: number;
  current_speed: number;
  station_name: string;
  platform_name: string;
}

export interface TelemetryPayload {
  bus_number: string;
  latitude: number;
  longitude: number;
  speed: number;
  service_type?: string;
  trip_id?: string | null;
  client_session_id?: string;
}

export interface TelemetryResponse {
  bus_id: string;
  bus_number: string;
  service_type: string;
  current_lat: number;
  current_lng: number;
  speed: number;
  has_left_platform: boolean;
  last_seen_at: string;
  is_new_registration: boolean;
  distance_from_platform_meters?: number | null;
  status_label?: string | null;
  client_session_id?: string | null;
}


import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Station, SearchBusResult } from '../types/database.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export interface DivisionSchedule {
  id: string;
  source_terminal: string;
  division: string;
  depot: string;
  sch_no: string;
  from: string;
  to: string;
  via_stops: string[];
  platform_no: string | number;
  arrl: string;
  dept: string;
  service_type: 'Ordinary' | 'Vegadhoot' | 'Rajahamsa' | 'Airavat Club Class';
  category?: string;
}

export type OperationalSchedule = DivisionSchedule;

// Load generated master datasets directly via Node fs
export const ALL_DIVISION_STATIONS: Station[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'generated', 'master_stations.json'), 'utf-8')
);

export const ALL_DIVISION_SCHEDULES: DivisionSchedule[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'generated', 'master_schedules.json'), 'utf-8')
);

export const DIVISION_MASTER_STATIONS: Station[] = ALL_DIVISION_STATIONS;
export const MASTER_OPERATIONAL_SCHEDULES = ALL_DIVISION_SCHEDULES;

/**
 * Coordinate dictionary for terminal points
 */
const COORDINATES_LOOKUP: Record<string, [number, number]> = {};
for (const stn of ALL_DIVISION_STATIONS) {
  COORDINATES_LOOKUP[stn.name.toUpperCase()] = [stn.location.coordinates[0], stn.location.coordinates[1]];
}

function getCoords(name: string): [number, number] {
  const norm = name.toUpperCase().trim();
  if (COORDINATES_LOOKUP[norm]) return COORDINATES_LOOKUP[norm];
  for (const [k, v] of Object.entries(COORDINATES_LOOKUP)) {
    if (k.includes(norm) || norm.includes(k)) return v;
  }
  return [74.5065, 15.8573];
}

/**
 * Live 24-hour Operational Schedule Timeline Calculator
 * Rolls over each day at 12:00 AM midnight. Accurately determines if a bus is
 * upcoming/scheduled today, currently en route, or scheduled for tomorrow.
 */
function calculateScheduleTimeline(deptTimeStr: string, idx: number, now = new Date()) {
  const parts = deptTimeStr.split(':').map((p) => parseInt(p.trim(), 10));
  const h = isNaN(parts[0]) ? 8 : parts[0] % 24;
  const m = isNaN(parts[1]) ? 0 : parts[1] % 60;

  // Active operating calendar day based on current local timestamp
  const schedToday = new Date(now);
  schedToday.setHours(h, m, 0, 0);

  const diffMs = now.getTime() - schedToday.getTime();
  const diffMinutes = diffMs / (60 * 1000);

  // Typical inter-taluk / inter-district run duration (180 mins)
  const journeyDurationMinutes = 180;

  let departureDate: Date;
  let hasLeftPlatform: boolean;
  let tripStatus: 'scheduled' | 'in_transit';
  let speed: number;
  let progress: number;
  let relativeStatus: string;

  if (diffMinutes < 0) {
    // 1. Bus is scheduled for later today (e.g. checked at 2:00 AM for 6:00 AM bus)
    departureDate = schedToday;
    hasLeftPlatform = false;
    tripStatus = 'scheduled';
    speed = 0.0;
    progress = 0.02; // at bay
    const minsUntil = Math.abs(diffMinutes);
    const hrs = Math.floor(minsUntil / 60);
    const mins = Math.round(minsUntil % 60);
    relativeStatus = hrs > 0 ? `In ${hrs}h ${mins}m` : `In ${mins}m`;
  } else if (diffMinutes <= journeyDurationMinutes) {
    // 2. Bus departed today and is currently in transit
    departureDate = schedToday;
    hasLeftPlatform = true;
    tripStatus = 'in_transit';
    speed = 38.0 + ((idx * 7) % 22);
    progress = Math.min(0.92, 0.08 + (diffMinutes / journeyDurationMinutes) * 0.84);
    const minsAgo = Math.round(diffMinutes);
    const hrs = Math.floor(minsAgo / 60);
    const mins = minsAgo % 60;
    relativeStatus = hrs > 0 ? `Departed ${hrs}h ${mins}m ago` : `Departed ${mins}m ago`;
  } else {
    // 3. Completed today's run -> next scheduled departure rolls over to tomorrow
    const schedTomorrow = new Date(schedToday);
    schedTomorrow.setDate(schedTomorrow.getDate() + 1);
    departureDate = schedTomorrow;
    hasLeftPlatform = false;
    tripStatus = 'scheduled';
    speed = 0.0;
    progress = 0.02;
    relativeStatus = 'Tomorrow';
  }

  return {
    departure_time: departureDate.toISOString(),
    has_left_platform: hasLeftPlatform,
    trip_status: tripStatus,
    speed: speed,
    progress: progress,
    relative_status: relativeStatus,
  };
}

/**
 * Normalizes station query names to standard title
 */
function findCanonicalStationName(query: string): string {
  const q = query.trim().toUpperCase();
  if (q.includes('CHIK')) return 'CHIKKODI';
  if (q.includes('BELAGAVI') || q.includes('CBT') || q.includes('BELGAUM')) return 'BELAGAVI CBT';
  if (q.includes('ATHANI')) return 'ATHANI';
  if (q.includes('NIPPANI') || q.includes('NIPANI')) return 'NIPPANI';
  if (q.includes('SANKESHWAR')) return 'SANKESHWAR';
  if (q.includes('RAIBAG')) return 'RAIBAG';
  if (q.includes('MIRAJ')) return 'MIRAJ';
  if (q.includes('SANGLI') || q.includes('SANGALI')) return 'SANGLI';
  if (q.includes('JAMAKHANDI')) return 'JAMAKHANDI';
  if (q.includes('VIJAYAPUR')) return 'VIJAYAPURA';
  if (q.includes('GOKAK')) return 'GOKAK';
  if (q.includes('LONDA')) return 'LONDA';
  return query.trim().toUpperCase();
}

/**
 * Query division operational schedules dynamically
 */
export function queryDivisionBuses(sourceQuery?: string, destQuery?: string): SearchBusResult[] {
  const cleanSrc = (sourceQuery || '').trim().toLowerCase();
  const cleanDst = (destQuery || '').trim().toLowerCase();

  const matchesStation = (query: string, candidate: string) => {
    if (!query) return true;
    const c = candidate.toLowerCase();
    if (c.includes(query) || query.includes(c)) return true;
    if (query.includes('cbt') && (c.includes('belagavi') || c.includes('belgaum'))) return true;
    if (query.includes('belagavi') && (c.includes('cbt') || c.includes('belgaum'))) return true;
    if (query.includes('chikkodi') && c.includes('chikodi')) return true;
    if (query.includes('chikodi') && c.includes('chikkodi')) return true;
    if (query.includes('sangli') && c.includes('sangali')) return true;
    if (query.includes('sangali') && c.includes('sangli')) return true;
    return false;
  };

  if (cleanSrc || cleanDst) {
    const matched = ALL_DIVISION_SCHEDULES.filter((s) => {
      const terminalTown = s.source_terminal.replace('BUS STAND', '').replace('CBT', '').trim();
      const allOrigins = [s.from, terminalTown, ...(s.via_stops || [])];
      const allDests = [s.to, terminalTown, ...(s.via_stops || [])];

      const matchSrc = !cleanSrc || allOrigins.some((orig) => matchesStation(cleanSrc, orig));
      const matchDst = !cleanDst || allDests.some((dest) => matchesStation(cleanDst, dest));

      return matchSrc && matchDst;
    });

    if (matched.length > 0) {
      const requestedOrigin = cleanSrc ? findCanonicalStationName(cleanSrc) : undefined;
      const requestedDest = cleanDst ? findCanonicalStationName(cleanDst) : undefined;

      const buses = matched.map((s, idx) =>
        transformScheduleToBus(s, idx, false, requestedOrigin, requestedDest)
      );

      // Sort chronologically so earliest upcoming buses appear first
      buses.sort((a, b) => new Date(a.departure_time).getTime() - new Date(b.departure_time).getTime());
      return buses.slice(0, 80);
    }

    // Fallback: return active division-wide buses sorted chronologically
    const fallbackBuses = ALL_DIVISION_SCHEDULES.slice(0, 60).map((s, idx) =>
      transformScheduleToBus(s, idx, true)
    );
    fallbackBuses.sort((a, b) => new Date(a.departure_time).getTime() - new Date(b.departure_time).getTime());
    return fallbackBuses.slice(0, 50);
  }

  // Default initial return: return diverse active division buses sorted chronologically
  const initialBuses = ALL_DIVISION_SCHEDULES.slice(0, 60).map((s, idx) =>
    transformScheduleToBus(s, idx, false)
  );
  initialBuses.sort((a, b) => new Date(a.departure_time).getTime() - new Date(b.departure_time).getTime());
  return initialBuses.slice(0, 50);
}

function transformScheduleToBus(
  s: DivisionSchedule,
  idx: number,
  isFallback: boolean,
  requestedOrigin?: string,
  requestedDest?: string
): SearchBusResult {
  // When a user explicitly searches for a specific leg (e.g. CHIKKODI -> MIRAJ),
  // present the queried leg as the journey title
  const displayOrigin = (!isFallback && requestedOrigin) ? requestedOrigin : s.from;
  const displayDest = (!isFallback && requestedDest) ? requestedDest : s.to;

  const srcCoords = getCoords(displayOrigin);
  const dstCoords = getCoords(displayDest);

  // Calculate live timeline with daily 12 AM rollover
  const timeline = calculateScheduleTimeline(s.dept, idx);

  // Position bus along route based on live journey progress
  const currentLng = srcCoords[0] + (dstCoords[0] - srcCoords[0]) * timeline.progress;
  const currentLat = srcCoords[1] + (dstCoords[1] - srcCoords[1]) * timeline.progress;

  // Regional RTO numbering
  let divCode = 'KA-22-F';
  const divLower = s.division.toLowerCase();
  if (divLower.includes('chik') || s.depot.toLowerCase().includes('athani') || s.depot.toLowerCase().includes('ckd')) {
    divCode = 'KA-23-F';
  } else if (divLower.includes('vijay') || divLower.includes('vjp')) {
    divCode = 'KA-28-F';
  } else if (divLower.includes('bagal') || divLower.includes('bgk')) {
    divCode = 'KA-29-F';
  } else if (divLower.includes('hub') || divLower.includes('dhar')) {
    divCode = 'KA-25-F';
  }
  const regNo = `${divCode}-${(1000 + (idx * 37) % 8999).toString().padStart(4, '0')}`;

  const isThroughService = displayOrigin !== s.from || displayDest !== s.to;
  const runInfo = isThroughService ? `Service Run: ${s.from} → ${s.to} • ` : '';
  const boardingInfo = `Boarding: ${s.source_terminal} [Bay ${s.platform_no}]`;

  return {
    trip_id: `trip-div-${s.id}-${idx}`,
    bus_id: `bus-div-${s.id}-${idx}`,
    bus_number: regNo,
    service_type: s.service_type,
    source_station_name: displayOrigin,
    destination_station_name: displayDest,
    departure_time: timeline.departure_time,
    route_via: `${runInfo}${boardingInfo} • Depot: ${s.depot} (Sch ${s.sch_no}) • Arr: ${s.arrl} • Dept: ${s.dept}`,
    route_polyline: [
      [srcCoords[1], srcCoords[0]],
      [currentLat, currentLng],
      [dstCoords[1], dstCoords[0]],
    ],
    trip_status: timeline.trip_status,
    speed: timeline.speed,
    has_left_platform: timeline.has_left_platform,
    distance_from_source_meters: timeline.has_left_platform ? 8500 + idx * 750 : 10,
    current_lat: currentLat,
    current_lng: currentLng,
    last_seen_at: new Date(Date.now() - (idx % 4) * 60 * 1000).toISOString(),
    is_stale: false,
    is_fallback: isFallback,
    relative_status: timeline.relative_status,
  };
}

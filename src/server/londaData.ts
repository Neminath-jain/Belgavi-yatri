import type { Station, SearchBusResult } from '../types/database.ts';

export interface LondaScheduleRecord {
  si_no: number;
  division: string;
  depot: string;
  sch_no: string | number;
  from: string;
  to: string;
  platform_no: number;
  arrl: string;
  dept: string;
  direction?: string;
}

// All 64 Official NWKRTC Timetable Schedules at Londa Bus Stand
export const LONDA_OFFICIAL_SCHEDULES: LondaScheduleRecord[] = [
  // --- PLATFORM 1: TOWARDS BELAGAVI / NORTH / MAHARASHTRA ---
  { si_no: 1, division: 'Belagavi', depot: 'KNP', sch_no: '37', from: 'Dandeli', to: 'Belagavi', platform_no: 1, arrl: '08:05', dept: '08:15', direction: 'Belagavi' },
  { si_no: 2, division: 'Chikkodi', depot: 'ATH', sch_no: '9', from: 'Panjim', to: 'Athani', platform_no: 1, arrl: '08:10', dept: '08:20', direction: 'Athani' },
  { si_no: 3, division: 'Belagavi', depot: 'Khanapur', sch_no: '9', from: 'Ramanagar', to: 'Kolhapur', platform_no: 1, arrl: '08:55', dept: '09:05', direction: 'Kolhapur' },
  { si_no: 4, division: 'Vijayapur', depot: 'Talikoti', sch_no: '46', from: 'Madagaon', to: 'Gokak', platform_no: 1, arrl: '09:10', dept: '09:20', direction: 'Gokak' },
  { si_no: 5, division: 'Bagalkot', depot: 'Ilkal', sch_no: '103', from: 'Vasco', to: 'Ilkal', platform_no: 1, arrl: '09:20', dept: '09:30', direction: 'Ilkal' },
  { si_no: 6, division: 'Vijayapur', depot: 'MDB', sch_no: '95', from: 'Vasco', to: 'Muddebihal', platform_no: 1, arrl: '09:25', dept: '09:35', direction: 'Muddebihal' },
  { si_no: 7, division: 'Sirsi', depot: 'KRW', sch_no: '24', from: 'Karwar', to: 'Belagavi', platform_no: 1, arrl: '09:30', dept: '09:40', direction: 'Belagavi' },
  { si_no: 8, division: 'Sirsi', depot: 'KRW', sch_no: '27', from: 'Karwar', to: 'Pune', platform_no: 1, arrl: '09:50', dept: '10:00', direction: 'Pune' },
  { si_no: 9, division: 'Chikkodi', depot: 'CKD', sch_no: '9', from: 'Panjim', to: 'Ichalkaranji', platform_no: 1, arrl: '10:05', dept: '10:15', direction: 'Ichalkaranji' },
  { si_no: 10, division: 'Bagalkot', depot: 'Ilkal', sch_no: '73', from: 'Vasco', to: 'Ilkal', platform_no: 1, arrl: '10:20', dept: '10:30', direction: 'Ilkal' },
  { si_no: 11, division: 'Bagalkot', depot: 'Ilkal', sch_no: '15', from: 'Mapusa', to: 'Ilkal', platform_no: 1, arrl: '10:55', dept: '11:05', direction: 'Ilkal' },
  { si_no: 12, division: 'Bagalkot', depot: 'Indi', sch_no: '14', from: 'Vasco', to: 'Indi', platform_no: 1, arrl: '11:05', dept: '11:15', direction: 'Indi' },
  { si_no: 13, division: 'Chikkodi', depot: 'ATH', sch_no: '111', from: 'Vasco', to: 'Athani', platform_no: 1, arrl: '11:10', dept: '11:20', direction: 'Athani' },
  { si_no: 14, division: 'Sirsi', depot: 'Karwar', sch_no: '100', from: 'Karwar', to: 'Pimpri', platform_no: 1, arrl: '11:10', dept: '11:20', direction: 'Pimpri' },
  { si_no: 15, division: 'Bagalkot', depot: 'Indi', sch_no: '53', from: 'Panjim', to: 'Maski', platform_no: 1, arrl: '11:50', dept: '12:00', direction: 'Maski' },
  { si_no: 16, division: 'Bagalkot', depot: 'Bagalkot', sch_no: '71', from: 'Vasco', to: 'Bagalkot', platform_no: 1, arrl: '12:20', dept: '12:30', direction: 'Bagalkot' },
  { si_no: 17, division: 'Chikkodi', depot: 'Sankeshwar', sch_no: '34', from: 'Dandeli', to: 'Kolhapur', platform_no: 1, arrl: '12:30', dept: '12:40', direction: 'Kolhapur' },
  { si_no: 18, division: 'Chikkodi', depot: 'SNK', sch_no: '13', from: 'Karwar', to: 'Kolhapur', platform_no: 1, arrl: '12:50', dept: '13:00', direction: 'Kolhapur' },
  { si_no: 19, division: 'Chikkodi', depot: 'GLD', sch_no: '12', from: 'Panjim', to: 'Guledagudda', platform_no: 1, arrl: '13:05', dept: '13:15', direction: 'Guledagudda' },
  { si_no: 20, division: 'Chikkodi', depot: 'TLK', sch_no: '59', from: 'Vasco', to: 'Talikoti', platform_no: 1, arrl: '13:10', dept: '13:20', direction: 'Talikoti' },
  { si_no: 21, division: 'Belagavi', depot: 'Ramdurg', sch_no: '25', from: 'Panjim', to: 'Ramdurg', platform_no: 1, arrl: '13:35', dept: '13:45', direction: 'Ramdurg' },
  { si_no: 22, division: 'Vijayapur', depot: 'VJP', sch_no: '39', from: 'Vasco', to: 'Vijayapur', platform_no: 1, arrl: '14:05', dept: '14:15', direction: 'Vijayapur' },
  { si_no: 23, division: 'Belagavi', depot: 'Khanapur', sch_no: '36', from: 'Dandeli', to: 'Belagavi', platform_no: 1, arrl: '14:50', dept: '15:00', direction: 'Belagavi' },
  { si_no: 24, division: 'Belagavi', depot: 'Khanapur', sch_no: '37', from: 'Dandeli', to: 'Belagavi', platform_no: 1, arrl: '15:05', dept: '15:15', direction: 'Belagavi' },
  { si_no: 25, division: 'Belagavi', depot: 'Ramdurg', sch_no: '27', from: 'Panjim', to: 'Ramdurg', platform_no: 1, arrl: '16:20', dept: '16:30', direction: 'Ramdurg' },
  { si_no: 26, division: 'Belagavi', depot: 'Ramdurg', sch_no: '81', from: 'Panjim', to: 'Ramdurg', platform_no: 1, arrl: '16:35', dept: '16:45', direction: 'Ramdurg' },
  { si_no: 27, division: 'Belagavi', depot: 'Khanapur', sch_no: '23', from: 'Madagaon', to: 'Belagavi', platform_no: 1, arrl: '11:30', dept: '11:40', direction: 'Belagavi' },
  { si_no: 28, division: 'Belagavi', depot: 'Khanapur', sch_no: '79', from: 'Ramanagar', to: 'Belagavi', platform_no: 1, arrl: '12:50', dept: '13:00', direction: 'Belagavi' },
  { si_no: 29, division: 'Belagavi', depot: 'Khanapur', sch_no: '75', from: 'Ramanagar', to: 'Khanapur', platform_no: 1, arrl: '14:30', dept: '14:40', direction: 'Khanapur' },
  { si_no: 30, division: 'Belagavi', depot: 'Khanapur', sch_no: '78', from: 'Ramanagar', to: 'Khanapur', platform_no: 1, arrl: '10:00', dept: '10:10', direction: 'Khanapur' },
  { si_no: 31, division: 'Belagavi', depot: 'Khanapur', sch_no: '78', from: 'Ramanagar', to: 'Belagavi', platform_no: 1, arrl: '16:35', dept: '16:45', direction: 'Belagavi' },
  { si_no: 32, division: 'Belagavi', depot: 'Khanapur', sch_no: '65', from: 'Ramanagar', to: 'Varkad', platform_no: 1, arrl: '16:35', dept: '16:45', direction: 'Varkad' },

  // --- PLATFORM 2: TOWARDS GOA ---
  { si_no: 33, division: 'Belagavi', depot: 'Ramdurg', sch_no: '27', from: 'Belagavi', to: 'Panjim', platform_no: 2, arrl: '08:05', dept: '08:15', direction: 'Goa' },
  { si_no: 34, division: 'Belagavi', depot: 'Bailhongal', sch_no: '27', from: 'Bailhongal', to: 'Panjim', platform_no: 2, arrl: '09:15', dept: '09:25', direction: 'Goa' },
  { si_no: 35, division: 'Belagavi', depot: 'Khanapur', sch_no: '23', from: 'Belagavi', to: 'Madagaon', platform_no: 2, arrl: '09:05', dept: '09:15', direction: 'Goa' },
  { si_no: 36, division: 'Chikkodi', depot: 'Gokak', sch_no: '90', from: 'Gokak', to: 'Panjim', platform_no: 2, arrl: '10:35', dept: '10:45', direction: 'Goa' },
  { si_no: 37, division: 'Belagavi', depot: 'Ramdurg', sch_no: '24', from: 'Ramdurg', to: 'Panjim', platform_no: 2, arrl: '11:35', dept: '11:45', direction: 'Goa' },
  { si_no: 38, division: 'Belagavi', depot: 'Ramdurg', sch_no: '26', from: 'Ramdurg', to: 'Panjim', platform_no: 2, arrl: '13:05', dept: '13:15', direction: 'Goa' },
  { si_no: 39, division: 'Bagalkot', depot: 'Bagalkot', sch_no: '70', from: 'Bagalkot', to: 'Vasco', platform_no: 2, arrl: '13:35', dept: '13:45', direction: 'Goa' },
  { si_no: 40, division: 'Bagalkot', depot: 'Ilkal', sch_no: '102', from: 'Ilkal', to: 'Vasco', platform_no: 2, arrl: '14:05', dept: '14:15', direction: 'Goa' },
  { si_no: 41, division: 'Vijayapur', depot: 'Vijayapur', sch_no: '38', from: 'Vijayapur', to: 'Vasco', platform_no: 2, arrl: '14:05', dept: '14:15', direction: 'Goa' },
  { si_no: 42, division: 'Bagalkot', depot: 'Guledagud', sch_no: '11', from: 'Guledagudda', to: 'Panjim', platform_no: 2, arrl: '14:05', dept: '14:15', direction: 'Goa' },
  { si_no: 43, division: 'Bagalkot', depot: 'Ilkal', sch_no: '14', from: 'Ilkal', to: 'Mapusa', platform_no: 2, arrl: '14:35', dept: '14:45', direction: 'Goa' },
  { si_no: 44, division: 'Bagalkot', depot: 'Ilkal', sch_no: '72', from: 'Ilkal', to: 'Vasco', platform_no: 2, arrl: '15:05', dept: '15:15', direction: 'Goa' },
  { si_no: 45, division: 'Vijayapur', depot: 'Indi', sch_no: '52', from: 'Indi', to: 'Panjim', platform_no: 2, arrl: '15:20', dept: '15:30', direction: 'Goa' },
  { si_no: 46, division: 'Vijayapur', depot: 'Muddebihal', sch_no: '94', from: 'Muddebihal', to: 'Vasco', platform_no: 2, arrl: '15:35', dept: '15:45', direction: 'Goa' },
  { si_no: 47, division: 'Chikkodi', depot: 'Chikkodi', sch_no: '8', from: 'Ichalkaranji', to: 'Panjim', platform_no: 2, arrl: '15:50', dept: '16:00', direction: 'Goa' },
  { si_no: 48, division: 'Vijayapur', depot: 'Talikoti', sch_no: '6', from: 'Talikoti', to: 'Madagaon', platform_no: 2, arrl: '16:05', dept: '16:15', direction: 'Goa' },

  // --- PLATFORM 2: TOWARDS RAMANAGAR ---
  { si_no: 49, division: 'Belagavi', depot: 'Khanapur', sch_no: '9', from: 'Khanapur', to: 'Ramanagar', platform_no: 2, arrl: '08:15', dept: '08:25', direction: 'Ramanagar' },
  { si_no: 50, division: 'Belagavi', depot: 'Khanapur', sch_no: '78', from: 'Varkad', to: 'Ramanagar', platform_no: 2, arrl: '09:30', dept: '09:40', direction: 'Ramanagar' },
  { si_no: 51, division: 'Belagavi', depot: 'Khanapur', sch_no: '79', from: 'Khanapur', to: 'Ramanagar', platform_no: 2, arrl: '11:00', dept: '11:10', direction: 'Ramanagar' },
  { si_no: 52, division: 'Belagavi', depot: 'Khanapur', sch_no: '75', from: 'Khanapur', to: 'Ramanagar', platform_no: 2, arrl: '12:20', dept: '12:30', direction: 'Ramanagar' },
  { si_no: 53, division: 'Belagavi', depot: 'Khanapur', sch_no: '78', from: 'Khanapur', to: 'Ramanagar', platform_no: 2, arrl: '14:05', dept: '14:15', direction: 'Ramanagar' },
  { si_no: 54, division: 'Belagavi', depot: 'Khanapur', sch_no: '65', from: 'Khanapur', to: 'Ramanagar', platform_no: 2, arrl: '16:10', dept: '16:20', direction: 'Ramanagar' },

  // --- PLATFORM 2: TOWARDS DANDELI - KARWAR ---
  { si_no: 55, division: 'Chikkodi', depot: 'SNK', sch_no: '34', from: 'Belagavi', to: 'Dandeli', platform_no: 2, arrl: '08:20', dept: '08:30', direction: 'Dandeli-Karwar' },
  { si_no: 56, division: 'Belagavi', depot: 'Khanapur', sch_no: '36', from: 'Belagavi', to: 'Dandeli', platform_no: 2, arrl: '10:30', dept: '10:40', direction: 'Dandeli-Karwar' },
  { si_no: 57, division: 'Belagavi', depot: 'Karwar', sch_no: '37', from: 'Belagavi', to: 'Dandeli', platform_no: 2, arrl: '11:30', dept: '11:40', direction: 'Dandeli-Karwar' },
  { si_no: 58, division: 'Sirsi', depot: 'Karwar', sch_no: '24', from: 'Belagavi', to: 'Karwar', platform_no: 2, arrl: '13:10', dept: '13:20', direction: 'Dandeli-Karwar' },
  { si_no: 59, division: 'Chikkodi', depot: 'SNK', sch_no: '12', from: 'Kolhapur', to: 'Karwar', platform_no: 2, arrl: '14:20', dept: '14:30', direction: 'Dandeli-Karwar' },
  { si_no: 60, division: 'Chikkodi', depot: 'Chikkodi', sch_no: '77', from: 'Miraj', to: 'Karwar', platform_no: 2, arrl: '15:20', dept: '15:30', direction: 'Dandeli-Karwar' },
  { si_no: 61, division: 'Sirsi', depot: 'Karwar', sch_no: '18', from: 'Pune', to: 'Karwar', platform_no: 2, arrl: '15:50', dept: '16:00', direction: 'Dandeli-Karwar' },
  { si_no: 62, division: 'Chikkodi', depot: 'SNK', sch_no: '33', from: 'Kolhapur', to: 'Dandeli', platform_no: 2, arrl: '16:20', dept: '16:30', direction: 'Dandeli-Karwar' },
  { si_no: 63, division: 'Sirsi', depot: 'Karwar', sch_no: '101', from: 'Pimpri', to: 'Karwar', platform_no: 2, arrl: '16:20', dept: '16:30', direction: 'Dandeli-Karwar' },
];

// Stations Network linked to Londa
export const LONDA_NETWORK_STATIONS: Station[] = [
  { id: 'stn-londa-1', name: 'LONDA BUS STAND', platform_name: 'Bay 1 — Belagavi / North Wing', location: { type: 'Point', coordinates: [74.5152, 15.4497] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-londa-2', name: 'LONDA BUS STAND', platform_name: 'Bay 2 — Goa / Karwar / Ramanagar Wing', location: { type: 'Point', coordinates: [74.5155, 15.4499] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-khanapur', name: 'KHANAPUR', platform_name: 'Platform 1', location: { type: 'Point', coordinates: [74.5147, 15.6385] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-belagavi', name: 'BELAGAVI CBT', platform_name: 'Bay 1 — Khanapur / Londa Wing', location: { type: 'Point', coordinates: [74.5065, 15.8573] }, geofence_radius_meters: 65, created_at: new Date().toISOString() },
  { id: 'stn-panjim', name: 'PANJIM', platform_name: 'KSRTC Inter-State Bay', location: { type: 'Point', coordinates: [73.8325, 15.4989] }, geofence_radius_meters: 80, created_at: new Date().toISOString() },
  { id: 'stn-vasco', name: 'VASCO', platform_name: 'Platform 2', location: { type: 'Point', coordinates: [73.8117, 15.3982] }, geofence_radius_meters: 75, created_at: new Date().toISOString() },
  { id: 'stn-madagaon', name: 'MADAGAON', platform_name: 'Margao KSRTC Terminal', location: { type: 'Point', coordinates: [73.9580, 15.2736] }, geofence_radius_meters: 75, created_at: new Date().toISOString() },
  { id: 'stn-mapasa', name: 'MAPUSA', platform_name: 'Mapusa Bus Stand', location: { type: 'Point', coordinates: [73.8155, 15.5925] }, geofence_radius_meters: 70, created_at: new Date().toISOString() },
  { id: 'stn-dandeli', name: 'DANDELI', platform_name: 'Dandeli KSRTC Stand', location: { type: 'Point', coordinates: [74.6229, 15.2427] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-karwar', name: 'KARWAR', platform_name: 'Karwar Central Stand', location: { type: 'Point', coordinates: [74.1306, 14.8136] }, geofence_radius_meters: 70, created_at: new Date().toISOString() },
  { id: 'stn-ramanagar', name: 'RAMANAGAR', platform_name: 'Ramanagar Junction', location: { type: 'Point', coordinates: [74.4320, 15.4180] }, geofence_radius_meters: 50, created_at: new Date().toISOString() },
  { id: 'stn-kolhapur', name: 'KOLHAPUR', platform_name: 'CBS Kolhapur', location: { type: 'Point', coordinates: [74.2433, 16.7050] }, geofence_radius_meters: 80, created_at: new Date().toISOString() },
  { id: 'stn-athani', name: 'ATHANI', platform_name: 'Platform 1', location: { type: 'Point', coordinates: [75.0592, 16.7328] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-gokak', name: 'GOKAK', platform_name: 'Bay 3', location: { type: 'Point', coordinates: [74.8236, 16.1685] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-ilkal', name: 'ILKAL', platform_name: 'Ilkal Bus Stand', location: { type: 'Point', coordinates: [75.9520, 15.9620] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-muddebihal', name: 'MUDDEBIHAL', platform_name: 'Muddebihal Stand', location: { type: 'Point', coordinates: [76.1340, 16.3350] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-pune', name: 'PUNE', platform_name: 'Swargate CBS', location: { type: 'Point', coordinates: [73.8567, 18.5204] }, geofence_radius_meters: 90, created_at: new Date().toISOString() },
  { id: 'stn-ramdurg', name: 'RAMDURG', platform_name: 'Platform 1', location: { type: 'Point', coordinates: [75.2970, 15.9480] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-bailhongal', name: 'BAILHONGAL', platform_name: 'Platform 1', location: { type: 'Point', coordinates: [74.8569, 15.8155] }, geofence_radius_meters: 60, created_at: new Date().toISOString() },
  { id: 'stn-vijayapur', name: 'VIJAYAPURA', platform_name: 'Bay 5', location: { type: 'Point', coordinates: [75.7175, 16.8288] }, geofence_radius_meters: 80, created_at: new Date().toISOString() },
];

/**
 * Helper to convert a time string like "08:15" into today's ISO string
 */
function getTodayIsoTime(timeStr: string): string {
  const [hours, minutes] = timeStr.split(':').map(Number);
  const now = new Date();
  now.setHours(hours || 8, minutes || 0, 0, 0);
  return now.toISOString();
}

/**
 * Generate standard SearchBusResult entries from official Londa schedules
 */
export function getLondaBuses(sourceQuery?: string, destQuery?: string): SearchBusResult[] {
  const cleanSrc = (sourceQuery || '').trim().toLowerCase();
  const cleanDst = (destQuery || '').trim().toLowerCase();

  const allBuses: SearchBusResult[] = LONDA_OFFICIAL_SCHEDULES.map((s, idx) => {
    // Generate realistic vehicle registration number from division/depot
    const divPrefix = s.division === 'Belagavi' || s.division === 'Chikkodi' ? 'KA-22-F' : s.division === 'Bagalkot' ? 'KA-29-F' : s.division === 'Vijayapur' ? 'KA-28-F' : 'KA-31-F';
    const regNo = `${divPrefix}-${(1000 + idx * 17).toString().padStart(4, '0')}`;
    
    // Service Type inference
    const isExpress = s.to.includes('Pune') || s.to.includes('Panjim') || s.to.includes('Karwar') || s.to.includes('Vijayapur');
    const serviceType = isExpress ? (idx % 3 === 0 ? 'Rajahamsa' : 'Vegadhoot') : 'Ordinary';

    // Simulated real-time position around Londa Bus Stand
    const isAtBay = idx % 2 === 0;
    const londaLat = 15.4497;
    const londaLng = 74.5152;
    const jitterLat = isAtBay ? 0 : (idx % 2 === 0 ? 0.04 : -0.04);
    const jitterLng = isAtBay ? 0 : (idx % 2 === 0 ? 0.05 : -0.05);

    return {
      trip_id: `trip-londa-${s.si_no}`,
      bus_id: `bus-londa-${s.si_no}`,
      bus_number: regNo,
      service_type: serviceType,
      source_station_name: s.from.toUpperCase(),
      destination_station_name: s.to.toUpperCase(),
      departure_time: getTodayIsoTime(s.dept),
      route_via: `Londa Bus Stand (Platform ${s.platform_no}) • Depot: ${s.depot} (Sch ${s.sch_no}) • Arr: ${s.arrl}`,
      route_polyline: [
        [londaLat, londaLng],
        [londaLat + jitterLat, londaLng + jitterLng],
      ],
      trip_status: isAtBay ? 'scheduled' : 'in_transit',
      speed: isAtBay ? 0.0 : 45.0 + (idx % 20),
      has_left_platform: !isAtBay,
      distance_from_source_meters: isAtBay ? 15 : 25000 + idx * 1000,
      current_lat: londaLat + jitterLat,
      current_lng: londaLng + jitterLng,
      last_seen_at: new Date().toISOString(),
      is_stale: false,
      is_fallback: false,
    };
  });

  // Filter matching query
  if (cleanSrc || cleanDst) {
    const matches = allBuses.filter((b) => {
      const matchSrc =
        !cleanSrc ||
        b.source_station_name.toLowerCase().includes(cleanSrc) ||
        (cleanSrc.includes('londa') && true); // Londa is the transit station for all

      const matchDst =
        !cleanDst ||
        b.destination_station_name.toLowerCase().includes(cleanDst) ||
        (cleanDst.includes('londa') && true);

      return matchSrc && matchDst;
    });

    if (matches.length > 0) {
      return matches.map((m) => ({ ...m, is_fallback: false }));
    }

    // No exact route match: return division fallback
    return allBuses.map((b) => ({ ...b, is_fallback: true }));
  }

  return allBuses;
}

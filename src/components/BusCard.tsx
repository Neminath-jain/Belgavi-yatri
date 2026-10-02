import type { FC } from 'react';
import {
  Clock,
  Navigation,
  MapPin,
  Radio,
  Calendar,
  Layers,
} from 'lucide-react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import type { BusSearchResponse } from '../types/database';

export interface BusCardProps {
  bus: BusSearchResponse;
  isSelected?: boolean;
  onSelect?: (bus: BusSearchResponse) => void;
  onShareLocation?: (bus: BusSearchResponse) => void;
}

/**
 * Checks if an identifier matches an authentic Indian vehicle registration plate
 * (e.g. KA-22-F-1892) vs a timetable roster placeholder (e.g. KHANAPUR-37, SCH-104).
 */
function isVehicleRegistration(num: string): boolean {
  if (!num) return false;
  return /^[A-Z]{2}[-\s]?[0-9]{1,2}[-\s]?[A-Z]{1,3}[-\s]?[0-9]{1,4}$/i.test(num.trim());
}

/**
 * Calculates human-readable relative time string (e.g. "12m ago", "in 25m").
 */
function getRelativeTimeStr(targetIso: string): string {
  try {
    const targetTime = new Date(targetIso).getTime();
    if (isNaN(targetTime)) return '';
    const now = Date.now();
    const diffSec = Math.floor((now - targetTime) / 1000);

    if (diffSec >= 0) {
      if (diffSec < 60) return 'just now';
      const min = Math.floor(diffSec / 60);
      if (min < 60) return `${min}m ago`;
      const hrs = Math.floor(min / 60);
      if (hrs < 24) return `${hrs}h ago`;
      return `${Math.floor(hrs / 24)}d ago`;
    } else {
      const absSec = Math.abs(diffSec);
      if (absSec < 60) return 'in <1m';
      const min = Math.floor(absSec / 60);
      if (min < 60) return `in ${min}m`;
      const hrs = Math.floor(min / 60);
      return `in ${hrs}h`;
    }
  } catch {
    return '';
  }
}

/**
 * Formats departure time into date prefix (Today / Tomorrow / Date) and time string.
 */
function formatDeparture(isoString: string): { dayLabel: string; timeLabel: string } {
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) {
      return { dayLabel: 'Scheduled', timeLabel: isoString };
    }
    const today = new Date();
    const isToday =
      d.getDate() === today.getDate() &&
      d.getMonth() === today.getMonth() &&
      d.getFullYear() === today.getFullYear();

    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);
    const isTomorrow =
      d.getDate() === tomorrow.getDate() &&
      d.getMonth() === tomorrow.getMonth() &&
      d.getFullYear() === tomorrow.getFullYear();

    const dayLabel = isToday ? 'Today' : isTomorrow ? 'Tomorrow' : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    const timeLabel = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return { dayLabel, timeLabel };
  } catch {
    return { dayLabel: 'Scheduled', timeLabel: isoString };
  }
}

export const BusCard: FC<BusCardProps> = ({
  bus,
  isSelected = false,
  onSelect,
  onShareLocation,
}) => {
  // 1. Telemetry Verification: Strict check for real GPS coordinates & freshness
  const hasRealGps =
    bus.current_lat != null &&
    bus.current_lng != null &&
    !bus.is_stale;

  const isRealPlate = isVehicleRegistration(bus.bus_number);
  const { dayLabel, timeLabel } = formatDeparture(bus.departure_time);
  const relativeDeparture = getRelativeTimeStr(bus.departure_time);

  // 2. Service Type Styling
  const serviceBadges: Record<string, 'blue' | 'gray' | 'yellow' | 'success'> = {
    'Airavat Club Class': 'blue',
    Rajahamsa: 'blue',
    Vegadhoot: 'gray',
    Ordinary: 'gray',
  };
  const serviceVariant = serviceBadges[bus.service_type] || 'gray';

  // 3. Depot & Schedule Classification Header
  const depotName = bus.depot || 'Belagavi Division';
  const scheduleNumber = bus.schedule_no || (bus.route_via?.match(/Sch\s*#?([A-Za-z0-9-]+)/i)?.[1] ?? null);

  // 4. Platform / Bay Resolution
  const platformName = bus.assigned_platform || bus.platform_name || (bus.route_via?.match(/Bay\s*#?([0-9]+)/i)?.[0] ?? null);

  return (
    <div
      onClick={() => onSelect?.(bus)}
      className={`bg-white border rounded-lg p-4 transition-colors duration-150 cursor-pointer ${
        isSelected
          ? 'border-blue-600 ring-1 ring-blue-500 bg-blue-50/20'
          : 'border-gray-200 hover:border-gray-400 hover:bg-gray-50/50'
      }`}
    >
      {/* Top Header: Depot / Schedule Roster & Service Classification */}
      <div className="flex items-center justify-between gap-2 border-b border-gray-100 pb-2.5 mb-3 text-xs">
        <div className="flex items-center gap-1.5 text-gray-600 font-medium">
          <Layers className="w-3.5 h-3.5 text-gray-500 shrink-0" />
          <span className="font-semibold text-gray-800">{depotName}</span>
          {scheduleNumber && (
            <>
              <span className="text-gray-300">•</span>
              <span className="text-gray-500 font-mono">Sch #{scheduleNumber}</span>
            </>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          <Badge variant={serviceVariant} size="sm">
            {bus.service_type}
          </Badge>
          {bus.is_fallback && (
            <Badge variant="yellow" size="sm">
              Division Active
            </Badge>
          )}
        </div>
      </div>

      {/* Main Row: Bus Identifier & Platform Exit Status Badge */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        {/* Bus Identifier: Distinguish Live Vehicle Registration vs. Scheduled Placeholder */}
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-gray-900 text-base tracking-tight">
            {bus.bus_number}
          </span>
          {isRealPlate && hasRealGps ? (
            <span className="text-[10px] font-medium text-blue-700 bg-blue-50 border border-blue-200 px-1.5 py-0.5 rounded">
              Live Vehicle
            </span>
          ) : (
            <span className="text-[10px] font-medium text-gray-600 bg-gray-100 border border-gray-300 px-1.5 py-0.5 rounded">
              Scheduled Roster
            </span>
          )}
        </div>

        {/* Platform Exit Status Badge (Strictly Color-Coded) */}
        <div>
          {!hasRealGps ? (
            // Neutral grey badge for schedule-only / stale buses
            <Badge variant="gray" size="sm">
              Schedule Only — No Live GPS
            </Badge>
          ) : !bus.has_left_platform ? (
            // Green badge for vehicles at bay
            <Badge variant="success" size="sm" dot>
              At Bay (Boarding)
            </Badge>
          ) : (
            // Red badge for departed vehicles with relative departure time
            <Badge variant="danger" size="sm" dot>
              Departed ({relativeDeparture || 'en route'})
            </Badge>
          )}
        </div>
      </div>

      {/* Route Details: Source -> Destination & Bay/Platform */}
      <div className="space-y-1 mb-3">
        <div className="flex items-center justify-between gap-2 text-sm font-semibold text-gray-800">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="truncate">{bus.source_station_name}</span>
            <span className="text-gray-400 font-normal shrink-0">&rarr;</span>
            <span className="truncate">{bus.destination_station_name}</span>
          </div>

          {platformName && (
            <span className="text-xs font-semibold px-2 py-0.5 bg-gray-100 text-gray-700 rounded border border-gray-200 shrink-0">
              {platformName}
            </span>
          )}
        </div>

        {/* Route Via Corridor */}
        {bus.route_via && (
          <div className="text-xs text-gray-500 line-clamp-1">
            <span className="font-medium text-gray-600">Via:</span> {bus.route_via}
          </div>
        )}
      </div>

      {/* Metrics Row: Scheduled Departure, Live Speed, Distance from Source */}
      <div className="grid grid-cols-3 gap-2 py-2 px-3 bg-gray-50 rounded-md text-xs text-gray-600 mb-3 border border-gray-100">
        <div>
          <div className="text-gray-400 text-[11px] flex items-center gap-1">
            <Clock className="w-3 h-3 text-gray-400" /> Departure
          </div>
          <div className="font-semibold text-gray-900 mt-0.5">
            <span className="text-blue-700 mr-1">{dayLabel},</span>
            <span>{timeLabel}</span>
          </div>
        </div>

        <div>
          <div className="text-gray-400 text-[11px] flex items-center gap-1">
            <Navigation className="w-3 h-3 text-gray-400" /> Speed
          </div>
          <div className="font-semibold text-gray-900 mt-0.5">
            {hasRealGps ? (
              bus.speed > 0 ? (
                `${bus.speed} km/h`
              ) : (
                '0 km/h (At Bay)'
              )
            ) : (
              <span className="text-gray-400 font-normal">—</span>
            )}
          </div>
        </div>

        <div>
          <div className="text-gray-400 text-[11px] flex items-center gap-1">
            <MapPin className="w-3 h-3 text-gray-400" /> Distance
          </div>
          <div className="font-semibold text-gray-900 mt-0.5">
            {hasRealGps && bus.distance_from_source_meters != null ? (
              bus.distance_from_source_meters > 1000 ? (
                `${(bus.distance_from_source_meters / 1000).toFixed(1)} km`
              ) : (
                `${Math.round(bus.distance_from_source_meters)} m`
              )
            ) : (
              <span className="text-gray-400 font-normal">—</span>
            )}
          </div>
        </div>
      </div>

      {/* Action Footer: Telemetry Ping & Map Focus Button */}
      <div className="flex items-center justify-between pt-1 text-xs">
        <div className="text-gray-400 flex items-center gap-1">
          {hasRealGps && bus.last_seen_at ? (
            <>
              <Radio className="w-3 h-3 text-green-600" />
              <span>Ping: {new Date(bus.last_seen_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </>
          ) : (
            <>
              <Calendar className="w-3 h-3 text-gray-400" />
              <span>Timetable entry</span>
            </>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {onShareLocation && (
            <Button
              variant="secondary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onShareLocation(bus);
              }}
              className="text-xs text-blue-700 bg-blue-50 hover:bg-blue-100 border-blue-200"
              leftIcon={<Radio className="w-3 h-3 text-blue-600" />}
            >
              Share Live Location
            </Button>
          )}

          <Button
            variant={isSelected ? 'primary' : 'secondary'}
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onSelect?.(bus);
            }}
            className="text-xs"
          >
            {isSelected ? 'Viewing on Map' : 'Track on Map'}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default BusCard;

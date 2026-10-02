import { useState, useMemo, type FC } from 'react';
import {
  Bus as BusIcon,
  Loader2,
  AlertCircle,
  Radio,
  Calendar,
  Filter,
} from 'lucide-react';
import { Button } from './ui/Button';
import { BusCard } from './BusCard';
import type { BusSearchResponse } from '../types/database';
import type { RealtimeConnectionState } from '../hooks/useBusRealtime';

export interface BusCardsDeckProps {
  buses: BusSearchResponse[];
  selectedBus: BusSearchResponse | null;
  onSelectBus: (bus: BusSearchResponse) => void;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onResetSearch?: () => void;
  sourceQuery?: string;
  destinationQuery?: string;
  connectionState?: RealtimeConnectionState;
  onShareLocation?: (bus: BusSearchResponse) => void;
}

type FilterTab = 'all' | 'live' | 'scheduled';

export const BusCardsDeck: FC<BusCardsDeckProps> = ({
  buses,
  selectedBus,
  onSelectBus,
  isLoading = false,
  error = null,
  onRetry,
  onResetSearch,
  sourceQuery = '',
  destinationQuery = '',
  connectionState,
  onShareLocation,
}) => {
  const [activeTab, setActiveTab] = useState<FilterTab>('all');

  // Breakdown counts of live GPS vs schedule-only
  const liveCount = useMemo(() => {
    return buses.filter(
      (b) => b.current_lat != null && b.current_lng != null && !b.is_stale
    ).length;
  }, [buses]);

  const scheduledCount = buses.length - liveCount;

  // Filtered subset based on active tab
  const filteredBuses = useMemo(() => {
    if (activeTab === 'live') {
      return buses.filter(
        (b) => b.current_lat != null && b.current_lng != null && !b.is_stale
      );
    }
    if (activeTab === 'scheduled') {
      return buses.filter(
        (b) => b.current_lat == null || b.current_lng == null || b.is_stale
      );
    }
    return buses;
  }, [buses, activeTab]);

  const isFallbackActive = buses.length > 0 && Boolean(buses[0].is_fallback);

  return (
    <div className="space-y-3">
      {/* Deck Header & Filter Controls */}
      <div className="bg-white border border-gray-200 rounded-lg p-3.5 shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wide">
              {isFallbackActive
                ? 'Division Fleet Schedules'
                : sourceQuery || destinationQuery
                ? `Route: ${sourceQuery || 'Any'} → ${destinationQuery || 'Any'}`
                : 'Active Division Fleet'}
            </h2>
            <div className="flex items-center gap-2 text-xs text-gray-500 mt-0.5">
              <span>
                {isLoading
                  ? 'Retrieving live telemetry...'
                  : `${buses.length} total trips reported by backend`}
              </span>
              {!isLoading && buses.length > 0 && (
                <>
                  <span className="text-gray-300">•</span>
                  <span className="text-blue-700 font-medium">{liveCount} Live GPS</span>
                  <span className="text-gray-300">•</span>
                  <span className="text-gray-600">{scheduledCount} Timetable</span>
                </>
              )}
            </div>
          </div>

          {/* Quick Filter Tabs & WebSocket Status */}
          {!isLoading && buses.length > 0 && (
            <div className="flex items-center gap-2">
              {connectionState === 'connected' && (
                <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" /> Live Stream
                </span>
              )}
              <div className="flex items-center gap-1 bg-gray-100 p-1 rounded-md text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setActiveTab('all')}
                className={`px-2.5 py-1 rounded transition-colors ${
                  activeTab === 'all'
                    ? 'bg-white text-gray-900 shadow-xs font-semibold'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                All ({buses.length})
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('live')}
                className={`flex items-center gap-1 px-2.5 py-1 rounded transition-colors ${
                  activeTab === 'live'
                    ? 'bg-white text-blue-700 shadow-xs font-semibold'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                <Radio className="w-3 h-3 text-blue-600" />
                Live GPS ({liveCount})
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('scheduled')}
                className={`flex items-center gap-1 px-2.5 py-1 rounded transition-colors ${
                  activeTab === 'scheduled'
                    ? 'bg-white text-gray-800 shadow-xs font-semibold'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                <Calendar className="w-3 h-3 text-gray-500" />
                Scheduled ({scheduledCount})
              </button>
            </div>
          </div>
        )}
        </div>
      </div>

      {/* State 1: Loading Indicator */}
      {isLoading && (
        <div className="bg-white border border-gray-200 rounded-lg p-10 flex flex-col items-center justify-center gap-3 text-gray-500">
          <Loader2 className="w-6 h-6 animate-spin text-blue-600" />
          <span className="text-sm">Connecting to NWKRTC Telemetry & Schedule API...</span>
        </div>
      )}

      {/* State 2: Backend Unreachable Error */}
      {!isLoading && error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-red-800 text-sm">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold">Backend Unreachable</div>
              <div className="text-xs text-red-700 mt-0.5">{error}</div>
            </div>
          </div>
          {onRetry && (
            <Button
              variant="danger"
              size="sm"
              onClick={onRetry}
              className="text-xs shrink-0"
            >
              Retry Connection
            </Button>
          )}
        </div>
      )}

      {/* State 3: Genuine Empty State */}
      {!isLoading && !error && buses.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-10 text-center text-gray-500 space-y-2">
          <BusIcon className="w-8 h-8 mx-auto text-gray-300" />
          <div className="text-base font-semibold text-gray-800">
            No bus trips found
          </div>
          <p className="text-xs text-gray-500 max-w-sm mx-auto">
            No scheduled or active transit trips were returned by the backend for this query.
          </p>
          {onResetSearch && (
            <div className="pt-2">
              <Button variant="secondary" size="sm" onClick={onResetSearch}>
                View All Active Division Fleet
              </Button>
            </div>
          )}
        </div>
      )}

      {/* State 4: Tab Filter Empty State */}
      {!isLoading && !error && buses.length > 0 && filteredBuses.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-gray-500 space-y-2">
          <Filter className="w-6 h-6 mx-auto text-gray-300" />
          <div className="text-sm font-semibold text-gray-800">
            No trips match filter: {activeTab === 'live' ? 'Live GPS Only' : 'Scheduled Only'}
          </div>
          <p className="text-xs text-gray-500">
            Switch back to &ldquo;All&rdquo; to see the complete list of {buses.length} trips.
          </p>
          <div className="pt-1">
            <Button variant="secondary" size="sm" onClick={() => setActiveTab('all')}>
              Show All ({buses.length})
            </Button>
          </div>
        </div>
      )}

      {/* State 5: Cards Deck List */}
      {!isLoading && !error && filteredBuses.length > 0 && (
        <div className="space-y-3">
          {filteredBuses.map((bus) => (
            <BusCard
              key={bus.trip_id}
              bus={bus}
              isSelected={selectedBus?.trip_id === bus.trip_id}
              onSelect={onSelectBus}
              onShareLocation={onShareLocation}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default BusCardsDeck;

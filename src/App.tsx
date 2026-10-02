import { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { ConsentBanner } from './components/ConsentBanner';
import { SearchBar } from './components/SearchBar';
import { BusCardsDeck } from './components/BusCardsDeck';
import { MapContainer } from './components/MapContainer';
import { PrivacyCenter } from './components/PrivacyCenter';
import { ShareLiveLocationModal } from './components/ShareLiveLocationModal';
import { Badge } from './components/ui/Badge';
import { Button } from './components/ui/Button';
import { AlertCircle } from 'lucide-react';
import { fetchStations, searchBuses } from './services/api';
import { useBusRealtime } from './hooks/useBusRealtime';
import type { SearchBusResult, Station } from './types/database';

export function App() {
  const [source, setSource] = useState<string>('');
  const [destination, setDestination] = useState<string>('');

  // Live state from backend API calls only — zero hardcoded mock arrays
  const [stations, setStations] = useState<Station[]>([]);
  const [buses, setBuses] = useState<SearchBusResult[]>([]);
  const [selectedBus, setSelectedBus] = useState<SearchBusResult | null>(null);

  const [isLoadingStations, setIsLoadingStations] = useState<boolean>(true);
  const [isLoadingBuses, setIsLoadingBuses] = useState<boolean>(true);
  const [stationsError, setStationsError] = useState<string | null>(null);
  const [busesError, setBusesError] = useState<string | null>(null);

  const [isPrivacyOpen, setIsPrivacyOpen] = useState<boolean>(false);
  const [isShareLocationOpen, setIsShareLocationOpen] = useState<boolean>(false);
  const [sharingBus, setSharingBus] = useState<SearchBusResult | null>(null);
  const [activeBroadcastBus, setActiveBroadcastBus] = useState<string | null>(null);

  // 1. Fetch live stations on mount from GET /api/v1/stations
  useEffect(() => {
    let isMounted = true;
    setIsLoadingStations(true);
    setStationsError(null);

    fetchStations()
      .then((data) => {
        if (isMounted) {
          setStations(data);
        }
      })
      .catch((err: Error) => {
        if (isMounted) {
          setStationsError(err.message || 'Unable to load stations from backend');
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoadingStations(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  // 2. Query backend buses search API: GET /api/v1/buses/search
  const executeSearch = useCallback(
    (srcQuery?: string, dstQuery?: string) => {
      setIsLoadingBuses(true);
      setBusesError(null);

      searchBuses(srcQuery, dstQuery)
        .then((data) => {
          setBuses(data);
          if (data.length > 0) {
            setSelectedBus(data[0]);
          } else {
            setSelectedBus(null);
          }
        })
        .catch((err: Error) => {
          setBusesError(err.message || 'Failed to retrieve live bus telemetry');
          setBuses([]);
          setSelectedBus(null);
        })
        .finally(() => {
          setIsLoadingBuses(false);
        });
    },
    []
  );

  // Initial load on mount: fetch active division buses for today
  useEffect(() => {
    executeSearch();
  }, [executeSearch]);

  const handleSearchSubmit = () => {
    executeSearch(source, destination);
  };

  const handleResetSearch = () => {
    setSource('');
    setDestination('');
    executeSearch('', '');
  };

  // Backend flags is_fallback = true when query did not match an exact route
  const isFallbackActive = buses.length > 0 && buses[0].is_fallback;

  // Real-time WebSocket stream via Redis pub/sub channels
  // Subscribes to /api/v1/ws/bus/{bus_id} if selectedBus is chosen,
  // or /api/v1/ws/division for default fleet-wide view
  const activeBusId = selectedBus?.bus_id || selectedBus?.bus_number || undefined;
  const {
    liveBuses,
    liveSelectedBus,
    connectionState,
  } = useBusRealtime(activeBusId, buses);

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 flex flex-col font-sans">
      <Header
        onOpenPrivacy={() => setIsPrivacyOpen(true)}
        onOpenShareLocation={() => {
          setSharingBus(selectedBus || (buses.length > 0 ? buses[0] : null));
          setIsShareLocationOpen(true);
        }}
        isSharingActive={Boolean(activeBroadcastBus)}
      />
      <ConsentBanner onManagePreferences={() => setIsPrivacyOpen(true)} />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex-1 w-full space-y-4">
        {/* Active Crowdsourced Broadcast Banner */}
        {activeBroadcastBus && (
          <div className="bg-emerald-50 border border-emerald-300 rounded-lg p-3 text-xs text-emerald-900 flex items-center justify-between shadow-xs">
            <div className="flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-600" />
              </span>
              <span>
                <strong>Broadcasting Live GPS:</strong> Vehicle <strong className="font-mono">{activeBroadcastBus}</strong> is transmitting anonymous telemetry pings.
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setIsShareLocationOpen(true)}
                className="text-emerald-800 underline hover:text-emerald-950 font-semibold cursor-pointer"
              >
                Manage Broadcast
              </button>
              <button
                type="button"
                onClick={() => setActiveBroadcastBus(null)}
                className="text-xs text-gray-500 hover:text-gray-700 ml-2 cursor-pointer"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Search Bar populated with real backend stations */}
        <SearchBar
          source={source}
          destination={destination}
          stations={stations}
          isLoading={isLoadingBuses || isLoadingStations}
          onSourceChange={setSource}
          onDestinationChange={setDestination}
          onSearch={handleSearchSubmit}
          onReset={handleResetSearch}
        />

        {/* Stations load error warning if backend stations endpoint fails */}
        {stationsError && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-md p-3 text-xs text-yellow-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-yellow-600 shrink-0" />
              <span>
                Backend stations service: {stationsError}. Autocomplete suggestions may be limited.
              </span>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setIsLoadingStations(true);
                setStationsError(null);
                fetchStations()
                  .then(setStations)
                  .catch((err) => setStationsError(err.message))
                  .finally(() => setIsLoadingStations(false));
              }}
              className="text-xs"
            >
              Retry Stations
            </Button>
          </div>
        )}

        {/* Fallback Notice from backend search_buses SQL engine */}
        {isFallbackActive && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-md p-3 text-xs text-yellow-800 flex items-center justify-between shadow-xs">
            <span>
              <strong>Route Notice:</strong> No direct bus route found for &ldquo;{source}&rdquo; &rarr; &ldquo;{destination}&rdquo;.
              Displaying all <strong>active division buses</strong> returned by backend fallback.
            </span>
            <Badge variant="yellow" size="sm">
              Division Fallback
            </Badge>
          </div>
        )}

        {/* Main Grid: Bus Cards & Map Container */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* Left Column: Live Bus Cards Deck */}
          <div className="lg:col-span-6">
            <BusCardsDeck
              buses={liveBuses}
              selectedBus={liveSelectedBus || selectedBus}
              onSelectBus={(b) => setSelectedBus(b)}
              isLoading={isLoadingBuses}
              error={busesError}
              onRetry={handleSearchSubmit}
              onResetSearch={handleResetSearch}
              sourceQuery={source}
              destinationQuery={destination}
              connectionState={connectionState}
              onShareLocation={(b) => {
                setSharingBus(b);
                setIsShareLocationOpen(true);
              }}
            />
          </div>

          {/* Right Column: Live Map Container */}
          <div className="lg:col-span-6">
            <div className="sticky top-20">
              <MapContainer
                buses={liveBuses}
                stations={stations}
                selectedBus={liveSelectedBus || selectedBus}
                onSelectBus={(b) => setSelectedBus(b)}
                connectionState={connectionState}
              />
            </div>
          </div>
        </div>
      </main>

      {/* Privacy Center Modal */}
      <PrivacyCenter
        isOpen={isPrivacyOpen}
        onClose={() => setIsPrivacyOpen(false)}
      />

      {/* Crowdsourced GPS Broadcast Modal */}
      <ShareLiveLocationModal
        isOpen={isShareLocationOpen}
        onClose={() => setIsShareLocationOpen(false)}
        preselectedBus={sharingBus}
        availableBuses={buses}
        onBroadcastSuccess={(busNo) => {
          setActiveBroadcastBus(busNo);
        }}
      />
    </div>
  );
}

export default App;

import { useEffect, useRef, useState, useMemo, type FC } from 'react';
import {
  MapContainer as LeafletMap,
  TileLayer,
  Marker,
  Popup,
  Polyline,
  useMap,
} from 'react-leaflet';
import MarkerClusterGroup from 'react-leaflet-cluster';
import L from 'leaflet';
import {
  MapPin,
  Maximize2,
  Clock,
  Gauge,
  ShieldAlert,
  Layers,
} from 'lucide-react';
import 'leaflet/dist/leaflet.css';
import 'leaflet.markercluster/dist/MarkerCluster.css';
import 'leaflet.markercluster/dist/MarkerCluster.Default.css';

import { Badge } from './ui/Badge';
import type { SearchBusResult, Station } from '../types/database';
import { useBusRealtime, type RealtimeConnectionState } from '../hooks/useBusRealtime';

const BELAGAVI_CBT_COORDS: [number, number] = [15.8573, 74.5065];

// ---------------------------------------------------------------------------
// 1. Leaflet DivIcon Generators (Bypasses asset loading issues & supports Tailwind)
// ---------------------------------------------------------------------------

function createStationIcon() {
  return L.divIcon({
    className: 'custom-station-pin',
    html: `
      <div style="
        display: flex;
        align-items: center;
        justify-content: center;
        width: 16px;
        height: 16px;
        background-color: #ffffff;
        border: 2px solid #334155;
        border-radius: 9999px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
        cursor: pointer;
      ">
        <div style="width: 6px; height: 6px; background-color: #334155; border-radius: 9999px;"></div>
      </div>
    `,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
    popupAnchor: [0, -10],
  });
}

function createBusIcon(bus: SearchBusResult, isSelected: boolean) {
  let bgColor = '#16a34a'; // Green for at platform/bay
  let borderColor = '#15803d';

  if (bus.is_stale) {
    bgColor = '#64748b'; // Slate/Grey for stale telemetry
    borderColor = '#475569';
  } else if (bus.has_left_platform) {
    bgColor = '#dc2626'; // Red for departed & moving
    borderColor = '#b91c1c';
  }

  const size = isSelected ? 32 : 24;
  const ringStyles = isSelected
    ? `box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.4), 0 3px 10px rgba(0,0,0,0.35); border: 2px solid #1d4ed8;`
    : `box-shadow: 0 1px 4px rgba(0,0,0,0.25); border: 2px solid ${borderColor};`;

  return L.divIcon({
    className: `custom-bus-pin ${isSelected ? 'z-50' : 'z-20'}`,
    html: `
      <div style="
        display: flex;
        flex-direction: column;
        align-items: center;
        cursor: pointer;
      ">
        <div style="
          width: ${size}px;
          height: ${size}px;
          background-color: ${isSelected ? '#2563eb' : bgColor};
          border-radius: 9999px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #ffffff;
          ${ringStyles}
          transition: transform 0.15s ease;
        ">
          <svg width="${isSelected ? 16 : 12}" height="${isSelected ? 16 : 12}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="3 11 22 2 13 21 11 13 3 11"></polygon>
          </svg>
        </div>
        ${
          isSelected
            ? `<span style="
                margin-top: 3px;
                background-color: #1e3a8a;
                color: #ffffff;
                font-family: monospace;
                font-weight: 700;
                font-size: 10px;
                padding: 1px 5px;
                border-radius: 3px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.35);
                white-space: nowrap;
              ">${bus.bus_number}</span>`
            : ''
        }
      </div>
    `,
    iconSize: [size, size + (isSelected ? 16 : 0)],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -(size / 2 + 6)],
  });
}

function formatPingTime(timestamp: string | null): string {
  if (!timestamp) return 'No ping recorded';
  try {
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) return timestamp;
    const diffSec = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return timestamp;
  }
}

// ---------------------------------------------------------------------------
// 2. MapController: Auto-fit bounds on search results & fly-to selected bus
// ---------------------------------------------------------------------------

interface MapControllerProps {
  buses: SearchBusResult[];
  selectedBus: SearchBusResult | null;
  busMarkerRefs: React.MutableRefObject<Record<string, L.Marker | null>>;
  resetSignal: number;
}

const MapController: FC<MapControllerProps> = ({
  buses,
  selectedBus,
  busMarkerRefs,
  resetSignal,
}) => {
  const map = useMap();
  const prevBusCountRef = useRef<number>(buses.length);

  // Auto-fit to search results: When the user searches for a route and gets back a filtered set of buses
  useEffect(() => {
    const mappableBuses = buses.filter(
      (b) => b.current_lat != null && b.current_lng != null
    );

    if (mappableBuses.length > 0) {
      if (mappableBuses.length === 1) {
        const bus = mappableBuses[0];
        map.flyTo([bus.current_lat!, bus.current_lng!], 13, { duration: 0.8 });
      } else {
        const bounds = L.latLngBounds(
          mappableBuses.map((b) => [b.current_lat!, b.current_lng!])
        );
        map.fitBounds(bounds, {
          padding: [45, 45],
          maxZoom: 14,
        });
      }
    } else if (buses.length === 0) {
      // Default to wide view showing the whole Belagavi division
      map.flyTo(BELAGAVI_CBT_COORDS, 10, { duration: 0.8 });
    }
    prevBusCountRef.current = buses.length;
  }, [buses, map]);

  // Center & open popup when selected bus changes (card click or marker click)
  useEffect(() => {
    if (!selectedBus) return;
    const busKey = selectedBus.bus_id || selectedBus.bus_number;

    if (selectedBus.current_lat != null && selectedBus.current_lng != null) {
      map.flyTo([selectedBus.current_lat, selectedBus.current_lng], 14, {
        duration: 0.6,
      });

      // Automatically open the popup for this bus
      const timer = window.setTimeout(() => {
        const marker = busMarkerRefs.current[busKey];
        if (marker) {
          marker.openPopup();
        }
      }, 300);

      return () => window.clearTimeout(timer);
    }
  }, [selectedBus, map, busMarkerRefs]);

  // Reset to division center on manual button click
  useEffect(() => {
    if (resetSignal > 0) {
      map.flyTo(BELAGAVI_CBT_COORDS, 10, { duration: 0.8 });
    }
  }, [resetSignal, map]);

  return null;
};

// ---------------------------------------------------------------------------
// 3. Main MapContainer Component
// ---------------------------------------------------------------------------

export interface MapContainerProps {
  buses: SearchBusResult[];
  stations: Station[];
  selectedBus: SearchBusResult | null;
  onSelectBus: (bus: SearchBusResult) => void;
  connectionState?: RealtimeConnectionState;
}

export const MapContainer: FC<MapContainerProps> = ({
  buses: propBuses,
  stations,
  selectedBus: propSelectedBus,
  onSelectBus,
  connectionState: propConnectionState,
}) => {
  const [resetSignal, setResetSignal] = useState<number>(0);
  const busMarkerRefs = useRef<Record<string, L.Marker | null>>({});

  // Real-time telemetry: Use parent-managed stream if connectionState is provided,
  // or instantiate self-contained hook for standalone usage
  const internalRealtime = useBusRealtime(
    propConnectionState !== undefined ? undefined : (propSelectedBus?.bus_id || propSelectedBus?.bus_number || undefined),
    propConnectionState !== undefined ? [] : propBuses
  );

  const liveBuses = propConnectionState !== undefined ? propBuses : internalRealtime.liveBuses;
  const liveSelectedBus = propConnectionState !== undefined ? propSelectedBus : internalRealtime.liveSelectedBus;
  const connectionState = propConnectionState ?? internalRealtime.connectionState;

  // Strict Truthfulness: only show buses with actual valid coordinates
  const mappableBuses = useMemo(() => {
    return liveBuses.filter(
      (b) => b.current_lat != null && b.current_lng != null
    );
  }, [liveBuses]);

  // Geocoded stations with valid GeoJSON point coordinates
  const mappableStations = useMemo(() => {
    return stations.filter(
      (s) =>
        s.location &&
        Array.isArray(s.location.coordinates) &&
        s.location.coordinates.length >= 2 &&
        s.location.coordinates[0] != null &&
        s.location.coordinates[1] != null
    );
  }, [stations]);

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden flex flex-col h-[560px]">
      {/* Map Header Toolbar */}
      <div className="px-4 py-2.5 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-gray-600" />
          <span className="text-sm font-semibold text-gray-800">
            Belagavi Division Live Map
          </span>
          <span className="text-xs text-gray-500 hidden sm:inline">
            ({mappableBuses.length} active buses, {mappableStations.length} stations)
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Real-time WebSocket Status Badge */}
          {connectionState === 'connected' && (
            <Badge variant="success" size="sm" dot>
              WebSocket Live
            </Badge>
          )}
          {connectionState === 'reconnecting' && (
            <Badge variant="yellow" size="sm" dot>
              Reconnecting...
            </Badge>
          )}
          {connectionState === 'disconnected' && (
            <Badge variant="gray" size="sm" dot>
              Offline
            </Badge>
          )}

          {liveSelectedBus && (
            <Badge variant="blue" size="sm">
              Tracking: {liveSelectedBus.bus_number}
            </Badge>
          )}

          <button
            type="button"
            onClick={() => setResetSignal((s) => s + 1)}
            className="p-1.5 hover:bg-gray-200 text-gray-600 rounded border border-gray-300 bg-white"
            title="Reset to Division View"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Map Surface Viewport */}
      <div className="relative flex-1 bg-slate-100 overflow-hidden">
        <LeafletMap
          center={BELAGAVI_CBT_COORDS}
          zoom={10}
          scrollWheelZoom={true}
          className="w-full h-full z-0"
        >
          {/* Base OpenStreetMap Tiles with License Attribution */}
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            maxZoom={19}
          />

          {/* Controller for bound auto-fit, panning, and popup triggering */}
          <MapController
            buses={liveBuses}
            selectedBus={liveSelectedBus}
            busMarkerRefs={busMarkerRefs}
            resetSignal={resetSignal}
          />

          {/* Planned Highway Route Corridor for Selected Bus */}
          {liveSelectedBus &&
            liveSelectedBus.route_polyline &&
            Array.isArray(liveSelectedBus.route_polyline) &&
            liveSelectedBus.route_polyline.length > 1 && (
              <Polyline
                positions={liveSelectedBus.route_polyline}
                pathOptions={{
                  color: '#2563eb',
                  weight: 4,
                  opacity: 0.85,
                  dashArray: '6, 6',
                }}
              />
            )}

          {/* 2. Clustered Station Markers (~490 NWKRTC Geocoded Bus Stands) */}
          <MarkerClusterGroup
            chunkedLoading
            maxClusterRadius={50}
            showCoverageOnHover={false}
          >
            {mappableStations.map((station) => {
              const lat = station.location.coordinates[1];
              const lng = station.location.coordinates[0];
              return (
                <Marker
                  key={station.id}
                  position={[lat, lng]}
                  icon={createStationIcon()}
                >
                  <Popup>
                    <div className="text-xs space-y-1 p-0.5">
                      <div className="font-bold text-gray-900 flex items-center gap-1">
                        <MapPin className="w-3.5 h-3.5 text-gray-700" />
                        {station.name}
                      </div>
                      {station.platform_name && (
                        <div className="text-gray-600">
                          Platform: <span className="font-medium text-gray-800">{station.platform_name}</span>
                        </div>
                      )}
                      <div className="text-gray-500 text-[10px] font-mono">
                        {lat.toFixed(4)}°N, {lng.toFixed(4)}°E
                      </div>
                      <div className="pt-1 border-t border-gray-200 text-[10px] text-blue-700 font-semibold">
                        NWKRTC Belagavi Division
                      </div>
                    </div>
                  </Popup>
                </Marker>
              );
            })}
          </MarkerClusterGroup>

          {/* 3. Real Bus Telemetry Markers */}
          {mappableBuses.map((bus) => {
            const busKey = bus.bus_id || bus.bus_number;
            const isSelected = liveSelectedBus?.trip_id === bus.trip_id;
            const lat = bus.current_lat!;
            const lng = bus.current_lng!;

            return (
              <Marker
                key={bus.trip_id}
                position={[lat, lng]}
                icon={createBusIcon(bus, isSelected)}
                ref={(markerRef) => {
                  busMarkerRefs.current[busKey] = markerRef;
                }}
                eventHandlers={{
                  click: () => onSelectBus(bus),
                }}
              >
                <Popup>
                  <div className="text-xs space-y-1.5 min-w-[200px] p-0.5">
                    {/* Bus Header */}
                    <div className="flex items-center justify-between border-b border-gray-200 pb-1">
                      <span className="font-bold text-gray-900 font-mono text-sm">
                        {bus.bus_number}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-700 font-medium rounded">
                        {bus.service_type}
                      </span>
                    </div>

                    {/* Route Corridor */}
                    <div className="text-gray-700 font-medium">
                      {bus.source_station_name} &rarr; {bus.destination_station_name}
                    </div>

                    {/* Telemetry Status & Speed */}
                    <div className="grid grid-cols-2 gap-1.5 py-1 text-[11px] bg-gray-50 p-1.5 rounded">
                      <div className="flex items-center gap-1 text-gray-700">
                        <Gauge className="w-3.5 h-3.5 text-gray-500" />
                        <span>{bus.speed > 0 ? `${bus.speed} km/h` : 'At Bay'}</span>
                      </div>
                      <div className="flex items-center gap-1 text-gray-700">
                        <Clock className="w-3.5 h-3.5 text-gray-500" />
                        <span>{formatPingTime(bus.last_seen_at)}</span>
                      </div>
                    </div>

                    {/* Platform Status */}
                    <div className="flex items-center justify-between pt-0.5 text-[11px]">
                      <span className="text-gray-500">Status:</span>
                      {bus.is_stale ? (
                        <span className="font-semibold text-gray-500 flex items-center gap-1">
                          <ShieldAlert className="w-3 h-3 text-gray-400" /> Signal Stale
                        </span>
                      ) : bus.has_left_platform ? (
                        <span className="font-semibold text-red-600">Departed & Moving</span>
                      ) : (
                        <span className="font-semibold text-green-700">At Platform / Bay</span>
                      )}
                    </div>
                  </div>
                </Popup>
              </Marker>
            );
          })}
        </LeafletMap>

        {/* Legend */}
        <div className="absolute bottom-3 right-3 bg-white/95 border border-gray-200 rounded-md p-2.5 shadow-md text-xs space-y-1 z-[1000] pointer-events-auto backdrop-blur-xs">
          <div className="font-semibold text-gray-700 text-[11px] mb-1">Live Map Legend</div>
          <div className="flex items-center gap-1.5 text-gray-600">
            <span className="w-2.5 h-2.5 rounded-full bg-green-600" /> At Platform / Bay
          </div>
          <div className="flex items-center gap-1.5 text-gray-600">
            <span className="w-2.5 h-2.5 rounded-full bg-red-600" /> Departed & Moving
          </div>
          <div className="flex items-center gap-1.5 text-gray-600">
            <span className="w-2.5 h-2.5 rounded-full bg-slate-500" /> Stale Telemetry
          </div>
          <div className="flex items-center gap-1.5 text-gray-600">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-600 ring-2 ring-blue-300" /> Selected Bus
          </div>
          <div className="flex items-center gap-1.5 text-gray-600">
            <span className="w-2.5 h-2.5 rounded-full border-2 border-slate-700 bg-white" /> Station / Cluster
          </div>
        </div>
      </div>
    </div>
  );
};

export default MapContainer;

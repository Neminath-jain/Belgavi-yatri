import { useState, useEffect, useRef, useMemo } from 'react';
import type { SearchBusResult } from '../types/database';

export type TelemetryStatus = 'websocket' | 'polling' | 'disconnected';

interface WebSocketTelemetryPayload {
  bus_id?: string;
  bus_number?: string;
  latitude?: number;
  longitude?: number;
  speed?: number;
  has_left_platform?: boolean;
  updated_at?: string;
}

/**
 * Derives the appropriate WebSocket URL for bus telemetry streaming.
 * Points to FastAPI backend WebSocket endpoint: /ws/v1/buses/{bus_id}
 */
function resolveWebSocketUrl(busIdentifier: string): string {
  const apiBase = import.meta.env.VITE_API_BASE_URL || '';
  const cleanId = encodeURIComponent(busIdentifier);

  if (apiBase && apiBase.startsWith('http')) {
    const wsBase = apiBase.replace(/^http/, 'ws');
    return `${wsBase}/ws/v1/buses/${cleanId}`;
  }

  // If Vite dev server is on port 5173, point directly to FastAPI backend on 8000
  if (typeof window !== 'undefined' && window.location.port === '5173') {
    return `ws://${window.location.hostname}:8000/ws/v1/buses/${cleanId}`;
  }

  const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = typeof window !== 'undefined' ? window.location.host : 'localhost:8000';
  return `${protocol}//${host}/ws/v1/buses/${cleanId}`;
}

/**
 * useBusTelemetry Hook
 * 
 * Manages live GPS telemetry updates for active division buses.
 * Subscribes to the FastAPI WebSocket stream (/ws/v1/buses/{bus_id}) for real-time
 * telemetry frame updates. If the WebSocket connection cannot be established,
 * it seamlessly transitions to a fallback polling fetch.
 */
export function useBusTelemetry(
  initialBuses: SearchBusResult[],
  selectedBus: SearchBusResult | null
) {
  const [telemetryUpdates, setTelemetryUpdates] = useState<Record<string, Partial<SearchBusResult>>>({});
  const [telemetryStatus, setTelemetryStatus] = useState<TelemetryStatus>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);

  // Target identifier for telemetry subscription (bus_id or bus_number)
  const targetBusId = selectedBus?.bus_id || selectedBus?.bus_number || (initialBuses.length > 0 ? (initialBuses[0].bus_id || initialBuses[0].bus_number) : null);

  // Reset update cache when bus ID changes
  const prevTargetBusIdRef = useRef<string | null>(null);

  // WebSocket Subscription Lifecycle
  useEffect(() => {
    if (!targetBusId) {
      return;
    }
    if (prevTargetBusIdRef.current !== targetBusId) {
      prevTargetBusIdRef.current = targetBusId;
    }

    let isSubscribed = true;
    const wsUrl = resolveWebSocketUrl(targetBusId);

    const connectWebSocket = () => {
      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isSubscribed) {
            ws.close();
            return;
          }
          setTelemetryStatus('websocket');
        };

        ws.onmessage = (event) => {
          if (!isSubscribed) return;
          try {
            const frame: WebSocketTelemetryPayload = JSON.parse(event.data);
            const busKey = frame.bus_id || frame.bus_number;
            if (!busKey) return;

            setTelemetryUpdates((prev) => ({
              ...prev,
              [busKey]: {
                ...(prev[busKey] || {}),
                current_lat: frame.latitude ?? prev[busKey]?.current_lat,
                current_lng: frame.longitude ?? prev[busKey]?.current_lng,
                speed: frame.speed ?? prev[busKey]?.speed,
                has_left_platform: frame.has_left_platform ?? prev[busKey]?.has_left_platform,
                last_seen_at: frame.updated_at ?? new Date().toISOString(),
                is_stale: false,
              },
            }));
          } catch {
            // Non-JSON frame ignored
          }
        };

        ws.onerror = () => {
          if (isSubscribed) {
            // Fall back to polling if WebSocket stream fails
            setTelemetryStatus('polling');
          }
        };

        ws.onclose = () => {
          if (isSubscribed) {
            setTelemetryStatus('polling');
          }
        };
      } catch {
        if (isSubscribed) {
          setTelemetryStatus('polling');
        }
      }
    };

    connectWebSocket();

    return () => {
      isSubscribed = false;
      const ws = wsRef.current;
      if (ws) {
        ws.close();
        wsRef.current = null;
      }
    };
  }, [targetBusId]);

  // TODO: Fallback polling fetch when WebSocket connection is unavailable or connecting to Vite dev mock
  useEffect(() => {
    if (telemetryStatus !== 'polling') return;

    const intervalId = window.setInterval(async () => {
      try {
        const apiBase = import.meta.env.VITE_API_BASE_URL || '';
        const res = await fetch(`${apiBase}/api/v1/buses/search?limit=25`, {
          headers: { Accept: 'application/json' },
        });
        if (!res.ok) return;

        const data: SearchBusResult[] = await res.json();
        const updates: Record<string, Partial<SearchBusResult>> = {};

        data.forEach((b) => {
          const key = b.bus_id || b.bus_number;
          if (key && b.current_lat != null && b.current_lng != null) {
            updates[key] = {
              current_lat: b.current_lat,
              current_lng: b.current_lng,
              speed: b.speed,
              has_left_platform: b.has_left_platform,
              last_seen_at: b.last_seen_at,
              is_stale: b.is_stale,
            };
          }
        });

        setTelemetryUpdates((prev) => ({ ...prev, ...updates }));
      } catch {
        // Polling failure gracefully ignored until next interval
      }
    }, 6000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [telemetryStatus]);

  // Merge original bus objects with live telemetry updates
  const liveBuses = useMemo(() => {
    return initialBuses.map((bus) => {
      const key = bus.bus_id || bus.bus_number;
      const update = key ? telemetryUpdates[key] : undefined;
      if (!update) return bus;

      return {
        ...bus,
        ...update,
      };
    });
  }, [initialBuses, telemetryUpdates]);

  const liveSelectedBus = useMemo(() => {
    if (!selectedBus) return null;
    const key = selectedBus.bus_id || selectedBus.bus_number;
    const update = key ? telemetryUpdates[key] : undefined;
    if (!update) return selectedBus;

    return {
      ...selectedBus,
      ...update,
    };
  }, [selectedBus, telemetryUpdates]);

  return {
    liveBuses,
    liveSelectedBus,
    telemetryStatus,
  };
}

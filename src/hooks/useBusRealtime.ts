import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import type { BusSearchResponse } from '../types/database';

export type RealtimeConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected';

export interface LiveTelemetryFrame {
  bus_id?: string;
  bus_number?: string;
  lat?: number;
  lng?: number;
  latitude?: number;
  longitude?: number;
  speed?: number;
  has_left_platform?: boolean;
  updated_at?: string;
}

export interface LiveBusState {
  current_lat: number | null;
  current_lng: number | null;
  speed: number;
  has_left_platform: boolean;
  last_seen_at: string | null;
  is_stale: boolean;
}

/**
 * Resolves the FastAPI WebSocket URL.
 * Subscribes to per-bus route (/api/v1/ws/bus/{bus_id}) if busId is provided,
 * or division broadcast route (/api/v1/ws/division) for the default wide view.
 */
function resolveWebSocketUrl(busId?: string): string {
  const apiBase = import.meta.env.VITE_API_BASE_URL || '';
  const endpoint = busId && busId.trim()
    ? `/api/v1/ws/bus/${encodeURIComponent(busId.trim())}`
    : '/api/v1/ws/division';

  if (apiBase && apiBase.startsWith('http')) {
    const wsBase = apiBase.replace(/^http/, 'ws');
    return `${wsBase}${endpoint}`;
  }

  // Vite development mode without proxy -> direct to FastAPI backend port 8000
  if (typeof window !== 'undefined' && window.location.port === '5173') {
    return `ws://${window.location.hostname}:8000${endpoint}`;
  }

  const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = typeof window !== 'undefined' ? window.location.host : 'localhost:8000';
  return `${protocol}//${host}${endpoint}`;
}

/**
 * Custom React Hook: useBusRealtime
 * 
 * Streams live GPS telemetry over FastAPI WebSockets backed by Redis Pub/Sub:
 * - Subscribes to /api/v1/ws/bus/{bus_id} for a selected vehicle, or /api/v1/ws/division for fleet-wide.
 * - Smoothly interpolates coordinates over ~800ms using requestAnimationFrame.
 * - Flips platform exit status badges instantly when has_left_platform changes.
 * - Never fabricates positions or movement for buses without telemetry.
 * - Reconnects automatically with exponential backoff on connection loss.
 */
export function useBusRealtime(
  busId?: string,
  initialBuses: BusSearchResponse[] = []
) {
  const [telemetryUpdates, setTelemetryUpdates] = useState<Record<string, LiveBusState>>({});
  const [connectionState, setConnectionState] = useState<RealtimeConnectionState>('connecting');
  const [lastPing, setLastPing] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const retryCountRef = useRef<number>(0);
  const animFramesRef = useRef<Record<string, number>>({});
  const latestCoordsRef = useRef<Record<string, { lat: number; lng: number }>>({});

  // Cancel any ongoing coordinate interpolation frames
  const cancelAllAnimations = useCallback(() => {
    Object.values(animFramesRef.current).forEach((id) => cancelAnimationFrame(id));
    animFramesRef.current = {};
  }, []);

  // Smooth position interpolation over ~800ms (ease-out quadratic)
  const interpolatePosition = useCallback((
    busKey: string,
    startLat: number,
    startLng: number,
    targetLat: number,
    targetLng: number
  ) => {
    // If coordinate change is negligible, skip animation loop
    if (Math.abs(targetLat - startLat) < 0.00001 && Math.abs(targetLng - startLng) < 0.00001) {
      setTelemetryUpdates((prev) => ({
        ...prev,
        [busKey]: {
          ...(prev[busKey] || {}),
          current_lat: targetLat,
          current_lng: targetLng,
        } as LiveBusState,
      }));
      latestCoordsRef.current[busKey] = { lat: targetLat, lng: targetLng };
      return;
    }

    if (animFramesRef.current[busKey]) {
      cancelAnimationFrame(animFramesRef.current[busKey]);
    }

    const startTime = performance.now();
    const duration = 800; // 800ms smooth transition window

    const step = (currentTime: number) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out quadratic: fast start, soft deceleration
      const ease = progress * (2 - progress);

      const currentLat = startLat + (targetLat - startLat) * ease;
      const currentLng = startLng + (targetLng - startLng) * ease;

      latestCoordsRef.current[busKey] = { lat: currentLat, lng: currentLng };

      setTelemetryUpdates((prev) => ({
        ...prev,
        [busKey]: {
          ...(prev[busKey] || {}),
          current_lat: currentLat,
          current_lng: currentLng,
        } as LiveBusState,
      }));

      if (progress < 1) {
        animFramesRef.current[busKey] = requestAnimationFrame(step);
      } else {
        delete animFramesRef.current[busKey];
      }
    };

    animFramesRef.current[busKey] = requestAnimationFrame(step);
  }, []);

  // Process incoming telemetry frame
  const handleIncomingFrame = useCallback((frame: LiveTelemetryFrame) => {
    const busKey = frame.bus_id || frame.bus_number;
    if (!busKey) return;

    const targetLat = frame.lat ?? frame.latitude;
    const targetLng = frame.lng ?? frame.longitude;
    const speed = frame.speed ?? 0;
    const hasLeftPlatform = frame.has_left_platform ?? false;
    const updatedAt = frame.updated_at ?? new Date().toISOString();

    setLastPing(updatedAt);

    // Instant status and speed update
    setTelemetryUpdates((prev) => {
      const currentEntry = prev[busKey];
      return {
        ...prev,
        [busKey]: {
          current_lat: currentEntry?.current_lat ?? targetLat ?? null,
          current_lng: currentEntry?.current_lng ?? targetLng ?? null,
          speed: speed,
          has_left_platform: hasLeftPlatform,
          last_seen_at: updatedAt,
          is_stale: false,
        },
      };
    });

    // If valid coordinates are provided, interpolate position smoothly
    if (targetLat != null && targetLng != null) {
      const prevCoords = latestCoordsRef.current[busKey];
      if (prevCoords && prevCoords.lat != null && prevCoords.lng != null) {
        interpolatePosition(busKey, prevCoords.lat, prevCoords.lng, targetLat, targetLng);
      } else {
        latestCoordsRef.current[busKey] = { lat: targetLat, lng: targetLng };
        setTelemetryUpdates((prev) => ({
          ...prev,
          [busKey]: {
            ...(prev[busKey] || {}),
            current_lat: targetLat,
            current_lng: targetLng,
            is_stale: false,
          } as LiveBusState,
        }));
      }
    }
  }, [interpolatePosition]);

  // Main WebSocket Connection Lifecycle with Exponential Backoff
  useEffect(() => {
    let isCancelled = false;
    const url = resolveWebSocketUrl(busId);

    const connect = () => {
      if (isCancelled) return;

      try {
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          if (isCancelled) {
            ws.close();
            return;
          }
          retryCountRef.current = 0;
          setConnectionState('connected');
        };

        ws.onmessage = (event) => {
          if (isCancelled) return;
          try {
            const frame: LiveTelemetryFrame = JSON.parse(event.data);
            handleIncomingFrame(frame);
          } catch {
            // Ignore non-JSON frames
          }
        };

        ws.onerror = () => {
          if (!isCancelled) {
            setConnectionState('reconnecting');
          }
        };

        ws.onclose = () => {
          if (isCancelled) return;
          setConnectionState('reconnecting');

          // Exponential backoff reconnect: 1s, 1.5s, 2.25s, max 10s + jitter
          const attempt = retryCountRef.current;
          const delay = Math.min(1000 * Math.pow(1.5, attempt), 10000) + Math.random() * 300;
          retryCountRef.current = attempt + 1;

          reconnectTimerRef.current = window.setTimeout(() => {
            if (!isCancelled) {
              connect();
            }
          }, delay);
        };
      } catch {
        if (!isCancelled) {
          setConnectionState('reconnecting');
        }
      }
    };

    connect();

    return () => {
      isCancelled = true;
      cancelAllAnimations();

      const ws = wsRef.current;
      if (ws) {
        ws.close();
        wsRef.current = null;
      }

      const timerId = reconnectTimerRef.current;
      if (timerId) {
        window.clearTimeout(timerId);
        reconnectTimerRef.current = null;
      }
    };
  }, [busId, handleIncomingFrame, cancelAllAnimations]);

  // Merge initial bus search response with live telemetry states
  const liveBuses = useMemo(() => {
    return initialBuses.map((bus) => {
      const key = bus.bus_id || bus.bus_number;
      const live = key ? telemetryUpdates[key] : undefined;
      if (!live) return bus;

      return {
        ...bus,
        current_lat: live.current_lat ?? bus.current_lat,
        current_lng: live.current_lng ?? bus.current_lng,
        speed: live.speed ?? bus.speed,
        has_left_platform: live.has_left_platform ?? bus.has_left_platform,
        last_seen_at: live.last_seen_at ?? bus.last_seen_at,
        is_stale: live.is_stale ?? bus.is_stale,
      };
    });
  }, [initialBuses, telemetryUpdates]);

  const liveSelectedBus = useMemo(() => {
    if (!busId) return null;
    return liveBuses.find((b) => b.bus_id === busId || b.bus_number === busId) || null;
  }, [liveBuses, busId]);

  return {
    liveBuses,
    liveSelectedBus,
    connectionState,
    isConnected: connectionState === 'connected',
    lastPing,
    telemetryUpdates,
  };
}

export default useBusRealtime;

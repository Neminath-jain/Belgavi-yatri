import { useState, useEffect, useRef, type FC } from 'react';
import {
  Radio,
  X,
  Navigation,
  CheckCircle,
  AlertTriangle,
  Bus as BusIcon,
  ShieldCheck,
  StopCircle,
  Activity,
} from 'lucide-react';
import { Button } from './ui/Button';
import { Badge } from './ui/Badge';
import { getAnonymousDeviceId, sendTelemetryPing } from '../services/api';
import type { SearchBusResult } from '../types/database';

export interface ShareLiveLocationModalProps {
  isOpen: boolean;
  onClose: () => void;
  preselectedBus?: SearchBusResult | null;
  availableBuses?: SearchBusResult[];
  onBroadcastSuccess?: (busNumber: string, coords: { lat: number; lng: number }) => void;
}

export const ShareLiveLocationModal: FC<ShareLiveLocationModalProps> = ({
  isOpen,
  onClose,
  preselectedBus = null,
  availableBuses = [],
  onBroadcastSuccess,
}) => {
  const [busNumber, setBusNumber] = useState<string>('');
  const [serviceType, setServiceType] = useState<string>('Ordinary');
  const [tripId, setTripId] = useState<string | null>(null);

  const [isBroadcasting, setIsBroadcasting] = useState<boolean>(false);
  const [currentCoords, setCurrentCoords] = useState<{
    latitude: number;
    longitude: number;
    accuracy?: number;
    speed?: number;
  } | null>(null);

  const [pingCount, setPingCount] = useState<number>(0);
  const [lastPingTime, setLastPingTime] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const watchIdRef = useRef<number | null>(null);
  const intervalRef = useRef<number | null>(null);
  const anonDeviceId = getAnonymousDeviceId();

  // Populate when preselected bus changes or modal opens
  useEffect(() => {
    if (preselectedBus) {
      setBusNumber(preselectedBus.bus_number || '');
      setServiceType(preselectedBus.service_type || 'Ordinary');
      setTripId(preselectedBus.trip_id || null);
    } else if (availableBuses.length > 0 && !busNumber) {
      setBusNumber(availableBuses[0].bus_number);
      setServiceType(availableBuses[0].service_type || 'Ordinary');
      setTripId(availableBuses[0].trip_id || null);
    }
  }, [preselectedBus, availableBuses]);

  // Clean up geolocation on unmount
  useEffect(() => {
    return () => {
      stopBroadcasting();
    };
  }, []);

  const stopBroadcasting = () => {
    if (watchIdRef.current !== null && typeof navigator !== 'undefined' && navigator.geolocation) {
      navigator.geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setIsBroadcasting(false);
  };

  const handleStartBroadcasting = () => {
    setErrorMsg(null);
    setSuccessMsg(null);

    const cleanBusNum = busNumber.trim().toUpperCase();
    if (!cleanBusNum) {
      setErrorMsg('Please specify a valid vehicle registration number (e.g. KA-22-F-1892).');
      return;
    }

    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setErrorMsg('Geolocation is not supported by your browser or environment.');
      return;
    }

    setIsBroadcasting(true);
    setPingCount(0);

    const dispatchPing = async (pos: GeolocationPosition) => {
      const lat = pos.coords.latitude;
      const lng = pos.coords.longitude;
      // Convert speed from m/s to km/h if available, default to reasonable moving speed or 0
      const rawSpeed = pos.coords.speed;
      const speedKmh = rawSpeed != null && rawSpeed > 0 ? rawSpeed * 3.6 : 28.5;

      setCurrentCoords({
        latitude: lat,
        longitude: lng,
        accuracy: pos.coords.accuracy,
        speed: speedKmh,
      });

      try {
        await sendTelemetryPing({
          bus_number: cleanBusNum,
          latitude: lat,
          longitude: lng,
          speed: Math.round(speedKmh * 10) / 10,
          service_type: serviceType,
          trip_id: tripId,
          client_session_id: anonDeviceId,
        });

        setPingCount((prev) => prev + 1);
        setLastPingTime(new Date().toLocaleTimeString());
        setSuccessMsg(`Live ping broadcasted successfully for ${cleanBusNum}`);
        onBroadcastSuccess?.(cleanBusNum, { lat, lng });
      } catch (err: any) {
        setErrorMsg(err.message || 'Failed to dispatch telemetry ping to server.');
      }
    };

    // 1. Initial immediate position query
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        dispatchPing(pos);
      },
      (err) => {
        setErrorMsg(`Location access denied or failed: ${err.message}`);
        stopBroadcasting();
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );

    // 2. High-precision live watcher
    try {
      const watchId = navigator.geolocation.watchPosition(
        (pos) => {
          dispatchPing(pos);
        },
        (err) => {
          console.warn('Geolocation watch error:', err);
        },
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 3000 }
      );
      watchIdRef.current = watchId;
    } catch {
      // Fallback timer if watchPosition is unsupported
      const timer = window.setInterval(() => {
        navigator.geolocation.getCurrentPosition(
          (pos) => dispatchPing(pos),
          () => {},
          { enableHighAccuracy: true, timeout: 5000 }
        );
      }, 4000);
      intervalRef.current = timer;
    }
  };

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-location-title"
      className="fixed inset-0 z-50 overflow-y-auto bg-black/50 backdrop-blur-xs flex items-center justify-center p-4"
    >
      <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full overflow-hidden border border-gray-200 animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="bg-blue-600 text-white px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-500/80 flex items-center justify-center text-white">
              <Radio className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <h2 id="share-location-title" className="text-base font-bold text-white">
                Share Live Bus Location
              </h2>
              <p className="text-xs text-blue-100">
                Frictionless Crowdsourced GPS • Zero Login Required
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-white/80 hover:text-white p-1 rounded-md transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4 text-sm text-gray-700">
          {/* Frictionless Privacy Notice */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-blue-900 flex items-start gap-2.5">
            <ShieldCheck className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold">100% Anonymous & Open:</span>
              <p className="text-blue-800 mt-0.5 leading-relaxed">
                You do not need an account, password, OTP, phone number, or email. Pings are tagged
                solely with an anonymous ephemeral device UUID (
                <span className="font-mono font-medium">{anonDeviceId.slice(0, 13)}...</span>) stored
                in this session to prevent spoofing.
              </p>
            </div>
          </div>

          {/* Form Fields */}
          <div className="space-y-3">
            <div>
              <label htmlFor="share-bus-input" className="block text-xs font-semibold text-gray-700 mb-1">
                Vehicle Registration / Bus Number
              </label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-gray-400">
                    <BusIcon className="w-4 h-4" />
                  </div>
                  <input
                    id="share-bus-input"
                    type="text"
                    value={busNumber}
                    disabled={isBroadcasting}
                    onChange={(e) => setBusNumber(e.target.value.toUpperCase())}
                    placeholder="e.g. KA-22-F-1892"
                    className="w-full pl-9 pr-3 py-2 text-sm font-mono font-bold uppercase rounded-md border border-gray-300 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100"
                  />
                </div>

                {availableBuses.length > 0 && !isBroadcasting && (
                  <select
                    title="Select an active bus from current search"
                    value={busNumber}
                    onChange={(e) => {
                      const selected = availableBuses.find((b) => b.bus_number === e.target.value);
                      if (selected) {
                        setBusNumber(selected.bus_number);
                        setServiceType(selected.service_type || 'Ordinary');
                        setTripId(selected.trip_id || null);
                      }
                    }}
                    className="text-xs border border-gray-300 rounded-md px-2 py-2 bg-gray-50 text-gray-700 cursor-pointer"
                  >
                    <option value="">Select active bus...</option>
                    {availableBuses.map((b) => (
                      <option key={b.trip_id} value={b.bus_number}>
                        {b.bus_number} ({b.service_type})
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>

            <div>
              <label htmlFor="share-service-type" className="block text-xs font-semibold text-gray-700 mb-1">
                Service Classification
              </label>
              <select
                id="share-service-type"
                value={serviceType}
                disabled={isBroadcasting}
                onChange={(e) => setServiceType(e.target.value)}
                className="w-full text-xs border border-gray-300 rounded-md px-3 py-2 bg-white text-gray-800 disabled:bg-gray-100"
              >
                <option value="Ordinary">Ordinary / City Service</option>
                <option value="Vegadhoot">Vegadhoot Express</option>
                <option value="Rajahamsa">Rajahamsa Deluxe</option>
                <option value="Airavat Club Class">Airavat Club Class (Multi-Axle)</option>
              </select>
            </div>
          </div>

          {/* Live Broadcasting Status Panel */}
          {isBroadcasting && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="relative flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-green-600" />
                  </span>
                  <span className="text-xs font-bold text-green-900 uppercase tracking-wide">
                    Live Broadcast Active
                  </span>
                </div>
                <Badge variant="success" size="sm">
                  Ping #{pingCount}
                </Badge>
              </div>

              {currentCoords && (
                <div className="grid grid-cols-2 gap-2 text-xs text-green-950 bg-white/70 rounded p-2 border border-green-100 font-mono">
                  <div>
                    <span className="text-gray-500">Lat:</span> {currentCoords.latitude.toFixed(5)}
                  </div>
                  <div>
                    <span className="text-gray-500">Lng:</span> {currentCoords.longitude.toFixed(5)}
                  </div>
                  <div>
                    <span className="text-gray-500">Speed:</span> {currentCoords.speed?.toFixed(1) || '0'} km/h
                  </div>
                  <div>
                    <span className="text-gray-500">Accuracy:</span> ±{Math.round(currentCoords.accuracy || 0)}m
                  </div>
                </div>
              )}

              {lastPingTime && (
                <div className="text-[11px] text-green-700 flex items-center justify-between">
                  <span>Last broadcast ping:</span>
                  <span className="font-semibold">{lastPingTime}</span>
                </div>
              )}
            </div>
          )}

          {/* Feedback messages */}
          {errorMsg && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-800 flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}

          {successMsg && !errorMsg && !isBroadcasting && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-xs text-green-800 flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
              <span>{successMsg}</span>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="bg-gray-50 border-t border-gray-200 px-6 py-3.5 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <Activity className="w-3.5 h-3.5 text-gray-400" />
            <span>Anonymous crowdsource stream</span>
          </div>

          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose} className="text-xs">
              Close
            </Button>

            {isBroadcasting ? (
              <Button
                variant="danger"
                size="sm"
                leftIcon={<StopCircle className="w-4 h-4" />}
                onClick={stopBroadcasting}
                className="text-xs font-semibold"
              >
                Stop Sharing
              </Button>
            ) : (
              <Button
                variant="primary"
                size="sm"
                leftIcon={<Navigation className="w-4 h-4" />}
                onClick={handleStartBroadcasting}
                className="text-xs font-semibold"
              >
                Start Broadcasting
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default ShareLiveLocationModal;

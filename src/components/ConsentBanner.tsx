import { useState, useEffect, type FC } from 'react';
import { ShieldCheck, X, AlertCircle } from 'lucide-react';
import { recordConsent, getRiderUserId } from '../services/api';

export interface ConsentBannerProps {
  /**
   * Purpose requesting affirmative consent (e.g. 'sms_alerts', 'saved_routes', 'email_alerts').
   * If null or undefined, the banner is NOT shown — preserving complete anonymity for the
   * public bus search & tracking flows.
   */
  pendingPurpose?: string | null;
  purposeTitle?: string | null;
  purposeDescription?: string | null;
  onAllow?: (purpose: string) => void;
  onDecline?: () => void;
  onManagePreferences?: () => void;
}

const DEFAULT_PURPOSE_DESCRIPTIONS: Record<string, { title: string; desc: string }> = {
  sms_alerts: {
    title: 'SMS & WhatsApp Platform Departure Alerts',
    desc: "We'll text you automated updates when your selected bus departs the source terminal platform or approaches your boarding bay. Your mobile number is encrypted at rest and never used for marketing.",
  },
  saved_routes: {
    title: 'Saved Favorite Routes & Sync',
    desc: 'Save your preferred origin and destination station pairs to easily access them on future visits. Preferences are tied solely to your pseudonymous device ID.',
  },
  email_alerts: {
    title: 'Email Transit Bulletins',
    desc: "We'll email you scheduled departure updates, seasonal festival special timings, and route advisory bulletins for your preferred travel corridors.",
  },
};

export const ConsentBanner: FC<ConsentBannerProps> = ({
  pendingPurpose = null,
  purposeTitle = null,
  purposeDescription = null,
  onAllow,
  onDecline,
  onManagePreferences,
}) => {
  // Listen for global custom event 'request-dpdp-consent' if triggered by cards or buttons
  const [eventPurpose, setEventPurpose] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const activePurpose = dismissed ? null : (pendingPurpose || eventPurpose);

  useEffect(() => {
    const handleConsentEvent = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail && detail.purpose) {
        setEventPurpose(detail.purpose);
        setDismissed(false);
      }
    };

    window.addEventListener('request-dpdp-consent', handleConsentEvent);
    return () => {
      window.removeEventListener('request-dpdp-consent', handleConsentEvent);
    };
  }, []);

  // Shown ONLY when a user opts to use a personal feature (SMS alerts, saved routes).
  // Returns null on the anonymous bus-search/tracking flow.
  if (!activePurpose) {
    return null;
  }

  const defaultMeta = DEFAULT_PURPOSE_DESCRIPTIONS[activePurpose] || {
    title: 'Optional Personal Feature',
    desc: "To use this feature, we need your consent to process your contact details for this specific purpose under India's DPDP Act, 2023.",
  };

  const title = purposeTitle || defaultMeta.title;
  const description = purposeDescription || defaultMeta.desc;

  const handleAllow = async () => {
    if (!activePurpose) return;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const riderId = getRiderUserId();
      await recordConsent(riderId, activePurpose);
      const allowedPurpose = activePurpose;
      setEventPurpose(null);
      setDismissed(true);
      onAllow?.(allowedPurpose);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to record consent. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDecline = () => {
    setEventPurpose(null);
    setDismissed(true);
    setErrorMessage(null);
    onDecline?.();
  };

  return (
    <div
      role="region"
      aria-label="Privacy Consent Notice"
      className="bg-white border-b-2 border-blue-600 shadow-sm text-gray-900 px-4 py-3 text-xs"
    >
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-start md:items-center justify-between gap-3">
        {/* Left: Icon & Purpose Description */}
        <div className="flex items-start gap-2.5 max-w-3xl">
          <ShieldCheck className="w-5 h-5 text-blue-600 shrink-0 mt-0.5" />
          <div className="space-y-0.5">
            <div className="font-bold text-gray-900 text-sm flex items-center gap-2">
              <span>{title}</span>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-blue-700 bg-blue-50 border border-blue-200 px-1.5 py-0.5 rounded">
                DPDP Act 2023 Notice
              </span>
            </div>
            <p className="text-gray-600 leading-relaxed text-xs">
              {description}
            </p>
            {errorMessage && (
              <div className="text-red-600 flex items-center gap-1 font-medium pt-1">
                <AlertCircle className="w-3.5 h-3.5" />
                <span>{errorMessage}</span>
              </div>
            )}
          </div>
        </div>

        {/* Right: Plain Allow (Solid Blue) & Decline (Outline/Ghost) Buttons */}
        <div className="flex items-center gap-2 shrink-0 self-end md:self-center">
          {onManagePreferences && (
            <button
              type="button"
              onClick={onManagePreferences}
              className="text-gray-600 hover:text-gray-900 underline text-xs mr-1 cursor-pointer"
            >
              Preferences
            </button>
          )}

          {/* Plain Outline / Ghost Button for Decline */}
          <button
            type="button"
            onClick={handleDecline}
            disabled={isSubmitting}
            className="bg-white hover:bg-gray-100 text-gray-700 font-medium px-3.5 py-1.5 rounded-md text-xs border border-gray-300 transition-colors cursor-pointer disabled:opacity-50"
          >
            Decline
          </button>

          {/* Plain Solid Blue Button for Allow */}
          <button
            type="button"
            onClick={handleAllow}
            disabled={isSubmitting}
            className="bg-blue-600 hover:bg-blue-700 text-white font-medium px-4 py-1.5 rounded-md text-xs border border-transparent transition-colors shadow-xs cursor-pointer disabled:opacity-50"
          >
            {isSubmitting ? 'Recording...' : 'Allow'}
          </button>

          <button
            type="button"
            onClick={handleDecline}
            className="text-gray-400 hover:text-gray-600 p-1 cursor-pointer ml-1"
            title="Dismiss Notice"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConsentBanner;

import { useState, useEffect, useCallback, type FC } from 'react';
import {
  X,
  Shield,
  Download,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Mail,
  Smartphone,
  Bookmark,
  RefreshCw,
  Building2,
} from 'lucide-react';
import { Badge } from './ui/Badge';
import {
  fetchConsentNotices,
  fetchConsentStatus,
  recordConsent,
  withdrawConsent,
  fetchMyData,
  deleteMyData,
  fetchGrievanceOfficer,
  getRiderUserId,
  type GrievanceOfficerInfo,
} from '../services/api';
import type { ConsentNoticeItem } from '../types/database';

export interface PrivacyCenterProps {
  isOpen: boolean;
  onClose: () => void;
}

export const PrivacyCenter: FC<PrivacyCenterProps> = ({ isOpen, onClose }) => {
  const [notices, setNotices] = useState<ConsentNoticeItem[]>([]);
  const [activeConsents, setActiveConsents] = useState<Set<string>>(new Set());
  const [grievanceOfficer, setGrievanceOfficer] = useState<GrievanceOfficerInfo | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<{ text: string; type: 'success' | 'info' | 'error' } | null>(null);
  const [riderId, setRiderId] = useState<string>(() => (typeof window !== 'undefined' ? getRiderUserId() : ''));

  // Confirmation modal state for account deletion
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [isDownloading, setIsDownloading] = useState<boolean>(false);

  const loadData = useCallback(async (uid: string) => {
    try {
      const [noticeList, status, officer] = await Promise.all([
        fetchConsentNotices().catch(() => []),
        fetchConsentStatus(uid).catch(() => ({ user_id: uid, active_consents: [], withdrawn_consents: [], notices: [] })),
        fetchGrievanceOfficer().catch(() => null),
      ]);

      if (noticeList.length > 0) {
        setNotices(noticeList);
      } else {
        // Fallback notices compliant with DPDP Section 5
        setNotices([
          {
            purpose: 'sms_alerts',
            title: 'SMS & WhatsApp Platform Departure Alerts',
            personal_data_collected: ['Mobile Phone Number (+91 format)'],
            specific_purpose:
              'We collect your mobile phone number solely to send automated real-time SMS alerts when your selected bus departs the source terminal platform.',
            withdrawal_info:
              'You may withdraw consent at any time. Upon withdrawal, SMS dispatch halts immediately, and your phone number is erased.',
            notice_version: 'DPDP-2025-v1.0',
            data_fiduciary: 'North Western Karnataka Road Transport Corporation (NWKRTC)',
            grievance_contact: 'grievance.privacy@nwkrtc-belagavi.in',
          },
          {
            purpose: 'saved_routes',
            title: 'Saved Favorite Routes & Sync',
            personal_data_collected: ['Origin Station', 'Destination Station'],
            specific_purpose:
              'We associate your saved station pairs with your pseudonymous rider device ID to persist frequent corridors.',
            withdrawal_info:
              'You may withdraw consent at any time. Withdrawing consent purges saved routes without affecting anonymous tracking.',
            notice_version: 'DPDP-2025-v1.0',
            data_fiduciary: 'North Western Karnataka Road Transport Corporation (NWKRTC)',
            grievance_contact: 'grievance.privacy@nwkrtc-belagavi.in',
          },
          {
            purpose: 'email_alerts',
            title: 'Email Transit Bulletins',
            personal_data_collected: ['Email Address'],
            specific_purpose:
              'We collect your email address solely to deliver scheduled departure updates and delay advisories.',
            withdrawal_info:
              'You may withdraw consent at any time. Upon withdrawal, all email processing halts immediately.',
            notice_version: 'DPDP-2025-v1.0',
            data_fiduciary: 'North Western Karnataka Road Transport Corporation (NWKRTC)',
            grievance_contact: 'grievance.privacy@nwkrtc-belagavi.in',
          },
        ]);
      }

      setActiveConsents(new Set(status.active_consents || []));

      if (officer) {
        setGrievanceOfficer(officer);
      } else {
        setGrievanceOfficer({
          data_fiduciary: 'North Western Karnataka Road Transport Corporation (NWKRTC) — Belagavi Division',
          officer_name: 'Data Protection & Grievance Redressal Officer',
          email: 'grievance.privacy@nwkrtc-belagavi.in',
          address: 'Division Control Office, Belagavi Central Bus Terminal (CBT), Fort Road, Belagavi, Karnataka 590016',
          phone: '+91 831 242 1234',
          turnaround_days: 30,
          dpdp_rules_version: 'DPDP Rules 2025',
        });
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen || (typeof window !== 'undefined' && window.location.pathname === '/privacy-center')) {
      const uid = getRiderUserId();
      loadData(uid);
    }
  }, [isOpen, loadData]);

  // Toggle consent for a specific purpose
  const handleToggleConsent = async (purpose: string) => {
    const isCurrentlyActive = activeConsents.has(purpose);
    setActionLoading(purpose);
    setStatusMessage(null);

    try {
      if (isCurrentlyActive) {
        // Withdraw consent (DELETE /api/v1/consent/{purpose})
        const res = await withdrawConsent(riderId, purpose);
        setActiveConsents((prev) => {
          const next = new Set(prev);
          next.delete(purpose);
          return next;
        });
        setStatusMessage({
          text: `Consent withdrawn under DPDP Section 6(4). ${res.message || 'Processing halted.'}`,
          type: 'info',
        });
      } else {
        // Opt in (POST /api/v1/consent)
        await recordConsent(riderId, purpose);
        setActiveConsents((prev) => new Set([...prev, purpose]));
        setStatusMessage({
          text: `Affirmative consent recorded under DPDP Section 6 for '${purpose}'.`,
          type: 'success',
        });
      }
    } catch (err: any) {
      setStatusMessage({
        text: err.message || 'Failed to update consent preference.',
        type: 'error',
      });
    } finally {
      setActionLoading(null);
    }
  };

  // Download personal data export (GET /api/v1/user/my-data)
  const handleDownloadMyData = async () => {
    setIsDownloading(true);
    setStatusMessage(null);

    try {
      const data = await fetchMyData(riderId);
      const jsonStr = JSON.stringify(data, null, 2);
      const blob = new Blob([jsonStr], { type: 'application/json' });
      const url = URL.createObjectURL(blob);

      const a = document.createElement('a');
      a.href = url;
      a.download = `nwkrtc_privacy_data_export_${riderId.slice(0, 8)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      setStatusMessage({
        text: 'Personal data export downloaded successfully under DPDP Section 11 (Right to Access).',
        type: 'success',
      });
    } catch (err: any) {
      setStatusMessage({
        text: err.message || 'Failed to download personal data.',
        type: 'error',
      });
    } finally {
      setIsDownloading(false);
    }
  };

  // Delete account & erase all personal data (DELETE /api/v1/user/my-data)
  const handleConfirmDelete = async () => {
    setIsDeleting(true);
    setStatusMessage(null);

    try {
      const res = await deleteMyData(riderId);
      setActiveConsents(new Set());
      setShowDeleteModal(false);

      // Reset anonymous device ID in local storage
      localStorage.removeItem('nwkrtc_dpdp_rider_id');
      const newId = getRiderUserId();
      setRiderId(newId);

      setStatusMessage({
        text: `${res.message || 'Account deleted.'} All personal identifiers, consents, and saved routes have been erased under DPDP Section 12.`,
        type: 'success',
      });
    } catch (err: any) {
      setStatusMessage({
        text: err.message || 'Failed to erase account data.',
        type: 'error',
      });
    } finally {
      setIsDeleting(false);
    }
  };

  if (!isOpen) return null;

  const getPurposeIcon = (purpose: string) => {
    switch (purpose) {
      case 'sms_alerts':
        return <Smartphone className="w-4 h-4 text-blue-600" />;
      case 'email_alerts':
        return <Mail className="w-4 h-4 text-gray-600" />;
      case 'saved_routes':
        return <Bookmark className="w-4 h-4 text-blue-700" />;
      default:
        return <Shield className="w-4 h-4 text-gray-600" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white border border-gray-200 rounded-lg shadow-lg max-w-2xl w-full overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-5 py-3.5 border-b border-gray-200 bg-gray-50 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <Shield className="w-5 h-5 text-blue-600" />
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-gray-900">
                  Privacy Center & Consent
                </h2>
                <Badge variant="blue" size="sm">
                  DPDP Act 2023
                </Badge>
              </div>
              <p className="text-xs text-gray-500 mt-0.5">
                Manage your optional personal data features, data access, and erasure rights.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 p-1.5 rounded hover:bg-gray-100 cursor-pointer"
            title="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable Content Body */}
        <div className="p-5 overflow-y-auto space-y-5 text-xs text-gray-800">
          {/* Status Message Notification */}
          {statusMessage && (
            <div
              className={`p-3 rounded-md border flex items-start gap-2 ${
                statusMessage.type === 'success'
                  ? 'bg-green-50 border-green-200 text-green-800'
                  : statusMessage.type === 'error'
                  ? 'bg-red-50 border-red-200 text-red-800'
                  : 'bg-blue-50 border-blue-200 text-blue-800'
              }`}
            >
              {statusMessage.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
              ) : statusMessage.type === 'error' ? (
                <AlertCircle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
              ) : (
                <Shield className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
              )}
              <div className="flex-1 font-medium">{statusMessage.text}</div>
            </div>
          )}

          {/* Rider Pseudonymous Identity Notice */}
          <div className="bg-gray-50 border border-gray-200 rounded-md p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <div className="text-[11px] font-semibold uppercase text-gray-500">
                Pseudonymous Rider Identifier
              </div>
              <div className="font-mono text-xs text-gray-900 mt-0.5 break-all">
                {riderId || 'Initializing...'}
              </div>
              <p className="text-[11px] text-gray-500 mt-1">
                You are completely anonymous by default. Live bus searching and tracking store zero personal data.
              </p>
            </div>
            <span className="self-start sm:self-auto text-[11px] font-medium bg-white text-gray-700 border border-gray-300 px-2 py-0.5 rounded">
              Anonymous Session
            </span>
          </div>

          {/* Section 1: Granular, Unbundled Consent Toggles */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-gray-900 uppercase tracking-wide">
                Optional Features & Consents
              </h3>
              <span className="text-[11px] text-gray-500">
                Section 6 • Unbundled & Granular
              </span>
            </div>

            {loading ? (
              <div className="p-8 text-center text-gray-400 flex flex-col items-center justify-center gap-2">
                <RefreshCw className="w-5 h-5 animate-spin text-blue-600" />
                <span>Loading privacy preferences...</span>
              </div>
            ) : (
              <div className="space-y-3">
                {notices.map((notice) => {
                  const isActive = activeConsents.has(notice.purpose);
                  const isProcessing = actionLoading === notice.purpose;

                  return (
                    <div
                      key={notice.purpose}
                      className="border border-gray-200 rounded-md p-3.5 bg-white space-y-2.5"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-2.5">
                          <div className="p-1.5 bg-gray-100 rounded text-gray-700 mt-0.5">
                            {getPurposeIcon(notice.purpose)}
                          </div>
                          <div>
                            <div className="font-semibold text-gray-900 text-xs">
                              {notice.title}
                            </div>
                            <p className="text-gray-600 text-xs mt-0.5 leading-relaxed">
                              {notice.specific_purpose}
                            </p>
                          </div>
                        </div>

                        {/* Plain Toggle Switch / Action Button */}
                        <div className="shrink-0 flex items-center gap-2">
                          <span
                            className={`text-[11px] font-semibold px-2 py-0.5 rounded border ${
                              isActive
                                ? 'bg-green-50 border-green-300 text-green-700'
                                : 'bg-gray-100 border-gray-300 text-gray-600'
                            }`}
                          >
                            {isActive ? 'Consent Active' : 'Not Opted In'}
                          </span>

                          <button
                            type="button"
                            disabled={isProcessing}
                            onClick={() => handleToggleConsent(notice.purpose)}
                            className={`px-3 py-1 text-xs font-medium rounded border cursor-pointer transition-colors ${
                              isActive
                                ? 'bg-white hover:bg-gray-100 text-red-600 border-red-200'
                                : 'bg-blue-600 hover:bg-blue-700 text-white border-transparent'
                            } disabled:opacity-50`}
                          >
                            {isProcessing
                              ? 'Saving...'
                              : isActive
                              ? 'Withdraw'
                              : 'Opt In'}
                          </button>
                        </div>
                      </div>

                      {/* Withdrawal Notice & Collected Attributes */}
                      <div className="pt-2 border-t border-gray-100 flex flex-wrap items-center justify-between text-[11px] text-gray-500 gap-1">
                        <span>
                          <strong>Data collected:</strong> {notice.personal_data_collected.join(', ')}
                        </span>
                        <span className="text-gray-400">
                          Notice: {notice.notice_version}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Section 2: Data Principal Rights (Download My Data & Delete Account) */}
          <div className="space-y-3 pt-2 border-t border-gray-200">
            <h3 className="text-sm font-bold text-gray-900 uppercase tracking-wide">
              Your Data Principal Rights (DPDP Act 2023)
            </h3>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Right to Access / Download My Data */}
              <div className="border border-gray-200 rounded-md p-3.5 bg-gray-50 flex flex-col justify-between space-y-2">
                <div>
                  <div className="font-semibold text-gray-900 flex items-center gap-1.5">
                    <Download className="w-4 h-4 text-blue-600" />
                    Download My Data
                  </div>
                  <p className="text-gray-500 text-[11px] mt-1 leading-relaxed">
                    Under Section 11 (Right to Access), obtain a complete JSON export of all your stored personal details, active alerts, and consent records.
                  </p>
                </div>
                <button
                  type="button"
                  disabled={isDownloading}
                  onClick={handleDownloadMyData}
                  className="bg-white hover:bg-gray-100 text-gray-800 font-medium px-3 py-1.5 rounded border border-gray-300 text-xs self-start cursor-pointer disabled:opacity-50"
                >
                  {isDownloading ? 'Exporting...' : 'Download JSON Export'}
                </button>
              </div>

              {/* Right to Erasure / Delete Account */}
              <div className="border border-red-200 rounded-md p-3.5 bg-red-50/40 flex flex-col justify-between space-y-2">
                <div>
                  <div className="font-semibold text-red-900 flex items-center gap-1.5">
                    <Trash2 className="w-4 h-4 text-red-600" />
                    Delete My Account
                  </div>
                  <p className="text-red-700 text-[11px] mt-1 leading-relaxed">
                    Under Section 12 (Right to Erasure), permanently delete your account, purge stored phone/email, and erase all consent logs.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowDeleteModal(true)}
                  className="bg-red-600 hover:bg-red-700 text-white font-medium px-3 py-1.5 rounded border border-transparent text-xs self-start cursor-pointer"
                >
                  Delete Account & Data
                </button>
              </div>
            </div>
          </div>

          {/* Section 3: Grievance Redressal Officer Contact Details */}
          {grievanceOfficer && (
            <div className="space-y-2 pt-2 border-t border-gray-200">
              <h3 className="text-sm font-bold text-gray-900 uppercase tracking-wide">
                Grievance Redressal Officer (Section 13)
              </h3>
              <div className="border border-gray-200 rounded-md p-3.5 bg-gray-50 space-y-2 text-xs">
                <div className="flex items-center gap-2">
                  <Building2 className="w-4 h-4 text-gray-600 shrink-0" />
                  <span className="font-semibold text-gray-900">
                    {grievanceOfficer.data_fiduciary}
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-gray-600 pt-1">
                  <div>
                    <span className="text-gray-400 block text-[11px]">Designation:</span>
                    <span className="font-medium text-gray-800">{grievanceOfficer.officer_name}</span>
                  </div>
                  <div>
                    <span className="text-gray-400 block text-[11px]">Official Email:</span>
                    <a
                      href={`mailto:${grievanceOfficer.email}`}
                      className="text-blue-600 hover:underline font-mono"
                    >
                      {grievanceOfficer.email}
                    </a>
                  </div>
                  <div>
                    <span className="text-gray-400 block text-[11px]">Statutory Turnaround:</span>
                    <span>Within {grievanceOfficer.turnaround_days} days ({grievanceOfficer.dpdp_rules_version})</span>
                  </div>
                  <div>
                    <span className="text-gray-400 block text-[11px]">Postal Address:</span>
                    <span className="text-gray-700">{grievanceOfficer.address}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-200 bg-gray-50 flex items-center justify-between text-xs text-gray-500 shrink-0">
          <div>
            DPDP Rules 2025 • Section 5, 6, 11, 12, 13
          </div>
          <button
            type="button"
            onClick={onClose}
            className="bg-white hover:bg-gray-100 text-gray-700 font-medium px-4 py-1.5 rounded border border-gray-300 cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>

      {/* Plain Confirmation Modal for Delete Account (No Fancy Transitions) */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/60">
          <div className="bg-white border border-gray-300 rounded-lg shadow-xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-start gap-3">
              <div className="p-2 bg-red-100 text-red-700 rounded-md shrink-0">
                <AlertCircle className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-gray-900">
                  Permanently Delete Account & Personal Data?
                </h4>
                <p className="text-xs text-gray-600 mt-1 leading-relaxed">
                  Under DPDP Section 12 (Right to Erasure), this will permanently erase your phone number, email, saved route preferences, and withdraw all active consents immediately. This action cannot be undone.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-200">
              <button
                type="button"
                disabled={isDeleting}
                onClick={() => setShowDeleteModal(false)}
                className="bg-white hover:bg-gray-100 text-gray-700 font-medium px-3.5 py-1.5 rounded border border-gray-300 text-xs cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isDeleting}
                onClick={handleConfirmDelete}
                className="bg-red-600 hover:bg-red-700 text-white font-medium px-4 py-1.5 rounded border border-transparent text-xs cursor-pointer disabled:opacity-50"
              >
                {isDeleting ? 'Erasing...' : 'Yes, Delete Account'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PrivacyCenter;

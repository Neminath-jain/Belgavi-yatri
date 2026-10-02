"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — DPDP Act 2023 Notice Registry
===============================================================================
Author: Senior Privacy & Data Protection Compliance Engineer
Compliance Target:
  - Digital Personal Data Protection Act, 2023 (DPDP Act) — Section 5 & 6
  - Digital Personal Data Protection Rules, 2025
Scope:
  Applies STRICTLY to rider-facing features collecting personal data (SMS alerts,
  email notifications, saved favorite routes). Non-personal transit telemetry
  and public schedules are exempt from personal data processing requirements.
===============================================================================
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

CURRENT_NOTICE_VERSION = "DPDP-2025-v1.0"
DATA_PROTECTION_OFFICER_EMAIL = "grievance.privacy@nwkrtc-belagavi.in"
DATA_FIDUCIARY_NAME = "North Western Karnataka Road Transport Corporation (NWKRTC) — Belagavi Division"


class PlainLanguageNotice(BaseModel):
    """
    Standardized, plain-language disclosure presented to riders prior to seeking
    consent for any optional personal-data-backed transit feature.
    """
    purpose: str = Field(..., description="Machine-readable purpose identifier")
    title: str = Field(..., description="Human-readable title")
    personal_data_collected: List[str] = Field(..., description="Explicit list of personal data items collected")
    specific_purpose: str = Field(..., description="Concrete, granular purpose of processing")
    withdrawal_info: str = Field(..., description="Plain-language instructions on how consent can be withdrawn")
    notice_version: str = Field(default=CURRENT_NOTICE_VERSION, description="Version tag of this notice")
    data_fiduciary: str = Field(default=DATA_FIDUCIARY_NAME, description="Legal entity processing the data")
    grievance_contact: str = Field(default=DATA_PROTECTION_OFFICER_EMAIL, description="Official grievance redressal contact")


# =============================================================================
# Granular, Unbundled Notice Registry
# =============================================================================
DPDP_NOTICE_REGISTRY: Dict[str, PlainLanguageNotice] = {
    "sms_alerts": PlainLanguageNotice(
        purpose="sms_alerts",
        title="SMS & WhatsApp Platform Departure Alerts",
        personal_data_collected=["Mobile Phone Number (+91 format)"],
        specific_purpose=(
            "We collect your mobile phone number solely to send automated real-time SMS or "
            "WhatsApp alerts when your selected bus departs the source terminal platform or "
            "crosses within 5 km of your boarding station. Your number is encrypted at rest "
            "and will never be shared with third parties or used for marketing."
        ),
        withdrawal_info=(
            "You may withdraw your consent at any time through the Privacy Center in the app "
            "or by deleting the alert. Upon withdrawal, SMS dispatch stops immediately, and your "
            "phone number is permanently erased from active alert queues."
        ),
    ),
    "email_alerts": PlainLanguageNotice(
        purpose="email_alerts",
        title="Email Transit Bulletins & Schedule Advisory Alerts",
        personal_data_collected=["Email Address"],
        specific_purpose=(
            "We collect your email address solely to deliver scheduled departure updates, delay "
            "advisories, and festival special service announcements for your preferred corridors. "
            "Your email address is encrypted at rest."
        ),
        withdrawal_info=(
            "You may withdraw your consent at any time via the Privacy Center or by clicking the "
            "unsubscribe link in any email. Processing and delivery cease immediately upon withdrawal."
        ),
    ),
    "saved_routes": PlainLanguageNotice(
        purpose="saved_routes",
        title="Saved Favorite Routes & Cross-Device Sync",
        personal_data_collected=["Account Identifier", "Origin Station", "Destination Station"],
        specific_purpose=(
            "We associate your saved station pairs with your pseudonymous rider account identifier "
            "to persist your frequent travel corridors across devices and browser sessions."
        ),
        withdrawal_info=(
            "You may withdraw consent at any time in the Privacy Center. Withdrawing consent "
            "immediately purges your saved route preferences from cloud storage without affecting "
            "your ability to search buses anonymously."
        ),
    ),
}


def get_plain_language_notice(purpose: str) -> Optional[PlainLanguageNotice]:
    """Retrieves the official plain-language notice for a given purpose."""
    return DPDP_NOTICE_REGISTRY.get(purpose)


def get_all_notices() -> List[PlainLanguageNotice]:
    """Returns all registered plain-language notices for optional transit features."""
    return list(DPDP_NOTICE_REGISTRY.values())

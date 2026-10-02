"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — Inactive Retention Cleanup Job
===============================================================================
Author: Senior Security & Compliance Engineer
Compliance Target:
  - Digital Personal Data Protection Act, 2023 (DPDP Act) — Section 8(7)
  - DPDP Rules, 2025: Storage Limitation Principle
Purpose:
  Scheduled maintenance job to automatically purge or anonymize user accounts,
  contact data, and saved route preferences inactive beyond retention period
  (default 730 days / 24 months).
===============================================================================
"""

import argparse
import logging
import sys

from .config import DPDP_RETENTION_PERIOD_DAYS
from .database import SessionLocal
from .dpdp_service import execute_retention_policy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [DPDP-RETENTION] %(message)s",
)
logger = logging.getLogger("dpdp_retention_job")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="NWKRTC Belagavi Tracker DPDP Inactive Account Retention Job"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DPDP_RETENTION_PERIOD_DAYS,
        help=f"Retention period in days (default: {DPDP_RETENTION_PERIOD_DAYS})",
    )
    args = parser.parse_args()

    logger.info(
        "Starting DPDP retention cleanup. Window: %d days (cutoff: %d days prior)",
        args.days,
        args.days,
    )

    db = SessionLocal()
    try:
        result = execute_retention_policy(
            db=db,
            retention_days=args.days,
            actor_id="cron-retention-worker",
        )
        logger.info(
            "DPDP Retention Cleanup Complete: %d inactive principals purged. Status: %s",
            result["principals_purged"],
            result["status"],
        )
        return 0
    except Exception as e:
        logger.error("Retention job failed: %s", e, exc_info=True)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

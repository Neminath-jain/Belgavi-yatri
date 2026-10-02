"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — DPDP Act 2023 Compliance Tests
===============================================================================
Author: Senior Privacy & Data Protection Compliance Engineer
Compliance Target:
  - Digital Personal Data Protection Act, 2023 (DPDP Act) — Sections 5, 6, 8
  - Digital Personal Data Protection Rules, 2025
Test Suite:
  1. Plain-Language Notice Inspection (Section 5)
  2. Unbundled Consent Intake & Audit Trail (Section 6)
  3. Strict Consent Gate Enforcement (Section 6)
  4. Immediate Consent Withdrawal & Cessation Cascade (Section 8)
  5. Cryptographic Field-Level PII Encryption at Rest (Section 8)
===============================================================================
"""

from datetime import datetime, timezone
import sqlite3
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from geoalchemy2 import Geometry
from geoalchemy2.admin.dialects import sqlite as gsqlite
import fakeredis.aioredis as fake_aio
import shapely.wkt
import shapely.wkb

from backend.config import RedisKeys
from backend.database import Base, get_db
from backend.dpdp_notices import (
    CURRENT_NOTICE_VERSION,
    DATA_PROTECTION_OFFICER_EMAIL,
    DATA_FIDUCIARY_NAME,
    DPDP_NOTICE_REGISTRY,
    get_all_notices,
    get_plain_language_notice,
)
from backend.dpdp_service import (
    decrypt_pii,
    encrypt_pii,
    enforce_consent_gate,
    has_active_consent,
    record_user_consent,
    withdraw_user_consent,
)
from backend.main import app
from backend.models import ConsentRecord, SavedRoute, Station, User
from backend.redis_client import get_redis_dependency

# -----------------------------------------------------------------------------
# SQLite SpatiaLite Simulation for Standalone Testing
# -----------------------------------------------------------------------------
gsqlite.after_create = lambda *a, **k: None
gsqlite.before_create = lambda *a, **k: None


@compiles(Geometry, "sqlite")
def compile_geom_sqlite(type_, compiler, **kw):
    return "TEXT"


def _sqlite_to_ewkb(val):
    if not val:
        return None
    if isinstance(val, bytes):
        return val if len(val) > 0 else None
    val_str = str(val)
    if "POINT" in val_str:
        wkt = val_str.split(";")[-1]
        geom = shapely.wkt.loads(wkt)
        return shapely.wkb.dumps(geom)
    return str(val).encode("utf-8")


class TestDPDPCompliance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def setup_sqlite_spatial_functions(conn, rec):
            if isinstance(conn, sqlite3.Connection):
                conn.create_function("GeomFromEWKT", 1, lambda v: v)
                conn.create_function("ST_GeomFromEWKT", 1, lambda v: v)
                conn.create_function("AsEWKB", 1, _sqlite_to_ewkb)
                conn.create_function("AsBinary", 1, _sqlite_to_ewkb)

        Base.metadata.create_all(cls.engine)
        cls.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=cls.engine
        )

    def setUp(self):
        self.db = self.TestingSessionLocal()
        # Clean tables
        self.db.query(SavedRoute).delete()
        self.db.query(ConsentRecord).delete()
        self.db.query(User).delete()
        self.db.query(Station).delete()
        self.db.commit()

        # Isolated fakeredis instance
        self.fake_redis = fake_aio.FakeRedis(decode_responses=True)

        # Overrides
        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        async def override_get_redis():
            return self.fake_redis

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_redis_dependency] = override_get_redis

        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.clear()

    # =========================================================================
    # 1. Plain-Language Notice Requirements (DPDP Section 5)
    # =========================================================================
    def test_plain_language_notices_api(self):
        """GET /api/v1/consent/notices must return unbundled notices with all mandatory fields."""
        response = self.client.get("/api/v1/consent/notices")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 3)

        purposes = {item["purpose"] for item in data}
        self.assertIn("sms_alerts", purposes)
        self.assertIn("email_alerts", purposes)
        self.assertIn("saved_routes", purposes)

        for item in data:
            self.assertEqual(item["notice_version"], CURRENT_NOTICE_VERSION)
            self.assertEqual(item["data_fiduciary"], DATA_FIDUCIARY_NAME)
            self.assertEqual(item["grievance_contact"], DATA_PROTECTION_OFFICER_EMAIL)
            self.assertIsInstance(item["personal_data_collected"], list)
            self.assertGreater(len(item["personal_data_collected"]), 0)
            self.assertTrue(len(item["specific_purpose"]) > 20)
            self.assertTrue(len(item["withdrawal_info"]) > 20)

    # =========================================================================
    # 2. Unbundled Consent Intake & Status (DPDP Section 6)
    # =========================================================================
    def test_unbundled_consent_intake(self):
        """Opting into SMS alerts must not bundle or activate saved routes or email alerts."""
        user_id = str(uuid.uuid4())

        # Step 1: Record consent ONLY for sms_alerts
        payload = {
            "user_id": user_id,
            "purpose": "sms_alerts",
            "notice_version": CURRENT_NOTICE_VERSION,
        }
        res = self.client.post("/api/v1/consent", json=payload)
        self.assertIn(res.status_code, [200, 201])
        body = res.json()
        self.assertEqual(body["user_id"], user_id)
        self.assertEqual(body["purpose"], "sms_alerts")
        self.assertTrue(body["is_active"])
        self.assertIsNone(body["consent_withdrawn_at"])

        # Step 2: Query consent overview to verify unbundling
        status_res = self.client.get(f"/api/v1/consent/status?user_id={user_id}")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["active_consents"], ["sms_alerts"])
        self.assertNotIn("saved_routes", status_data["active_consents"])
        self.assertNotIn("email_alerts", status_data["active_consents"])

        # Step 3: Verify idempotency — re-posting the same purpose returns active record
        res_dup = self.client.post("/api/v1/consent", json=payload)
        self.assertIn(res_dup.status_code, [200, 201])
        self.assertEqual(res_dup.json()["id"], body["id"])

    def test_reject_unregistered_purpose(self):
        """Attempting to consent to an unlisted purpose must be rejected with HTTP 400."""
        payload = {
            "user_id": str(uuid.uuid4()),
            "purpose": "unauthorized_tracking",
        }
        res = self.client.post("/api/v1/consent", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid purpose", res.json()["detail"])

    # =========================================================================
    # 3. Strict Consent Gate Enforcement (DPDP Section 6)
    # =========================================================================
    def test_consent_gate_blocks_alert_registration_without_consent(self):
        """Registering an alert without active consent MUST return HTTP 403 Forbidden."""
        user_id = str(uuid.uuid4())
        trip_id = str(uuid.uuid4())
        payload = {
            "user_id": user_id,
            "trip_id": trip_id,
            "purpose": "sms_alerts",
            "phone_number": "+919876543210",
        }

        # Attempt to register alert before giving consent
        res = self.client.post("/api/v1/users/register-alert", json=payload)
        self.assertEqual(res.status_code, 403)
        self.assertIn("DPDP Act 2023 Compliance Violation", res.json()["detail"])

        # Verify NO phone number was written to database
        db_user = self.db.query(User).filter(User.id == uuid.UUID(user_id)).first()
        if db_user:
            self.assertIsNone(db_user.phone_number_encrypted)

    def test_alert_registration_succeeds_with_prior_consent(self):
        """Registering an alert with active consent succeeds and encrypts phone number."""
        user_id = str(uuid.uuid4())

        # Give affirmative consent for sms_alerts
        self.client.post(
            "/api/v1/consent",
            json={"user_id": user_id, "purpose": "sms_alerts"},
        )

        # Register alert
        phone = "+919876543210"
        trip_id = str(uuid.uuid4())
        payload = {
            "user_id": user_id,
            "trip_id": trip_id,
            "purpose": "sms_alerts",
            "phone_number": phone,
        }
        res = self.client.post("/api/v1/users/register-alert", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "subscribed")
        self.assertEqual(data["purpose"], "sms_alerts")
        self.assertEqual(data["user_id"], user_id)

        # Verify PII is encrypted at rest in PostgreSQL/SQLite BYTEA
        db_user = self.db.query(User).filter(User.id == uuid.UUID(user_id)).first()
        self.assertIsNotNone(db_user)
        self.assertIsNotNone(db_user.phone_number_encrypted)
        # Ensure raw phone number is NOT stored in plain text
        self.assertNotIn(phone.encode("utf-8"), db_user.phone_number_encrypted)
        # Ensure decryption recovers the original phone number
        decrypted = decrypt_pii(db_user.phone_number_encrypted)
        self.assertEqual(decrypted, phone)

    def test_saved_routes_consent_gate(self):
        """Saving routes without 'saved_routes' consent must return HTTP 403."""
        user_id = str(uuid.uuid4())
        src_id = str(uuid.uuid4())
        dst_id = str(uuid.uuid4())
        payload = {
            "user_id": user_id,
            "source_station_id": src_id,
            "destination_station_id": dst_id,
            "alert_enabled": False,
        }

        # Attempt without consent
        res = self.client.post("/api/v1/users/saved-routes", json=payload)
        self.assertEqual(res.status_code, 403)
        self.assertIn("saved_routes", res.json()["detail"])

        # Opt in to saved_routes
        self.client.post(
            "/api/v1/consent",
            json={"user_id": user_id, "purpose": "saved_routes"},
        )

        # Now saving route succeeds
        res_ok = self.client.post("/api/v1/users/saved-routes", json=payload)
        self.assertEqual(res_ok.status_code, 201)
        self.assertEqual(res_ok.json()["source_station_id"], src_id)

    # =========================================================================
    # 4. Immediate Consent Withdrawal & Cessation (DPDP Section 8)
    # =========================================================================
    def test_immediate_consent_withdrawal_cascade(self):
        """
        Withdrawing SMS consent must:
        1. Populate consent_withdrawn_at on consent record.
        2. Immediately purge encrypted phone number.
        3. Turn off alert_enabled on any saved routes.
        4. Cause subsequent alert attempts to return 403.
        """
        user_id = str(uuid.uuid4())
        trip_id = str(uuid.uuid4())
        src_id = str(uuid.uuid4())
        dst_id = str(uuid.uuid4())

        # Opt in to sms_alerts and register alert
        self.client.post(
            "/api/v1/consent",
            json={"user_id": user_id, "purpose": "sms_alerts"},
        )
        self.client.post(
            "/api/v1/users/register-alert",
            json={
                "user_id": user_id,
                "trip_id": trip_id,
                "purpose": "sms_alerts",
                "phone_number": "+919999988888",
            },
        )

        # Also opt in to saved routes and save a route with alert_enabled=True
        self.client.post(
            "/api/v1/consent",
            json={"user_id": user_id, "purpose": "saved_routes"},
        )
        self.client.post(
            "/api/v1/users/saved-routes",
            json={
                "user_id": user_id,
                "source_station_id": src_id,
                "destination_station_id": dst_id,
                "alert_enabled": True,
            },
        )

        # Verify initial state
        db_user = self.db.query(User).filter(User.id == uuid.UUID(user_id)).first()
        self.assertIsNotNone(db_user.phone_number_encrypted)
        saved_route = self.db.query(SavedRoute).filter(SavedRoute.user_id == uuid.UUID(user_id)).first()
        self.assertTrue(saved_route.alert_enabled)

        # Withdraw SMS consent
        del_res = self.client.delete(f"/api/v1/consent/sms_alerts?user_id={user_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["consent_withdrawn"])

        # Check DB cessation effects
        self.db.refresh(db_user)
        self.assertIsNone(db_user.phone_number_encrypted, "Phone number must be purged on consent withdrawal")
        self.db.refresh(saved_route)
        self.assertFalse(saved_route.alert_enabled, "Alerts must be disabled on consent withdrawal")

        # Consent record audit
        record = self.db.query(ConsentRecord).filter(
            ConsentRecord.user_id == uuid.UUID(user_id),
            ConsentRecord.purpose == "sms_alerts",
        ).first()
        self.assertIsNotNone(record.consent_withdrawn_at)

        # Subsequent alert registration attempt must be blocked with HTTP 403
        blocked_res = self.client.post(
            "/api/v1/users/register-alert",
            json={
                "user_id": user_id,
                "trip_id": trip_id,
                "purpose": "sms_alerts",
                "phone_number": "+919999988888",
            },
        )
        self.assertEqual(blocked_res.status_code, 403)

    def test_saved_routes_withdrawal_purges_routes(self):
        """Withdrawing saved_routes consent purges synchronized routes from storage."""
        user_id = str(uuid.uuid4())
        src_id = str(uuid.uuid4())
        dst_id = str(uuid.uuid4())

        self.client.post(
            "/api/v1/consent",
            json={"user_id": user_id, "purpose": "saved_routes"},
        )
        self.client.post(
            "/api/v1/users/saved-routes",
            json={
                "user_id": user_id,
                "source_station_id": src_id,
                "destination_station_id": dst_id,
                "alert_enabled": False,
            },
        )

        routes_count = self.db.query(SavedRoute).filter(SavedRoute.user_id == uuid.UUID(user_id)).count()
        self.assertEqual(routes_count, 1)

        # Withdraw saved_routes
        res = self.client.delete(f"/api/v1/consent/saved_routes?user_id={user_id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["consent_withdrawn"])

        # Verify routes were purged
        routes_count_after = self.db.query(SavedRoute).filter(SavedRoute.user_id == uuid.UUID(user_id)).count()
        self.assertEqual(routes_count_after, 0)

    # =========================================================================
    # 5. Cryptographic Field-Level PII Protection (DPDP Section 8)
    # =========================================================================
    def test_pii_encryption_and_decryption(self):
        """Tests field-level encryption/decryption functions directly."""
        plain_phone = "+91-98450-12345"
        plain_email = "passenger.belagavi@example.com"

        enc_phone = encrypt_pii(plain_phone)
        enc_email = encrypt_pii(plain_email)

        self.assertNotEqual(enc_phone, plain_phone.encode("utf-8"))
        self.assertNotEqual(enc_email, plain_email.encode("utf-8"))

        self.assertEqual(decrypt_pii(enc_phone), plain_phone)
        self.assertEqual(decrypt_pii(enc_email), plain_email)

        # Empty / None handling
        self.assertEqual(encrypt_pii(""), b"")
        self.assertEqual(decrypt_pii(b""), "")


if __name__ == "__main__":
    unittest.main()

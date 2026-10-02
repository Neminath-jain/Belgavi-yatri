"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — DPDP Security Safeguards Tests
===============================================================================
Author: Senior Security & Compliance Engineer
Compliance Target:
  - Digital Personal Data Protection Act, 2023 (DPDP Act) — Section 8
  - DPDP Rules, 2025: Reasonable Security Safeguards & Storage Limitation
Test Suite:
  1. Authenticated AES-256-GCM Encryption at Rest & Tampering Detection
  2. TLS Transport Security Headers (HSTS, nosniff, DENY)
  3. Role-Based Access Control (RBAC: Admin vs Service Account vs Anonymous)
  4. Append-Only Personal Data Audit Trail Verification
  5. Security Breach Notification & Incident Logging (Section 8(6))
  6. Storage Limitation & Inactive Account Retention Engine (Section 8(7))
===============================================================================
"""

import base64
from datetime import datetime, timezone, timedelta
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

from backend.config import (
    ADMIN_API_KEY,
    SERVICE_ACCOUNT_API_KEY,
    DPDP_RETENTION_PERIOD_DAYS,
)
from backend.database import Base, get_db
from backend.dpdp_service import (
    decrypt_pii,
    decrypt_rider_contact,
    encrypt_pii,
    execute_retention_policy,
    has_active_consent,
    log_personal_data_access,
    record_security_incident,
    record_user_consent,
)
from backend.main import app
from backend.models import (
    ConsentRecord,
    PersonalDataAuditLog,
    SavedRoute,
    SecurityIncident,
    Station,
    User,
)
from backend.redis_client import get_redis_dependency
from backend.security import Role

# -----------------------------------------------------------------------------
# SQLite Simulation
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


class TestDPDPSecuritySafeguards(unittest.TestCase):
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
        # Clean test tables
        self.db.query(SecurityIncident).delete()
        self.db.query(PersonalDataAuditLog).delete()
        self.db.query(SavedRoute).delete()
        self.db.query(ConsentRecord).delete()
        self.db.query(User).delete()
        self.db.commit()

        self.fake_redis = fake_aio.FakeRedis(decode_responses=True)

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
    # 1. Authenticated AES-256-GCM Encryption Tests (Section 8)
    # =========================================================================
    def test_aes_256_gcm_probabilistic_encryption(self):
        """Encrypting the same plaintext twice yields distinct ciphertexts (random 96-bit nonce)."""
        plaintext = "+919845012345"
        ct1 = encrypt_pii(plaintext)
        ct2 = encrypt_pii(plaintext)

        self.assertNotEqual(ct1, ct2, "AES-256-GCM must use random nonces, preventing deterministic ciphertext analysis")

        # Decrypt both
        self.assertEqual(decrypt_pii(ct1), plaintext)
        self.assertEqual(decrypt_pii(ct2), plaintext)

    def test_aes_256_gcm_tamper_detection(self):
        """Altering a single byte of ciphertext fails authentication tag verification."""
        plaintext = "passenger@nwkrtc-belagavi.in"
        encrypted_b64 = encrypt_pii(plaintext)
        raw = bytearray(base64.b64decode(encrypted_b64))

        # Tamper with the last byte (authentication tag byte)
        raw[-1] ^= 0xFF
        tampered_b64 = base64.b64encode(bytes(raw))

        # Decryption of tampered ciphertext must fail safely (return empty string)
        decrypted = decrypt_pii(tampered_b64)
        self.assertEqual(decrypted, "", "Tampered ciphertext must fail authentication and return empty string")

    def test_legacy_format_backward_compatibility(self):
        """Legacy XOR-HMAC ciphertexts decrypt cleanly alongside AES-256-GCM."""
        plaintext = "+918888877777"
        # Simulate legacy ciphertext (no 'v2:' prefix)
        from backend.config import DPDP_PII_SECRET
        import hashlib
        key = hashlib.sha256(DPDP_PII_SECRET).digest()
        raw_legacy = bytes(b ^ key[i % len(key)] for i, b in enumerate(plaintext.encode("utf-8")))
        legacy_b64 = base64.b64encode(raw_legacy)

        self.assertEqual(decrypt_pii(legacy_b64), plaintext)

    # =========================================================================
    # 2. TLS Transport Security & HTTP Headers
    # =========================================================================
    def test_security_headers_injected(self):
        """All responses must include defense-in-depth security headers (HSTS, nosniff, DENY)."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)

        self.assertIn("strict-transport-security", res.headers)
        self.assertIn("max-age=63072000", res.headers["strict-transport-security"])
        self.assertEqual(res.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(res.headers.get("x-frame-options"), "DENY")
        self.assertIn("strict-origin-when-cross-origin", res.headers.get("referrer-policy", ""))

    # =========================================================================
    # 3. Role-Based Access Control (RBAC) & Decryption Isolation
    # =========================================================================
    def test_anonymous_cannot_decrypt_personal_data(self):
        """Anonymous callers attempting to decrypt personal data are rejected with HTTP 403."""
        user_id = str(uuid.uuid4())
        # First grant consent and register alert
        self.client.post("/api/v1/consent", json={"user_id": user_id, "purpose": "sms_alerts"})
        self.client.post(
            "/api/v1/users/register-alert",
            json={
                "user_id": user_id,
                "trip_id": str(uuid.uuid4()),
                "purpose": "sms_alerts",
                "phone_number": "+919876543210",
            },
        )

        # Anonymous caller attempts to decrypt
        res = self.client.post(
            "/api/v1/internal/dispatch/decrypt-contact",
            json={"user_id": user_id, "purpose": "sms_alerts"},
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access Denied", res.json()["detail"])

    def test_invalid_bearer_token_rejected_401(self):
        """Invalid credentials yield HTTP 401 Unauthorized."""
        res = self.client.post(
            "/api/v1/internal/dispatch/decrypt-contact",
            headers={"Authorization": "Bearer forged-token-xyz"},
            json={"user_id": str(uuid.uuid4()), "purpose": "sms_alerts"},
        )
        self.assertEqual(res.status_code, 401)

    def test_service_account_can_decrypt_with_active_consent(self):
        """Authenticated service account can decrypt contact details for active dispatch."""
        user_id = str(uuid.uuid4())
        phone = "+919876543210"

        # Opt in and register
        self.client.post("/api/v1/consent", json={"user_id": user_id, "purpose": "sms_alerts"})
        self.client.post(
            "/api/v1/users/register-alert",
            json={
                "user_id": user_id,
                "trip_id": str(uuid.uuid4()),
                "purpose": "sms_alerts",
                "phone_number": phone,
            },
        )

        # Service account decrypts using X-Service-Key
        res = self.client.post(
            "/api/v1/internal/dispatch/decrypt-contact",
            headers={"X-Service-Key": SERVICE_ACCOUNT_API_KEY},
            json={"user_id": user_id, "purpose": "sms_alerts"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["decrypted_value"], phone)
        self.assertEqual(data["status"], "decrypted")

    def test_admin_only_endpoints_block_service_account(self):
        """Audit logs endpoint is restricted strictly to Admin; Service Account is forbidden."""
        # Service account attempts to read audit logs
        res = self.client.get(
            "/api/v1/security/audit-logs",
            headers={"X-Service-Key": SERVICE_ACCOUNT_API_KEY},
        )
        self.assertEqual(res.status_code, 403)

        # Admin reads audit logs successfully
        res_admin = self.client.get(
            "/api/v1/security/audit-logs",
            headers={"X-Admin-Key": ADMIN_API_KEY},
        )
        self.assertEqual(res_admin.status_code, 200)
        self.assertIsInstance(res_admin.json(), list)

    # =========================================================================
    # 4. Append-Only Audit Logging
    # =========================================================================
    def test_audit_logs_record_personal_data_operations(self):
        """Consent intake, alert registration, and consent withdrawal record audit trail entries."""
        user_id = str(uuid.uuid4())

        # 1. Record consent
        self.client.post("/api/v1/consent", json={"user_id": user_id, "purpose": "sms_alerts"})

        # 2. Register alert
        self.client.post(
            "/api/v1/users/register-alert",
            json={
                "user_id": user_id,
                "trip_id": str(uuid.uuid4()),
                "purpose": "sms_alerts",
                "phone_number": "+919999900000",
            },
        )

        # 3. Withdraw consent
        self.client.delete(f"/api/v1/consent/sms_alerts?user_id={user_id}")

        # Query audit log as admin
        res = self.client.get(
            f"/api/v1/security/audit-logs?user_id={user_id}",
            headers={"X-Admin-Key": ADMIN_API_KEY},
        )
        self.assertEqual(res.status_code, 200)
        logs = res.json()

        actions = [item["action"] for item in logs]
        self.assertIn("INSERT", actions)
        self.assertIn("UPDATE", actions)
        self.assertIn("WITHDRAW_CONSENT", actions)

    # =========================================================================
    # 5. Security Breach Notification & Incident Logging (Section 8(6))
    # =========================================================================
    def test_unauthorized_decrypt_triggers_security_incident(self):
        """Unauthorized attempts to decrypt personal data automatically log a security incident."""
        user_id = str(uuid.uuid4())
        # Opt in and register alert
        self.client.post("/api/v1/consent", json={"user_id": user_id, "purpose": "sms_alerts"})
        self.client.post(
            "/api/v1/users/register-alert",
            json={
                "user_id": user_id,
                "trip_id": str(uuid.uuid4()),
                "purpose": "sms_alerts",
                "phone_number": "+919876543210",
            },
        )

        # Unauthorized caller attempts to decrypt directly via helper
        try:
            decrypt_rider_contact(
                db=self.db,
                user_id=user_id,
                purpose="sms_alerts",
                caller_role="anonymous",
                actor_id="rogue-client",
                ip_address="198.51.100.1",
            )
        except Exception:
            pass

        # Check incident logs
        incident = self.db.query(SecurityIncident).first()
        self.assertIsNotNone(incident)
        self.assertEqual(incident.incident_type, "unauthorized_decrypt_attempt")
        self.assertEqual(incident.severity, "HIGH")
        self.assertEqual(incident.affected_principals_count, 1)

    def test_report_and_list_security_incidents(self):
        """Service accounts can report incidents, and Admins can review them for DPBI readiness."""
        payload = {
            "incident_type": "credential_stuffing_attempt",
            "severity": "MEDIUM",
            "affected_principals_count": 5,
            "data_fields_involved": ["account_id"],
            "details": {"source_subnet": "203.0.113.0/24"},
        }
        res_report = self.client.post(
            "/api/v1/security/incidents",
            headers={"X-Service-Key": SERVICE_ACCOUNT_API_KEY},
            json=payload,
        )
        self.assertEqual(res_report.status_code, 201)
        inc_id = res_report.json()["id"]

        # Admin lists incidents
        res_list = self.client.get(
            "/api/v1/security/incidents",
            headers={"X-Admin-Key": ADMIN_API_KEY},
        )
        self.assertEqual(res_list.status_code, 200)
        incidents = res_list.json()
        self.assertTrue(any(i["id"] == inc_id for i in incidents))

    # =========================================================================
    # 6. Storage Limitation & Inactive Account Retention Engine (Section 8(7))
    # =========================================================================
    def test_retention_policy_purges_inactive_accounts(self):
        """Accounts inactive beyond retention period (24 months) are purged and anonymized."""
        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=800)  # > 730 days (24 months)

        # 1. Create an inactive user (inactive for 800 days)
        inactive_user = User(
            id=uuid.uuid4(),
            phone_number_encrypted=encrypt_pii("+919111122222"),
            created_at=old_date,
            last_active_at=old_date,
            account_status="active",
        )
        self.db.add(inactive_user)

        # 2. Create an active user (active today)
        active_user = User(
            id=uuid.uuid4(),
            phone_number_encrypted=encrypt_pii("+919999988888"),
            created_at=now - timedelta(days=10),
            last_active_at=now,
            account_status="active",
        )
        self.db.add(active_user)
        self.db.commit()

        # Add saved route for inactive user
        src_id = uuid.uuid4()
        dst_id = uuid.uuid4()
        route = SavedRoute(
            id=uuid.uuid4(),
            user_id=inactive_user.id,
            source_station_id=src_id,
            destination_station_id=dst_id,
            alert_enabled=True,
            created_at=old_date,
        )
        self.db.add(route)
        self.db.commit()

        # Execute retention policy with 730 days threshold
        res = self.client.post(
            "/api/v1/security/retention/run?retention_days=730",
            headers={"X-Admin-Key": ADMIN_API_KEY},
        )
        self.assertEqual(res.status_code, 200)
        report = res.json()
        self.assertEqual(report["principals_purged"], 1)

        # Verify inactive user was purged
        self.db.refresh(inactive_user)
        self.assertIsNone(inactive_user.phone_number_encrypted, "PII must be nullified upon retention purge")
        self.assertEqual(inactive_user.account_status, "erased")

        # Verify saved routes for inactive user were deleted
        remaining_routes = self.db.query(SavedRoute).filter(SavedRoute.user_id == inactive_user.id).count()
        self.assertEqual(remaining_routes, 0)

        # Verify active user remains intact
        self.db.refresh(active_user)
        self.assertIsNotNone(active_user.phone_number_encrypted, "Active user data must remain untouched")
        self.assertEqual(active_user.account_status, "active")


if __name__ == "__main__":
    unittest.main()

"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — SQLAlchemy Database Models
===============================================================================
Author: Senior Python Engineer
Purpose:
  Object-Relational Mapping (ORM) models for transit telemetry, geocoded stations,
  schedules, buses, and unresolved stations using SQLAlchemy and GeoAlchemy2.
===============================================================================
"""

import uuid
from sqlalchemy import (
    Column,
    String,
    Boolean,
    Numeric,
    Integer,
    DateTime,
    ForeignKey,
    JSON,
    LargeBinary,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry

from .database import Base


class Station(Base):
    """
    Belagavi Division bus stops, depots, and terminal bays with PostGIS geometry.
    Includes Step 2C geocoding provenance and geofence perimeter radius.
    """
    __tablename__ = "stations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, index=True)
    platform_name = Column(String, nullable=True)
    location = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)
    geofence_radius_meters = Column(Numeric(6, 2), nullable=False, default=60.00)
    geocode_source = Column(String, nullable=True)  # Step 2C: 'manual_override', 'nominatim:bus_stop', etc.
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    unresolved_record = relationship(
        "UnresolvedStation",
        back_populates="station",
        uselist=False,
        cascade="all, delete-orphan",
    )
    departing_trips = relationship(
        "Trip",
        foreign_keys="Trip.source_station_id",
        back_populates="source_station",
    )
    arriving_trips = relationship(
        "Trip",
        foreign_keys="Trip.destination_station_id",
        back_populates="destination_station",
    )

    def __repr__(self) -> str:
        return f"<Station(name='{self.name}', platform='{self.platform_name}', source='{self.geocode_source}')>"


class UnresolvedStation(Base):
    """
    Quarantine table (Step 2C) for transit stops with low-confidence or missing
    geocoding matches requiring administrative review.
    """
    __tablename__ = "unresolved_stations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    station_id = Column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
    )
    name = Column(String, nullable=False)
    attempted_query = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    station = relationship("Station", back_populates="unresolved_record")

    def __repr__(self) -> str:
        return f"<UnresolvedStation(name='{self.name}', reason='{self.reason}')>"


class Bus(Base):
    """
    Real-time bus telemetry state, fleet identity, speed, and platform departure status.
    Dynamically auto-registered upon first telemetry ping.
    """
    __tablename__ = "buses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bus_number = Column(String, unique=True, nullable=False, index=True)
    service_type = Column(String, nullable=False, default="Ordinary")
    current_location = Column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    speed = Column(Numeric(5, 2), default=0.00)
    has_left_platform = Column(Boolean, nullable=False, default=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    trips = relationship("Trip", back_populates="bus")

    def __repr__(self) -> str:
        return f"<Bus(bus_number='{self.bus_number}', service='{self.service_type}', speed={self.speed}, departed={self.has_left_platform})>"


class Trip(Base):
    """
    Scheduled and active inter-taluk / inter-district passenger trips across Belagavi Division.
    Backed by Step 2B imported schedules with depot, schedule_no, and polylines.
    """
    __tablename__ = "trips"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bus_id = Column(
        UUID(as_uuid=True),
        ForeignKey("buses.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_station_id = Column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    destination_station_id = Column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    departure_time = Column(DateTime(timezone=True), nullable=False)
    route_via = Column(String, nullable=True)
    route_polyline = Column(JSON, nullable=False, default=list)
    status = Column(String, nullable=False, default="scheduled")  # scheduled, in_transit, arrived, delayed, cancelled
    depot = Column(String, nullable=True)  # Step 2B schedule depot (e.g. Belagavi-1, Chikkodi, Athani)
    schedule_no = Column(String, nullable=True)  # Step 2B schedule number
    platform_no = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    bus = relationship("Bus", back_populates="trips")
    source_station = relationship(
        "Station",
        foreign_keys=[source_station_id],
        back_populates="departing_trips",
    )
    destination_station = relationship(
        "Station",
        foreign_keys=[destination_station_id],
        back_populates="arriving_trips",
    )

    def __repr__(self) -> str:
        return f"<Trip(id={self.id}, dept='{self.departure_time}', status='{self.status}', depot='{self.depot}')>"


class User(Base):
    """DPDP Act 2023 compliant registered user record."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number_encrypted = Column(LargeBinary, nullable=True)
    email_encrypted = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_active_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())
    account_status = Column(String, nullable=False, default="active")


class SavedRoute(Base):
    """Rider saved routes and alert subscriptions."""
    __tablename__ = "saved_routes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_station_id = Column(UUID(as_uuid=True), ForeignKey("stations.id", ondelete="CASCADE"), nullable=False)
    destination_station_id = Column(UUID(as_uuid=True), ForeignKey("stations.id", ondelete="CASCADE"), nullable=False)
    alert_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConsentRecord(Base):
    """DPDP Notice & Consent Audit Log."""
    __tablename__ = "consent_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose = Column(String, nullable=False)
    consent_given_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    consent_withdrawn_at = Column(DateTime(timezone=True), nullable=True)
    notice_version = Column(String, nullable=False, default="DPDP-2025-v1.0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DataRequest(Base):
    """Data Principal Rights Processing Log."""
    __tablename__ = "data_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    request_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class PersonalDataAuditLog(Base):
    """
    Append-only audit ledger under Section 8 of DPDP Act 2023.
    Records every read, write, consent mutation, and PII decryption event on personal data.
    """
    __tablename__ = "personal_data_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    actor_role = Column(String, nullable=False)  # 'anonymous', 'service_account', 'admin', 'system_job'
    actor_id = Column(String, nullable=False)
    action = Column(String, nullable=False, index=True)  # 'READ', 'INSERT', 'UPDATE', 'DELETE', 'WITHDRAW_CONSENT', 'DECRYPT_PII', 'RETENTION_PURGE'
    target_table = Column(String, nullable=False)
    target_user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    fields_accessed = Column(JSON, nullable=False, default=list)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    status = Column(String, nullable=False, default="SUCCESS")  # 'SUCCESS', 'DENIED', 'ERROR'


class SecurityIncident(Base):
    """
    Personal data breach and security incident log under DPDP Act 2023 Section 8(6).
    Groundwork for mandatory notifications to Data Protection Board of India (DPBI)
    and affected Data Principals.
    """
    __tablename__ = "incident_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_type = Column(String, nullable=False)
    severity = Column(String, nullable=False, index=True)  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    affected_principals_count = Column(Integer, nullable=False, default=0)
    data_fields_involved = Column(JSON, nullable=False, default=list)
    detected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    status = Column(String, nullable=False, default="detected", index=True)  # 'detected', 'investigating', 'contained', 'reported_to_dpbi', 'resolved'
    reported_to_dpbi_at = Column(DateTime(timezone=True), nullable=True)
    affected_users_notified_at = Column(DateTime(timezone=True), nullable=True)
    details = Column(JSON, nullable=False, default=dict)


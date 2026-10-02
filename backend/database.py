"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — Database Engine & Session
===============================================================================
Author: Senior Python Engineer
Purpose:
  SQLAlchemy engine configuration, connection pooling, declarative base,
  and FastAPI dependency injection with `get_db()`.
===============================================================================
"""

import logging
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from .config import DATABASE_URL

logger = logging.getLogger("ksrtc_database")

# Ensure PostgreSQL driver dialect format
_db_url = DATABASE_URL
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif _db_url.startswith("postgresql://") and not _db_url.startswith("postgresql+"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

# Initialize SQLAlchemy Engine
try:
    engine = create_engine(
        _db_url,
        pool_pre_ping=True,
        pool_size=15,
        max_overflow=25,
        pool_recycle=1800,
        echo=False,
    )
except Exception as e:
    logger.error("Failed to initialize database engine for %s: %s", _db_url, e)
    # Fallback memory engine for offline dev/inspection
    engine = create_engine("sqlite:///:memory:", echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a transactional SQLAlchemy database session.
    Automatically handles closure upon request completion.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_health() -> bool:
    """Verifies database connectivity with a lightweight ping."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("Database connectivity check failed: %s", e)
        return False

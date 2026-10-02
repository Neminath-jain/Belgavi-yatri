"""
===============================================================================
KSRTC / NWKRTC Belagavi Division Live Tracker — Redis Client Lifecycle Manager
===============================================================================
Author: Senior Backend Infrastructure Engineer
Purpose:
  High-performance connection pooling for both asynchronous (FastAPI/WebSockets)
  and synchronous (ETL / Geocoder CLI scripts) Redis workloads.
===============================================================================
"""

import logging
from typing import AsyncGenerator, Optional
import redis
import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool as AsyncConnectionPool
from redis.connection import ConnectionPool as SyncConnectionPool

from .config import (
    REDIS_URL,
    REDIS_POOL_MAX_CONNECTIONS,
    REDIS_SOCKET_TIMEOUT,
    REDIS_CONNECT_TIMEOUT,
)

logger = logging.getLogger("ksrtc_redis_client")

logger = logging.getLogger("ksrtc_redis_client")

# Global Connection Pools
_async_pool: Optional[AsyncConnectionPool] = None
_sync_pool: Optional[SyncConnectionPool] = None
_fake_async_client = None
_fake_sync_client = None
_is_using_fake = False


def _check_redis_reachable() -> bool:
    """Quick 0.5s socket check to see if local/remote Redis is reachable."""
    try:
        test_client = redis.Redis.from_url(REDIS_URL, socket_timeout=0.5, socket_connect_timeout=0.5)
        test_client.ping()
        test_client.close()
        return True
    except Exception:
        return False


# -----------------------------------------------------------------------------
# 1. Asynchronous Redis Client (FastAPI & Telemetry Ingestion Hot-Path)
# -----------------------------------------------------------------------------
def get_async_redis() -> aioredis.Redis:
    """
    Returns an async Redis client.
    If live Redis server is reachable, uses pooled aioredis connection.
    If not running (e.g. local offline development), seamlessly uses in-memory fakeredis.
    """
    global _async_pool, _fake_async_client, _is_using_fake

    if _is_using_fake or not _check_redis_reachable():
        if _fake_async_client is None:
            import fakeredis.aioredis as fake_aio
            _fake_async_client = fake_aio.FakeRedis(decode_responses=True)
            _is_using_fake = True
            logger.info("Live Redis server not detected at %s. Using in-memory Redis simulation for local dev.", REDIS_URL)
        return _fake_async_client

    if _async_pool is None:
        _async_pool = AsyncConnectionPool.from_url(
            REDIS_URL,
            max_connections=REDIS_POOL_MAX_CONNECTIONS,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
            decode_responses=True,
        )
        logger.info("Initialized Redis async connection pool: max_conn=%d", REDIS_POOL_MAX_CONNECTIONS)

    return aioredis.Redis(connection_pool=_async_pool)


async def get_redis_dependency() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI Depends() generator for injection into API route handlers."""
    client = get_async_redis()
    try:
        yield client
    finally:
        if not _is_using_fake:
            await client.aclose()


async def close_async_pool() -> None:
    """Gracefully flushes and tears down the async pool on application shutdown."""
    global _async_pool, _fake_async_client
    if _async_pool is not None:
        await _async_pool.disconnect()
        _async_pool = None
        logger.info("Closed Redis async connection pool.")
    if _fake_async_client is not None:
        await _fake_async_client.aclose()
        _fake_async_client = None


# -----------------------------------------------------------------------------
# 2. Synchronous Redis Client (ETL Importers, Geocoding Scripts)
# -----------------------------------------------------------------------------
def get_sync_redis() -> redis.Redis:
    """
    Returns a synchronous Redis client for background importer scripts.
    Falls back to in-memory sync fakeredis if Redis is not running.
    """
    global _sync_pool, _fake_sync_client

    if not _check_redis_reachable():
        if _fake_sync_client is None:
            import fakeredis
            _fake_sync_client = fakeredis.FakeRedis(decode_responses=True)
            logger.info("Using synchronous in-memory Redis simulation for ETL.")
        return _fake_sync_client

    if _sync_pool is None:
        _sync_pool = SyncConnectionPool.from_url(
            REDIS_URL,
            max_connections=10,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
            decode_responses=True,
        )
        logger.info("Initialized Redis sync connection pool for ETL tooling.")

    return redis.Redis(connection_pool=_sync_pool)


def close_sync_pool() -> None:
    """Gracefully closes the synchronous Redis connection pool."""
    global _sync_pool, _fake_sync_client
    if _sync_pool is not None:
        _sync_pool.disconnect()
        _sync_pool = None
        logger.info("Closed Redis sync connection pool.")
    if _fake_sync_client is not None:
        _fake_sync_client.close()
        _fake_sync_client = None

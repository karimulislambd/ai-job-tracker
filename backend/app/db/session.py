"""Async engine / session factory and the request-scoped session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_SSL_MODES_REQUIRING_TLS = {"require", "verify-ca", "verify-full"}


def normalize_db_url(url: str) -> tuple[str, dict[str, Any]]:
    """Strip libpq-only query params (``sslmode``, ``channel_binding``) that asyncpg rejects,
    translating them into asyncpg ``connect_args``. Neon connection strings include both.
    """
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    # Pin the session timezone so date_trunc('week', ...) in stats is deterministic.
    connect_args: dict[str, Any] = {"server_settings": {"timezone": "UTC"}}
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if sslmode in _SSL_MODES_REQUIRING_TLS:
        connect_args["ssl"] = "require"
    # PgBouncer in transaction mode (e.g. Neon's "-pooler" host) breaks asyncpg's
    # prepared-statement cache; disable it and use unique statement names.
    if "-pooler" in (parts.hostname or ""):
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"
    clean = urlunsplit(parts._replace(query=urlencode(query)))
    return clean, connect_args


def create_engine(url: str | None = None, **kwargs: Any) -> AsyncEngine:
    settings = get_settings()
    clean_url, connect_args = normalize_db_url(url or settings.database_url)
    options: dict[str, Any] = {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
    options.update(kwargs)
    return create_async_engine(clean_url, connect_args=connect_args, **options)


engine: AsyncEngine = create_engine()
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, autoflush=False
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed by the service layer."""
    async with SessionLocal() as session:
        yield session

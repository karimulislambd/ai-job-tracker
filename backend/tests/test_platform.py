"""Cross-cutting behaviour: health, error envelope, request ids, CORS, OpenAPI, logging,
cache/rate-limit backends, settings normalisation and migration/model drift."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.cache import InMemoryCache, RedisCache
from app.core.config import Settings
from app.core.logging import JsonFormatter, request_id_var
from app.core.rate_limit import InMemoryRateLimiter, RedisRateLimiter
from app.db.base import Base
from app.db.session import normalize_db_url
from app.main import build_backends


async def test_health(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


async def test_health_reports_db_failure(app_factory: Any) -> None:
    from app.db.session import get_session

    class Broken:
        async def execute(self, *a: Any) -> None:
            raise ConnectionError("db down")

    app = app_factory()

    async def broken_session() -> Any:
        yield Broken()

    app.dependency_overrides[get_session] = broken_session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


async def test_request_id_is_generated_or_propagated(client: httpx.AsyncClient) -> None:
    generated = await client.get("/health")
    assert len(generated.headers["x-request-id"]) == 32
    propagated = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert propagated.headers["x-request-id"] == "abc-123"
    # Malicious/oversized ids are replaced, not echoed.
    replaced = await client.get("/health", headers={"X-Request-ID": "x" * 200})
    assert replaced.headers["x-request-id"] != "x" * 200


async def test_error_envelope_includes_request_id(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/nope", headers={"X-Request-ID": "trace-me"})
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "details": None,
            "request_id": "trace-me",
        }
    }
    resp = await client.delete("/health")
    assert resp.json()["error"]["code"] == "method_not_allowed"


async def test_unhandled_exceptions_return_generic_500(app_factory: Any) -> None:
    app: FastAPI = app_factory()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    assert "secret" not in resp.text


async def test_cors_allows_only_frontend_origin(client: httpx.AsyncClient) -> None:
    ok = await client.options(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert ok.headers["access-control-allow-credentials"] == "true"

    bad = await client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers


async def test_openapi_documents_all_routes(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    paths = set(spec["paths"])
    for expected in [
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/demo",
        "/api/v1/applications",
        "/api/v1/applications/{application_id}/status",
        "/api/v1/applications/{application_id}/analyze",
        "/api/v1/analyses/{analysis_id}",
        "/api/v1/resumes",
        "/api/v1/stats/dashboard",
    ]:
        assert expected in paths
    assert (await client.get("/docs")).status_code == 200


def test_json_log_formatter_includes_request_id_and_extras() -> None:
    token = request_id_var.set("rid-1")
    try:
        record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello %s", ("world",), None)
        record.job_id = 42
        out = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert out["msg"] == "hello world"
    assert out["request_id"] == "rid-1"
    assert out["job_id"] == 42
    assert out["level"] == "INFO"


def test_settings_normalise_database_url_and_blanks() -> None:
    s = Settings(database_url="postgres://u:p@h/db", redis_url="  ", groq_api_key="")
    assert s.database_url == "postgresql+asyncpg://u:p@h/db"
    assert s.redis_url is None
    assert s.groq_api_key is None
    s2 = Settings(frontend_origin="https://a.app/, https://b.app")
    assert s2.cors_origins == ["https://a.app", "https://b.app"]


def test_neon_url_is_made_asyncpg_compatible() -> None:
    url, args = normalize_db_url(
        "postgresql+asyncpg://u:p@ep-x-pooler.eu.aws.neon.tech/db?sslmode=require&channel_binding=require"
    )
    assert "sslmode" not in url
    assert "channel_binding" not in url
    assert args["ssl"] == "require"
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_name_func"]().startswith("__asyncpg_")
    _, plain_args = normalize_db_url("postgresql+asyncpg://u:p@localhost/db")
    assert "ssl" not in plain_args
    assert plain_args["server_settings"] == {"timezone": "UTC"}


async def test_models_match_migrations(engine: AsyncEngine) -> None:
    """Fails if someone changes a model without writing an Alembic migration."""
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)
        )
    assert diff == []


async def test_in_memory_cache_ttl_and_eviction() -> None:
    cache = InMemoryCache(max_entries=2)
    await cache.set_json("a", {"v": 1}, ttl_seconds=60)
    assert await cache.get_json("a") == {"v": 1}
    await cache.set_json("b", 2, ttl_seconds=-1)  # already expired
    assert await cache.get_json("b") is None
    await cache.set_json("c", 3, 60)
    await cache.set_json("d", 4, 60)  # evicts to stay within max_entries
    assert len(cache._data) <= 2
    await cache.delete("d")
    assert await cache.get_json("d") is None
    assert await cache.get_json("missing") is None


async def test_in_memory_rate_limiter_windows() -> None:
    limiter = InMemoryRateLimiter()
    results = [await limiter.hit("k", limit=2, window_seconds=60) for _ in range(3)]
    assert [r[0] for r in results] == [True, True, False]
    assert 1 <= results[-1][1] <= 60
    assert (await limiter.hit("other", 2, 60))[0] is True
    await limiter.reset()
    assert (await limiter.hit("k", 2, 60))[0] is True


@pytest.fixture
async def redis_url() -> Any:
    import os

    from redis.asyncio import Redis

    url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
    client = Redis.from_url(url, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        pytest.skip("Redis not available")
    finally:
        await client.aclose()
    return url


async def test_redis_backends(redis_url: str, settings: Settings) -> None:
    cache, limiter, redis = build_backends(settings.model_copy(update={"redis_url": redis_url}))
    assert isinstance(cache, RedisCache)
    assert isinstance(limiter, RedisRateLimiter)
    assert redis is not None
    try:
        await redis.flushdb()
        await cache.set_json("k", {"a": [1, 2]}, 30)
        assert await cache.get_json("k") == {"a": [1, 2]}
        await cache.delete("k")
        assert await cache.get_json("k") is None
        hits = [await limiter.hit("ip", limit=2, window_seconds=30) for _ in range(3)]
        assert [h[0] for h in hits] == [True, True, False]
    finally:
        await redis.flushdb()
        await redis.aclose()


def test_memory_backends_without_redis(settings: Settings) -> None:
    cache, limiter, redis = build_backends(settings)
    assert isinstance(cache, InMemoryCache)
    assert isinstance(limiter, InMemoryRateLimiter)
    assert redis is None


async def test_lifespan_starts_and_stops_in_process_worker(settings: Settings) -> None:
    from app.main import create_app

    cfg = settings.model_copy(
        update={"run_worker_in_api": True, "worker_poll_interval_seconds": 0.05}
    )
    app = create_app(cfg)
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.cache, InMemoryCache)
        assert isinstance(app.state.rate_limiter, InMemoryRateLimiter)

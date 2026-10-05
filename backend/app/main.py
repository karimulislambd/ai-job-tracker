"""FastAPI application factory and lifespan (cache/rate-limit backends, worker, demo seed)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.router import api_router
from app.api.routes import health
from app.core.cache import Cache, InMemoryCache, RedisCache
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.db.session import SessionLocal, engine
from app.seed.seeder import seed_demo_template
from app.services.llm import build_llm_client
from app.worker.handlers import build_registry
from app.worker.runner import Scheduler, Worker

logger = logging.getLogger("app")

API_DESCRIPTION = """
Track job applications on a Kanban board, keep a status-change timeline, upload your CV and
get an **AI match analysis** (Groq · GPT-OSS 120B) processed by a Postgres-backed job queue.

**Auth:** `POST /api/v1/auth/login` (or `/auth/demo`) returns a short-lived JWT access token;
send it as `Authorization: Bearer <token>`. A rotating refresh token lives in an httpOnly cookie.

All errors share one envelope: `{"error": {"code", "message", "details", "request_id"}}`.
"""


def build_backends(settings: Settings) -> tuple[Cache, RateLimiter, Redis | None]:
    if settings.redis_url:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return RedisCache(redis), RedisRateLimiter(redis), redis
    return InMemoryCache(), InMemoryRateLimiter(), None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    cache, limiter, redis = build_backends(settings)
    app.state.cache, app.state.rate_limiter = cache, limiter
    logger.info(
        "startup",
        extra={
            "environment": settings.environment,
            "backend": "redis" if redis else "in-memory",
            "llm": "groq" if settings.groq_api_key else "heuristic-offline",
            "in_process_worker": settings.run_worker_in_api,
        },
    )

    if settings.demo_enabled and settings.environment != "test":
        try:
            async with SessionLocal() as session:
                await seed_demo_template(session)
        except Exception:
            logger.exception("demo_seed_failed")

    stop = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []
    if settings.run_worker_in_api:
        worker = Worker(SessionLocal, build_registry(build_llm_client(settings)), settings)
        tasks.append(asyncio.create_task(worker.run_forever(stop), name="worker"))
        tasks.append(
            asyncio.create_task(
                Scheduler(SessionLocal, settings).run_forever(stop), name="scheduler"
            )
        )
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            with suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(task, timeout=10)
        if redis is not None:
            await redis.aclose()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = settings
    # Fallbacks so the app also works when the lifespan isn't run (e.g. some test clients).
    app.state.cache, app.state.rate_limiter = InMemoryCache(), InMemoryRateLimiter()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()

"""FastAPI dependencies: DB session, settings, cache, current user, rate limiting."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import Cache
from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from app.core.rate_limit import RateLimiter
from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_session
from app.models import User
from app.repositories.users import UserRepository

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_bearer = HTTPBearer(auto_error=False, description="JWT access token from /auth/login")


def get_cache(request: Request) -> Cache:
    cache: Cache = request.app.state.cache
    return cache


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


CacheDep = Annotated[Cache, Depends(get_cache)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    unauthorized = UnauthorizedError("Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise UnauthorizedError(
            "Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    user = await UserRepository(session).get(user_id)
    if user is None or user.is_demo_template:
        raise unauthorized
    if user.is_demo and user.demo_expires_at and user.demo_expires_at <= datetime.now(UTC):
        raise UnauthorizedError("Demo session expired")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def current_user_id(user: CurrentUser) -> uuid.UUID:
    return user.id


UserId = Annotated[uuid.UUID, Depends(current_user_id)]


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, multiplier: int = 1) -> Callable[..., Awaitable[None]]:
    """Per-IP fixed-window limit for sensitive endpoints (login, register, refresh, demo).

    ``multiplier`` scales AUTH_RATE_LIMIT for endpoints legitimately hit more often
    (e.g. refresh runs on every page load).
    """

    async def _dependency(
        request: Request,
        settings: SettingsDep,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        key = f"{bucket}:{client_ip(request, settings)}"
        allowed, retry_after = await limiter.hit(
            key, settings.auth_rate_limit * multiplier, settings.auth_rate_window_seconds
        )
        if not allowed:
            raise RateLimitedError(
                "Too many requests, please slow down",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency


async def verify_origin(request: Request, settings: SettingsDep) -> None:
    """CSRF defence for cookie-authenticated endpoints (refresh/logout).

    Browsers always send ``Origin`` on cross-site POSTs; if present it must be ours.
    Requests with no Origin (curl, same-origin proxies, server-to-server) are allowed.
    """
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in settings.cors_origins:
        raise ForbiddenError("Origin not allowed")

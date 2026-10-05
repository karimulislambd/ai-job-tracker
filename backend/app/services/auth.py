"""Authentication: registration, login, refresh-token rotation with reuse detection, logout."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    AccessToken,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models import RefreshToken, User
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    user: User
    access: AccessToken
    refresh_token: str
    refresh_expires_at: datetime


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    async def register(self, email: str, password: str, full_name: str | None) -> User:
        user = User(email=email.lower(), password_hash=hash_password(password), full_name=full_name)
        try:
            await self.users.add(user)
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("An account with this email already exists") from exc
        await self.session.commit()
        return user

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)
        # verify_password runs even for unknown users (dummy hash) to equalise timing.
        if not verify_password(password, user.password_hash if user else None) or user is None:
            raise UnauthorizedError("Invalid email or password")
        if user.is_demo_template:
            raise UnauthorizedError("Invalid email or password")
        return user

    async def issue_tokens(
        self,
        user: User,
        *,
        family_id: uuid.UUID | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> tuple[IssuedTokens, RefreshToken]:
        now = now or datetime.now(UTC)
        raw, digest = new_refresh_token()
        expires = now + timedelta(days=self.settings.refresh_token_ttl_days)
        if user.is_demo and user.demo_expires_at is not None:
            expires = min(expires, user.demo_expires_at)
        record = await self.tokens.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id or uuid.uuid4(),
                token_hash=digest,
                expires_at=expires,
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        issued = IssuedTokens(
            user=user,
            access=create_access_token(user.id, now=now),
            refresh_token=raw,
            refresh_expires_at=expires,
        )
        return issued, record

    async def login(self, email: str, password: str, user_agent: str | None) -> IssuedTokens:
        user = await self.authenticate(email, password)
        issued, _ = await self.issue_tokens(user, user_agent=user_agent)
        await self.session.commit()
        return issued

    async def refresh(
        self, raw_token: str | None, user_agent: str | None, now: datetime | None = None
    ) -> IssuedTokens:
        """Rotate a refresh token. Reuse of a rotated/revoked token revokes the family."""
        now = now or datetime.now(UTC)
        if not raw_token:
            raise UnauthorizedError("Missing refresh token")
        current = await self.tokens.get_by_hash_for_update(hash_refresh_token(raw_token))
        if current is None:
            raise UnauthorizedError("Invalid refresh token")
        if current.revoked_at is not None:
            # A token that was already rotated is being replayed: assume it was stolen.
            logger.warning(
                "refresh_token_reuse_detected",
                extra={"user_id": str(current.user_id), "family_id": str(current.family_id)},
            )
            await self.tokens.revoke_family(current.family_id, now)
            await self.session.commit()
            raise UnauthorizedError("Refresh token reuse detected; please log in again")
        if current.expires_at <= now:
            raise UnauthorizedError("Refresh token expired")
        user = await self.users.get(current.user_id)
        if user is None:  # pragma: no cover - FK cascade makes this unreachable
            raise UnauthorizedError("Invalid refresh token")

        issued, replacement = await self.issue_tokens(
            user, family_id=current.family_id, user_agent=user_agent, now=now
        )
        current.revoked_at = now
        current.replaced_by_id = replacement.id
        await self.session.commit()
        return issued

    async def logout(self, raw_token: str | None, now: datetime | None = None) -> None:
        """Revoke the whole token family of the presented refresh token (idempotent)."""
        if not raw_token:
            return
        current = await self.tokens.get_by_hash_for_update(hash_refresh_token(raw_token))
        if current is not None:
            await self.tokens.revoke_family(current.family_id, now or datetime.now(UTC))
            await self.session.commit()

"""Password hashing (Argon2id), JWT access tokens and opaque refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library defaults (OWASP-compliant parameters)

# Verifying against a dummy hash for unknown emails keeps login timing uniform,
# so response time does not reveal whether an account exists.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True, slots=True)
class AccessToken:
    token: str
    expires_at: datetime


def create_access_token(user_id: uuid.UUID, *, now: datetime | None = None) -> AccessToken:
    settings = get_settings()
    issued = now or datetime.now(UTC)
    expires = issued + timedelta(minutes=settings.access_token_ttl_minutes)
    claims = {
        "sub": str(user_id),
        "type": "access",
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return AccessToken(token=token, expires_at=expires)


class InvalidTokenError(Exception):
    pass


def decode_access_token(token: str) -> uuid.UUID:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if claims.get("type") != "access":
        raise InvalidTokenError("wrong token type")
    try:
        return uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise InvalidTokenError("malformed subject") from exc


def new_refresh_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hex)``. Only the hash is persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    # Refresh tokens are 384 bits of CSPRNG output, so a fast hash is appropriate here
    # (unlike passwords, they cannot be brute-forced from the hash).
    return hashlib.sha256(raw.encode()).hexdigest()

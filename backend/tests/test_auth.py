from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_access_token, verify_password
from app.models import RefreshToken
from tests.conftest import AuthedUser, register_user

COOKIE = "ajt_refresh"


async def test_register_returns_tokens_and_sets_httponly_cookie(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "New.User@Example.com", "password": "hunter22!", "full_name": "New"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "new.user@example.com"  # normalised
    set_cookie = resp.headers["set-cookie"]
    assert f"{COOKIE}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie
    assert "samesite=lax" in set_cookie.lower()


async def test_register_duplicate_email_conflicts(client: httpx.AsyncClient) -> None:
    await register_user(client, email="dup@example.com")
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "DUP@example.com", "password": "hunter22!"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"email": "not-an-email", "password": "hunter22!"}, "email"),
        ({"email": "a@example.com", "password": "short1"}, "password"),
        ({"email": "a@example.com", "password": "onlyletters"}, "password"),
    ],
)
async def test_register_validation(
    client: httpx.AsyncClient, payload: dict[str, str], field: str
) -> None:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert any(field in d["loc"] for d in err["details"])


async def test_login_and_me(client: httpx.AsyncClient) -> None:
    u = await register_user(client, email="login@example.com", password="pa55word!")
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "LOGIN@example.com", "password": "pa55word!"}
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(u.id)
    assert me.json()["is_demo"] is False


@pytest.mark.parametrize(
    ("email", "password"),
    [("login2@example.com", "wrong-password1"), ("nobody@example.com", "pa55word!")],
)
async def test_login_failures_are_indistinguishable(
    client: httpx.AsyncClient, email: str, password: str
) -> None:
    await register_user(client, email="login2@example.com", password="pa55word!")
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Invalid email or password"


async def test_me_requires_valid_token(client: httpx.AsyncClient, settings: Settings) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    bad = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    assert bad.headers["www-authenticate"] == "Bearer"

    u = await register_user(client)
    expired = create_access_token(u.id, now=datetime.now(UTC) - timedelta(hours=1))
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired.token}"})
    assert resp.status_code == 401

    # A token signed with the right key but the wrong type is rejected.
    wrong_type = jwt.encode(
        {"sub": str(u.id), "type": "refresh", "iat": 1, "exp": 4_102_444_800},
        settings.jwt_secret,
        algorithm="HS256",
    )
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {wrong_type}"})
    assert resp.status_code == 401

    # Forged signature.
    forged = jwt.encode(
        {"sub": str(u.id), "type": "access", "iat": 1, "exp": 4_102_444_800},
        "x" * 40,
        algorithm="HS256",
    )
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


async def test_refresh_rotates_token(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await register_user(client)
    first = client.cookies.get(COOKIE)
    assert first

    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    second = client.cookies.get(COOKIE)
    assert second and second != first

    tokens = (await db_session.execute(select(RefreshToken))).scalars().all()
    old = next(t for t in tokens if t.revoked_at is not None)
    new = next(t for t in tokens if t.revoked_at is None)
    assert old.replaced_by_id == new.id
    assert old.family_id == new.family_id


async def test_refresh_token_reuse_revokes_whole_family(client: httpx.AsyncClient) -> None:
    await register_user(client)
    stolen = client.cookies.get(COOKIE)
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    legit = client.cookies.get(COOKIE)

    # Attacker replays the already-rotated token -> rejected...
    client.cookies.set(COOKIE, stolen, path="/api/v1/auth")
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    assert "reuse" in replay.json()["error"]["message"]

    # ...and the legitimate holder's current token was revoked along with the family.
    client.cookies.set(COOKIE, legit, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_refresh_without_or_with_unknown_cookie(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    client.cookies.set(COOKIE, "garbage", path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_expired_refresh_token_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await register_user(client)
    token = (await db_session.execute(select(RefreshToken))).scalar_one()
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Refresh token expired"


async def test_logout_revokes_refresh_token(client: httpx.AsyncClient) -> None:
    await register_user(client)
    cookie = client.cookies.get(COOKIE)
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    assert (
        'ajt_refresh=""' in resp.headers["set-cookie"] or "Max-Age=0" in resp.headers["set-cookie"]
    )
    # Even if the client kept a copy of the cookie, it no longer works.
    client.cookies.set(COOKIE, cookie, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    # Logging out twice is harmless.
    assert (await client.post("/api/v1/auth/logout")).status_code == 204


async def test_cookie_endpoints_reject_foreign_origin(client: httpx.AsyncClient) -> None:
    await register_user(client)
    resp = await client.post("/api/v1/auth/refresh", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    ok = await client.post("/api/v1/auth/refresh", headers={"Origin": "http://localhost:3000"})
    assert ok.status_code == 200


async def test_auth_endpoints_are_rate_limited(app_factory: object) -> None:
    app = app_factory(auth_rate_limit=3)  # type: ignore[operator]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        codes = [
            (
                await c.post(
                    "/api/v1/auth/login",
                    json={"email": "x@example.com", "password": "whatever1"},
                    headers={"X-Forwarded-For": "203.0.113.7"},
                )
            ).status_code
            for _ in range(4)
        ]
        assert codes == [401, 401, 401, 429]
        limited = await c.post(
            "/api/v1/auth/login",
            json={"email": "x@example.com", "password": "whatever1"},
            headers={"X-Forwarded-For": "203.0.113.7"},
        )
        assert limited.json()["error"]["code"] == "rate_limited"
        assert int(limited.headers["retry-after"]) >= 1
        # A different client IP has its own budget.
        other = await c.post(
            "/api/v1/auth/login",
            json={"email": "x@example.com", "password": "whatever1"},
            headers={"X-Forwarded-For": "198.51.100.1"},
        )
        assert other.status_code == 401


async def test_secure_cross_site_cookie_settings(app_factory: object) -> None:
    app = app_factory(cookie_secure=True, cookie_samesite="none")  # type: ignore[operator]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://t") as c:
        resp = await c.post(
            "/api/v1/auth/register", json={"email": "sec@example.com", "password": "hunter22!"}
        )
        cookie = resp.headers["set-cookie"].lower()
        assert "secure" in cookie
        assert "samesite=none" in cookie


def test_password_hash_roundtrip() -> None:
    from app.core.security import hash_password

    h = hash_password("correct horse 1")
    assert h.startswith("$argon2id$")
    assert verify_password("correct horse 1", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


async def test_access_token_contains_expected_claims(user: AuthedUser, settings: Settings) -> None:
    claims = jwt.decode(user.token, settings.jwt_secret, algorithms=["HS256"])
    assert claims["sub"] == str(user.id)
    assert claims["type"] == "access"
    assert claims["exp"] - claims["iat"] == settings.access_token_ttl_minutes * 60

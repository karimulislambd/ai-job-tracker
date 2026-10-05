"""Integration-test fixtures against a real PostgreSQL database.

* The schema is built once per session by running the real Alembic migrations.
* Each test runs inside an outer transaction that is rolled back afterwards; the code
  under test commits to SAVEPOINTs (``join_transaction_mode="create_savepoint"``), so
  services behave exactly as in production while tests stay isolated and fast.
* Tests that need truly concurrent connections (SKIP LOCKED) use ``committed_engine``
  and clean up after themselves.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from typing import Any

# Configure the app for tests *before* any app module is imported.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/jobtracker_test",
)
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": TEST_DATABASE_URL,
        "RUN_WORKER_IN_API": "false",
        "GROQ_API_KEY": "",
        "REDIS_URL": "",
        "LOG_LEVEL": "WARNING",
        "JWT_SECRET": "test-secret-0123456789-0123456789-0123456789",
        "FRONTEND_ORIGIN": "http://localhost:3000",
        "AUTH_RATE_LIMIT": "1000",
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.db.session import get_session, normalize_db_url  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.llm import LLMResponse  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _alembic_config() -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    return cfg


async def _reset_schema() -> None:
    url, args = normalize_db_url(TEST_DATABASE_URL)
    engine = create_async_engine(url, poolclass=NullPool, connect_args=args)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Fresh schema built by the real migrations (also exercises downgrade -> upgrade)."""
    asyncio.run(_reset_schema())
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    url, args = normalize_db_url(TEST_DATABASE_URL)
    eng = create_async_engine(url, connect_args=args, pool_size=5, max_overflow=10)
    yield eng
    await eng.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()


@pytest.fixture
def session_factory(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Sessions bound to the test's connection; their commits become SAVEPOINT releases."""
    return async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )


@pytest.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
def app_factory(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> Callable[..., Any]:
    def _make(**overrides: Any) -> Any:
        app = create_app(settings)
        if overrides:
            patched = settings.model_copy(update=overrides)
            app.dependency_overrides[get_settings] = lambda: patched
            app.state.settings = patched

        async def _session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as s:
                yield s

        app.dependency_overrides[get_session] = _session
        return app

    return _make


@pytest.fixture
async def client(app_factory: Callable[..., Any]) -> AsyncIterator[httpx.AsyncClient]:
    app = app_factory()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# --------------------------------------------------------------------------- helpers


@dataclass
class AuthedUser:
    id: uuid.UUID
    email: str
    token: str
    headers: dict[str, str]


async def register_user(
    client: httpx.AsyncClient, email: str | None = None, password: str = "s3cret-pass!"
) -> AuthedUser:
    email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password, "full_name": "T"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    token = body["access_token"]
    return AuthedUser(
        id=uuid.UUID(body["user"]["id"]),
        email=email,
        token=token,
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.fixture
async def user(client: httpx.AsyncClient) -> AuthedUser:
    return await register_user(client)


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedUser:
    return await register_user(client)


JOB_DESCRIPTION = (
    "Backend Engineer. Requirements: Python, FastAPI, PostgreSQL, Docker, Kubernetes, "
    "Terraform and Redis. Experience with GitHub Actions is a plus."
)


async def create_application(
    client: httpx.AsyncClient, u: AuthedUser, **fields: Any
) -> dict[str, Any]:
    payload = {"company": "Acme Corp", "role_title": "Backend Engineer", **fields}
    resp = await client.post("/api/v1/applications", json=payload, headers=u.headers)
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


VALID_RESULT: dict[str, Any] = {
    "match_score": 82,
    "summary": "Strong match for a Python backend role.",
    "matched_skills": ["Python", "FastAPI", "PostgreSQL", "python"],
    "missing_skills": ["Kubernetes"],
    "strengths": ["Solid API experience"],
    "gaps": ["No Kubernetes"],
    "cv_bullet_suggestions": [
        "Built FastAPI services handling 2M requests/day.",
        "Designed a Postgres job queue with retries.",
        "Automated CI with GitHub Actions.",
    ],
    "cover_letter": "Dear team, I am excited to apply for this backend role because " * 2,
}


class FakeLLM:
    """Scripted LLM: returns (or raises) the queued responses in order."""

    model = "fake-llm"

    def __init__(self, *responses: str | BaseException) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system: str, user: str) -> LLMResponse:
        self.calls.append((system, user))
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, BaseException):
            raise item
        return LLMResponse(
            content=item, model=self.model, prompt_tokens=120, completion_tokens=80, latency_ms=5
        )

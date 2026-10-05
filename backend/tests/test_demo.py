"""Demo mode: one-click isolated demo users cloned from the seeded template + cleanup."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIAnalysis, Application, ApplicationEvent, Resume, User
from app.seed.data import APPLICATIONS
from app.seed.seeder import seed_demo_template
from app.services.maintenance import cleanup_demo_users


@pytest.fixture
async def template(db_session: AsyncSession) -> User:
    return await seed_demo_template(db_session)


async def _demo_login(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.post("/api/v1/auth/demo")
    assert resp.status_code == 201, resp.text
    body = dict(resp.json())
    body["headers"] = {"Authorization": f"Bearer {body['access_token']}"}
    return body


async def test_seed_is_idempotent_and_force_recreates(
    db_session: AsyncSession, template: User
) -> None:
    again = await seed_demo_template(db_session)
    assert again.id == template.id
    recreated = await seed_demo_template(db_session, force=True)
    assert recreated.id != template.id
    count = await db_session.scalar(select(func.count()).where(User.is_demo_template.is_(True)))
    assert count == 1


async def test_demo_login_clones_full_dataset(
    client: httpx.AsyncClient, template: User, db_session: AsyncSession
) -> None:
    demo = await _demo_login(client)
    assert demo["user"]["is_demo"] is True
    expires = datetime.fromisoformat(demo["user"]["demo_expires_at"])
    assert timedelta(hours=23) < expires - datetime.now(UTC) <= timedelta(hours=24)
    assert "ajt_refresh=" in client.cookies.jar.__repr__() or client.cookies.get("ajt_refresh")

    apps = await client.get("/api/v1/applications", params={"limit": 200}, headers=demo["headers"])
    assert apps.json()["total"] == len(APPLICATIONS)
    statuses = {a["status"] for a in apps.json()["items"]}
    assert statuses == {"wishlist", "applied", "interviewing", "offer", "rejected", "withdrawn"}

    resumes = (await client.get("/api/v1/resumes", headers=demo["headers"])).json()
    assert [r["version"] for r in resumes] == [2, 1]
    assert resumes[0]["is_active"] is True

    # Events and analyses came along, re-pointed at the cloned rows.
    offer = next(a for a in apps.json()["items"] if a["company"] == "Northwind Analytics")
    events = (
        await client.get(f"/api/v1/applications/{offer['id']}/events", headers=demo["headers"])
    ).json()
    assert [e["to_status"] for e in events] == ["applied", "interviewing", "offer"]
    analyses = (
        await client.get(f"/api/v1/applications/{offer['id']}/analyses", headers=demo["headers"])
    ).json()
    assert len(analyses) == 1
    assert analyses[0]["result"]["match_score"] == 88
    assert analyses[0]["resume_id"] == resumes[0]["id"]

    stats = (await client.get("/api/v1/stats/dashboard", headers=demo["headers"])).json()
    assert stats["total"] == len(APPLICATIONS)
    assert stats["response_rate"] > 0
    assert any(w["count"] > 0 for w in stats["applications_per_week"])


async def test_demo_data_is_shifted_to_look_current(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # Template seeded 30 days ago: clones must be shifted forward by ~30 days.
    old = datetime.now(UTC) - timedelta(days=30)
    await seed_demo_template(db_session, now=old)
    demo = await _demo_login(client)
    apps = (
        await client.get("/api/v1/applications", params={"limit": 200}, headers=demo["headers"])
    ).json()["items"]
    newest_applied = max(datetime.fromisoformat(a["applied_at"]) for a in apps if a["applied_at"])
    assert datetime.now(UTC) - newest_applied < timedelta(days=4)


async def test_demo_users_are_isolated_from_each_other_and_the_template(
    client: httpx.AsyncClient, template: User, db_session: AsyncSession
) -> None:
    a = await _demo_login(client)
    b = await _demo_login(client)
    assert a["user"]["id"] != b["user"]["id"]

    a_apps = (await client.get("/api/v1/applications", headers=a["headers"])).json()["items"]
    target = a_apps[0]
    await client.delete(f"/api/v1/applications/{target['id']}", headers=a["headers"])
    # B can't see A's rows, and B's copy is unaffected by A's delete.
    assert (
        await client.get(f"/api/v1/applications/{target['id']}", headers=b["headers"])
    ).status_code == 404
    b_total = (await client.get("/api/v1/applications", headers=b["headers"])).json()["total"]
    assert b_total == len(APPLICATIONS)
    template_total = await db_session.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == template.id)
    )
    assert template_total == len(APPLICATIONS)


async def test_template_account_cannot_log_in(client: httpx.AsyncClient, template: User) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": template.email, "password": "anything123"}
    )
    assert resp.status_code == 401


async def test_demo_unavailable_without_seed_or_when_disabled(
    client: httpx.AsyncClient, app_factory: Callable[..., Any]
) -> None:
    resp = await client.post("/api/v1/auth/demo")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "demo_unavailable"

    app = app_factory(demo_enabled=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/api/v1/auth/demo")).status_code == 503


async def test_expired_demo_users_are_cleaned_up_with_all_their_data(
    client: httpx.AsyncClient, template: User, db_session: AsyncSession
) -> None:
    expired = await _demo_login(client)
    fresh = await _demo_login(client)

    user = await db_session.get(User, expired["user"]["id"])
    assert user is not None
    user.demo_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    # Expired demo tokens stop working immediately, even before cleanup runs.
    me = await client.get("/api/v1/auth/me", headers=expired["headers"])
    assert me.status_code == 401

    deleted = await cleanup_demo_users(db_session)
    assert deleted == 1

    async def count(model: Any, user_id: str) -> int:
        if model is ApplicationEvent:
            stmt = (
                select(func.count())
                .select_from(ApplicationEvent)
                .join(Application)
                .where(Application.user_id == user_id)
            )
        elif model is AIAnalysis:
            stmt = (
                select(func.count())
                .select_from(AIAnalysis)
                .join(Application)
                .where(Application.user_id == user_id)
            )
        else:
            stmt = select(func.count()).select_from(model).where(model.user_id == user_id)
        return int(await db_session.scalar(stmt) or 0)

    gone = expired["user"]["id"]
    template_id = str(template.id)
    db_session.expire_all()
    assert await db_session.get(User, gone) is None
    for model in (Application, ApplicationEvent, Resume, AIAnalysis):
        assert await count(model, gone) == 0
    # Fresh demo user and the template are untouched.
    assert await count(Application, fresh["user"]["id"]) == len(APPLICATIONS)
    assert await count(Application, template_id) == len(APPLICATIONS)
    assert await cleanup_demo_users(db_session) == 0

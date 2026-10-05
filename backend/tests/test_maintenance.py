from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.maintenance import flag_overdue_follow_ups
from tests.conftest import AuthedUser, create_application


async def test_flag_overdue_follow_ups(
    client: httpx.AsyncClient, user: AuthedUser, other_user: AuthedUser, db_session: AsyncSession
) -> None:
    past = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    overdue = await create_application(client, user, status="applied", follow_up_at=past)
    upcoming = await create_application(client, user, status="applied", follow_up_at=future)
    closed = await create_application(client, user, status="rejected", follow_up_at=past)
    others = await create_application(client, other_user, status="interviewing", follow_up_at=past)

    # Run with a clock slightly ahead so rows created in this transaction compare cleanly.
    now = datetime.now(UTC) + timedelta(seconds=1)
    assert await flag_overdue_follow_ups(db_session, now=now) == 2
    assert await flag_overdue_follow_ups(db_session, now=now) == 0  # idempotent

    async def flagged(u: AuthedUser, app_id: str) -> bool:
        body = (await client.get(f"/api/v1/applications/{app_id}", headers=u.headers)).json()
        return body["follow_up_flagged_at"] is not None

    assert await flagged(user, overdue["id"])
    assert not await flagged(user, upcoming["id"])
    assert not await flagged(user, closed["id"])  # rejected apps need no follow-up
    assert await flagged(other_user, others["id"])

    events = (
        await client.get(f"/api/v1/applications/{overdue['id']}/events", headers=user.headers)
    ).json()
    assert events[-1]["event_type"] == "follow_up_overdue"
    assert events[-1]["note"].startswith("Follow-up was due")

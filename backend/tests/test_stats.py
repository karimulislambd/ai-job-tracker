"""Dashboard stats correctness on a hand-computed dataset with fixed timestamps."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import InMemoryCache
from app.models import Application, ApplicationEvent, ApplicationStatus, EventType
from app.services.stats import StatsService
from tests.conftest import AuthedUser

# Wednesday, so "this week" starts Monday 2026-03-09.
NOW = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
S = ApplicationStatus


async def _add(
    session: AsyncSession,
    user_id: uuid.UUID,
    status: ApplicationStatus,
    *,
    applied_days_ago: float | None,
    transitions: list[tuple[ApplicationStatus, float]] = (),  # type: ignore[assignment]
    follow_up_in_days: float | None = None,
) -> Application:
    applied_at = NOW - timedelta(days=applied_days_ago) if applied_days_ago is not None else None
    app = Application(
        user_id=user_id,
        company=f"Co {uuid.uuid4().hex[:6]}",
        role_title="Engineer",
        status=status,
        applied_at=applied_at,
        follow_up_at=NOW + timedelta(days=follow_up_in_days)
        if follow_up_in_days is not None
        else None,
    )
    session.add(app)
    await session.flush()
    first = S.APPLIED if applied_at else S.WISHLIST
    session.add(
        ApplicationEvent(
            application_id=app.id,
            event_type=EventType.CREATED,
            to_status=first,
            occurred_at=applied_at or NOW - timedelta(days=1),
        )
    )
    prev = first
    for to, days_ago in transitions:
        session.add(
            ApplicationEvent(
                application_id=app.id,
                event_type=EventType.STATUS_CHANGED,
                from_status=prev,
                to_status=to,
                occurred_at=NOW - timedelta(days=days_ago),
            )
        )
        prev = to
    await session.flush()
    return app


async def test_dashboard_stats_match_hand_computed_values(
    db_session: AsyncSession, user: AuthedUser, other_user: AuthedUser
) -> None:
    uid = user.id
    # 1. applied 20d ago -> interviewing 16d ago (4 days) -> offer 5d ago
    await _add(
        db_session,
        uid,
        S.OFFER,
        applied_days_ago=20,
        transitions=[(S.INTERVIEWING, 16), (S.OFFER, 5)],
    )
    # 2. applied 10d ago -> rejected 4d ago (6 days)
    await _add(db_session, uid, S.REJECTED, applied_days_ago=10, transitions=[(S.REJECTED, 4)])
    # 3. applied 30d ago -> interviewing 22d ago (8 days) -> withdrawn 1d ago
    await _add(
        db_session,
        uid,
        S.WITHDRAWN,
        applied_days_ago=30,
        transitions=[(S.INTERVIEWING, 22), (S.WITHDRAWN, 1)],
    )
    # 4/5. applied, no response yet (one with an overdue follow-up, one upcoming)
    await _add(db_session, uid, S.APPLIED, applied_days_ago=3, follow_up_in_days=-1)
    await _add(db_session, uid, S.APPLIED, applied_days_ago=1, follow_up_in_days=2)
    # 6. wishlist (never applied) — excluded from rate denominators
    await _add(db_session, uid, S.WISHLIST, applied_days_ago=None, follow_up_in_days=20)
    # 7. applied 100 days ago (outside the 12-week window), still waiting
    await _add(db_session, uid, S.APPLIED, applied_days_ago=100)
    # Another user's data must not leak into the numbers.
    await _add(
        db_session,
        other_user.id,
        S.OFFER,
        applied_days_ago=2,
        transitions=[(S.OFFER, 1)],
        follow_up_in_days=1,
    )
    await db_session.commit()

    stats = await StatsService(db_session, InMemoryCache(), 60).dashboard(uid, now=NOW)

    assert stats.total == 7
    assert stats.by_status == {
        S.WISHLIST: 1,
        S.APPLIED: 3,
        S.INTERVIEWING: 0,
        S.OFFER: 1,
        S.REJECTED: 1,
        S.WITHDRAWN: 1,
    }
    assert stats.applied_count == 6
    assert stats.response_rate == round(3 / 6, 4)  # apps 1, 2, 3
    assert stats.interview_rate == round(2 / 6, 4)  # apps 1, 3 (withdrawal doesn't erase it)
    assert stats.offer_rate == round(1 / 6, 4)
    assert stats.avg_days_to_first_response == 6.0  # (4 + 6 + 8) / 3

    weeks = stats.applications_per_week
    assert len(weeks) == 12
    assert weeks[-1].week_start == date(2026, 3, 9)
    assert weeks[0].week_start == date(2025, 12, 22)
    assert all(w.week_start.weekday() == 0 for w in weeks)
    counts = {w.week_start: w.count for w in weeks}
    # applied 1d (Mar 10) and 3d (Mar 8 -> week of Mar 2) ago, 10d (Mar 1 -> Feb 23),
    # 20d (Feb 19 -> Feb 16), 30d (Feb 9 -> Feb 9)
    assert counts[date(2026, 3, 9)] == 1
    assert counts[date(2026, 3, 2)] == 1
    assert counts[date(2026, 2, 23)] == 1
    assert counts[date(2026, 2, 16)] == 1
    assert counts[date(2026, 2, 9)] == 1
    assert sum(counts.values()) == 5  # the 100-day-old one is outside the window

    # Follow-ups: due within 14 days (incl. overdue), active statuses only, soonest first.
    assert [f.overdue for f in stats.upcoming_follow_ups] == [True, False]
    assert stats.overdue_follow_ups == 1


async def test_empty_dashboard(db_session: AsyncSession, user: AuthedUser) -> None:
    stats = await StatsService(db_session, InMemoryCache(), 60).dashboard(user.id, now=NOW)
    assert stats.total == 0
    assert stats.response_rate == 0.0
    assert stats.avg_days_to_first_response is None
    assert len(stats.applications_per_week) == 12
    assert stats.upcoming_follow_ups == []


async def test_stats_endpoint_is_cached_and_invalidated_on_write(
    client: httpx.AsyncClient, user: AuthedUser
) -> None:
    async def total() -> int:
        resp = await client.get("/api/v1/stats/dashboard", headers=user.headers)
        assert resp.status_code == 200
        return int(resp.json()["total"])

    assert await total() == 0
    created = await client.post(
        "/api/v1/applications", json={"company": "A", "role_title": "B"}, headers=user.headers
    )
    assert await total() == 1  # cache invalidated by the write
    await client.patch(
        f"/api/v1/applications/{created.json()['id']}/status",
        json={"status": "applied"},
        headers=user.headers,
    )
    resp = await client.get("/api/v1/stats/dashboard", headers=user.headers)
    assert resp.json()["by_status"]["applied"] == 1
    await client.delete(f"/api/v1/applications/{created.json()['id']}", headers=user.headers)
    assert await total() == 0

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import Cache
from app.models import ApplicationStatus
from app.repositories.stats import StatsRepository
from app.schemas.stats import DashboardStats, UpcomingFollowUp, WeeklyCount
from app.services.applications import stats_cache_key


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


class StatsService:
    def __init__(self, session: AsyncSession, cache: Cache, ttl_seconds: int) -> None:
        self.repo = StatsRepository(session)
        self.cache = cache
        self.ttl = ttl_seconds

    async def dashboard(
        self, user_id: uuid.UUID, now: datetime | None = None, *, use_cache: bool = True
    ) -> DashboardStats:
        key = stats_cache_key(user_id)
        if use_cache and now is None:
            cached: Any = await self.cache.get_json(key)
            if cached is not None:
                return DashboardStats.model_validate(cached)

        now = now or datetime.now(UTC)
        summary = await self.repo.summary(user_id)
        by_status_raw = await self.repo.by_status(user_id)
        by_status = {s: by_status_raw.get(s.value, 0) for s in ApplicationStatus}
        applied = int(summary["applied"] or 0)
        avg_days = summary["avg_days_to_response"]
        stats = DashboardStats(
            total=int(summary["total"] or 0),
            by_status=by_status,
            applied_count=applied,
            response_rate=_rate(int(summary["responded"] or 0), applied),
            interview_rate=_rate(int(summary["interviewed"] or 0), applied),
            offer_rate=_rate(int(summary["offered"] or 0), applied),
            avg_days_to_first_response=round(float(avg_days), 1) if avg_days is not None else None,
            applications_per_week=[
                WeeklyCount(week_start=w, count=n) for w, n in await self.repo.weekly(user_id, now)
            ],
            upcoming_follow_ups=[
                UpcomingFollowUp.model_validate(r) for r in await self.repo.follow_ups(user_id, now)
            ],
            overdue_follow_ups=await self.repo.overdue_count(user_id, now),
        )
        if use_cache:
            await self.cache.set_json(key, stats.model_dump(mode="json"), self.ttl)
        return stats

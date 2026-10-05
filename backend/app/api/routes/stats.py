from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CacheDep, SessionDep, SettingsDep, UserId
from app.schemas.stats import DashboardStats
from app.services.stats import StatsService

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/dashboard", response_model=DashboardStats, summary="Aggregated dashboard metrics")
async def dashboard(
    user_id: UserId, session: SessionDep, cache: CacheDep, settings: SettingsDep
) -> DashboardStats:
    return await StatsService(session, cache, settings.stats_cache_ttl_seconds).dashboard(user_id)

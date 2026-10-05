from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.enums import ApplicationStatus


class WeeklyCount(BaseModel):
    week_start: date
    count: int


class UpcomingFollowUp(BaseModel):
    id: uuid.UUID
    company: str
    role_title: str
    status: ApplicationStatus
    follow_up_at: datetime
    overdue: bool


class DashboardStats(BaseModel):
    total: int
    by_status: dict[ApplicationStatus, int]
    applied_count: int
    response_rate: float
    interview_rate: float
    offer_rate: float
    avg_days_to_first_response: float | None
    applications_per_week: list[WeeklyCount]
    upcoming_follow_ups: list[UpcomingFollowUp]
    overdue_follow_ups: int

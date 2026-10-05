from __future__ import annotations

from enum import StrEnum


class ApplicationStatus(StrEnum):
    WISHLIST = "wishlist"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


# Statuses that mean "the company got back to me" — used by stats (response rate etc.).
RESPONSE_STATUSES: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
)
INTERVIEW_STATUSES: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFER,
)


class EventType(StrEnum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    FOLLOW_UP_OVERDUE = "follow_up_overdue"


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

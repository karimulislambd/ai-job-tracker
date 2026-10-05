from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator

from app.models.enums import ApplicationStatus, EventType
from app.schemas.common import ORMModel


class _ApplicationFields(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    role_title: str = Field(min_length=1, max_length=200)
    job_url: AnyHttpUrl | None = None
    location: str | None = Field(default=None, max_length=200)
    salary_min: int | None = Field(default=None, ge=0, le=100_000_000)
    salary_max: int | None = Field(default=None, ge=0, le=100_000_000)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    applied_at: datetime | None = None
    follow_up_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    job_description: str | None = Field(default=None, max_length=50_000)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @field_validator("company", "role_title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class ApplicationCreate(_ApplicationFields):
    status: ApplicationStatus = ApplicationStatus.WISHLIST

    @model_validator(mode="after")
    def _salary_range(self) -> ApplicationCreate:
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min must be <= salary_max")
        return self


class ApplicationUpdate(BaseModel):
    """Partial update; only fields present in the request body are applied."""

    company: str | None = Field(default=None, min_length=1, max_length=200)
    role_title: str | None = Field(default=None, min_length=1, max_length=200)
    job_url: AnyHttpUrl | None = None
    location: str | None = Field(default=None, max_length=200)
    salary_min: int | None = Field(default=None, ge=0, le=100_000_000)
    salary_max: int | None = Field(default=None, ge=0, le=100_000_000)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    status: ApplicationStatus | None = None
    applied_at: datetime | None = None
    follow_up_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    job_description: str | None = Field(default=None, max_length=50_000)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @model_validator(mode="after")
    def _non_nullable(self) -> ApplicationUpdate:
        for name in ("company", "role_title", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class StatusUpdate(BaseModel):
    status: ApplicationStatus
    note: str | None = Field(default=None, max_length=2_000)


class ApplicationOut(ORMModel):
    id: uuid.UUID
    company: str
    role_title: str
    job_url: str | None
    location: str | None
    salary_min: int | None
    salary_max: int | None
    currency: str | None
    status: ApplicationStatus
    applied_at: datetime | None
    follow_up_at: datetime | None
    follow_up_flagged_at: datetime | None
    notes: str | None
    job_description: str | None
    created_at: datetime
    updated_at: datetime


class ApplicationEventOut(ORMModel):
    id: int
    event_type: EventType
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus | None
    note: str | None
    occurred_at: datetime


class ApplicationSort(StrEnum):
    CREATED_DESC = "-created_at"
    CREATED_ASC = "created_at"
    UPDATED_DESC = "-updated_at"
    APPLIED_DESC = "-applied_at"
    APPLIED_ASC = "applied_at"
    COMPANY_ASC = "company"
    COMPANY_DESC = "-company"
    FOLLOW_UP_ASC = "follow_up_at"
    RELEVANCE = "relevance"


class ApplicationFilters(BaseModel):
    status: list[ApplicationStatus] | None = None
    company: str | None = None
    q: str | None = Field(default=None, max_length=200)
    applied_from: datetime | None = None
    applied_to: datetime | None = None
    sort: ApplicationSort = ApplicationSort.CREATED_DESC
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

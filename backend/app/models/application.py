from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import ApplicationStatus

application_status_enum = Enum(
    ApplicationStatus,
    name="application_status",
    values_callable=lambda e: [m.value for m in e],
)

SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('english', coalesce(company, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(role_title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(location, '')), 'B') || "
    "setweight(to_tsvector('english', coalesce(notes, '')), 'C')"
)


class Application(TimestampMixin, Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    role_title: Mapped[str] = mapped_column(String(200), nullable=False)
    job_url: Mapped[str | None] = mapped_column(String(2048))
    location: Mapped[str | None] = mapped_column(String(200))
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[ApplicationStatus] = mapped_column(
        application_status_enum, nullable=False, server_default=ApplicationStatus.WISHLIST.value
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by the scheduled "flag overdue follow-ups" job; cleared when follow_up_at changes.
    follow_up_flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    job_description: Mapped[str | None] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR_SQL, persisted=True), deferred=True
    )

    __table_args__ = (
        CheckConstraint("salary_min IS NULL OR salary_min >= 0", name="salary_min_non_negative"),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max",
            name="salary_range_valid",
        ),
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency_iso4217"),
        Index("ix_applications_user_id_status", "user_id", "status"),
        Index("ix_applications_user_id_created_at", "user_id", "created_at"),
        Index("ix_applications_user_id_applied_at", "user_id", "applied_at"),
        Index(
            "ix_applications_follow_up_at",
            "follow_up_at",
            postgresql_where=text("follow_up_at IS NOT NULL"),
        ),
        Index("ix_applications_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_applications_company_trgm",
            "company",
            postgresql_using="gin",
            postgresql_ops={"company": "gin_trgm_ops"},
        ),
    )

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.application import application_status_enum
from app.models.enums import ApplicationStatus, EventType

event_type_enum = Enum(
    EventType, name="application_event_type", values_callable=lambda e: [m.value for m in e]
)


class ApplicationEvent(Base):
    """Append-only timeline of an application (creation, status changes, overdue flags)."""

    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[EventType] = mapped_column(event_type_enum, nullable=False)
    from_status: Mapped[ApplicationStatus | None] = mapped_column(application_status_enum)
    to_status: Mapped[ApplicationStatus | None] = mapped_column(application_status_enum)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_application_events_application_id_occurred_at", "application_id", "occurred_at"),
    )

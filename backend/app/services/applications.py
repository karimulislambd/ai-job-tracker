"""Application use-cases. Status changes always append to the event log in the same
transaction, so the timeline can never drift from the current status."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import Cache
from app.core.errors import NotFoundError, ValidationFailedError
from app.models import Application, ApplicationEvent, ApplicationStatus, EventType
from app.repositories.applications import ApplicationRepository
from app.schemas.application import (
    ApplicationCreate,
    ApplicationFilters,
    ApplicationUpdate,
)


def stats_cache_key(user_id: uuid.UUID) -> str:
    return f"stats:{user_id}"


class ApplicationService:
    def __init__(self, session: AsyncSession, cache: Cache) -> None:
        self.session = session
        self.cache = cache
        self.repo = ApplicationRepository(session)

    async def _invalidate(self, user_id: uuid.UUID) -> None:
        await self.cache.delete(stats_cache_key(user_id))

    async def get(self, user_id: uuid.UUID, application_id: uuid.UUID) -> Application:
        app = await self.repo.get(user_id, application_id)
        if app is None:
            # 404 rather than 403: never reveal that another user's resource exists.
            raise NotFoundError("Application not found")
        return app

    async def search(
        self, user_id: uuid.UUID, filters: ApplicationFilters
    ) -> tuple[list[Application], int]:
        return await self.repo.search(user_id, filters)

    async def create(self, user_id: uuid.UUID, data: ApplicationCreate) -> Application:
        values = data.model_dump()
        values["job_url"] = str(data.job_url) if data.job_url else None
        if data.status != ApplicationStatus.WISHLIST and values["applied_at"] is None:
            values["applied_at"] = datetime.now(UTC)
        app = await self.repo.add(Application(user_id=user_id, **values))
        await self.repo.add_event(
            ApplicationEvent(
                application_id=app.id, event_type=EventType.CREATED, to_status=app.status
            )
        )
        await self.session.commit()
        await self.session.refresh(app)
        await self._invalidate(user_id)
        return app

    async def update(
        self, user_id: uuid.UUID, application_id: uuid.UUID, data: ApplicationUpdate
    ) -> Application:
        app = await self.repo.get(user_id, application_id, for_update=True)
        if app is None:
            raise NotFoundError("Application not found")
        changes = data.model_dump(exclude_unset=True)
        new_status = changes.pop("status", None)
        if "job_url" in changes:
            changes["job_url"] = str(data.job_url) if data.job_url else None
        if "follow_up_at" in changes and changes["follow_up_at"] != app.follow_up_at:
            changes["follow_up_flagged_at"] = None
        for key, value in changes.items():
            setattr(app, key, value)
        smin = app.salary_min
        smax = app.salary_max
        if smin is not None and smax is not None and smin > smax:
            raise ValidationFailedError("salary_min must be <= salary_max")
        if new_status is not None:
            self._transition(app, ApplicationStatus(new_status), note=None)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(app)
        await self._invalidate(user_id)
        return app

    async def change_status(
        self,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        status: ApplicationStatus,
        note: str | None = None,
    ) -> Application:
        app = await self.repo.get(user_id, application_id, for_update=True)
        if app is None:
            raise NotFoundError("Application not found")
        self._transition(app, status, note=note)
        await self.session.commit()
        await self.session.refresh(app)
        await self._invalidate(user_id)
        return app

    def _transition(self, app: Application, status: ApplicationStatus, note: str | None) -> None:
        if app.status == status:
            return  # idempotent: no event for a no-op
        previous = app.status
        app.status = status
        if status != ApplicationStatus.WISHLIST and app.applied_at is None:
            app.applied_at = datetime.now(UTC)
        self.session.add(
            ApplicationEvent(
                application_id=app.id,
                event_type=EventType.STATUS_CHANGED,
                from_status=previous,
                to_status=status,
                note=note,
            )
        )

    async def delete(self, user_id: uuid.UUID, application_id: uuid.UUID) -> None:
        app = await self.get(user_id, application_id)
        await self.repo.delete(app)
        await self.session.commit()
        await self._invalidate(user_id)

    async def events(self, user_id: uuid.UUID, application_id: uuid.UUID) -> list[ApplicationEvent]:
        await self.get(user_id, application_id)  # 404 for foreign/missing applications
        return await self.repo.list_events(user_id, application_id)

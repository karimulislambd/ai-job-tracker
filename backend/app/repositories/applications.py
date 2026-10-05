"""Application data access. Every query is scoped by ``user_id`` — there is no
unscoped "get by id" on purpose, so cross-tenant reads are impossible by construction.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models import Application, ApplicationEvent
from app.schemas.application import ApplicationFilters, ApplicationSort


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, user_id: uuid.UUID, application_id: uuid.UUID, *, for_update: bool = False
    ) -> Application | None:
        stmt = select(Application).where(
            Application.id == application_id, Application.user_id == user_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, application: Application) -> Application:
        self.session.add(application)
        await self.session.flush()
        return application

    async def delete(self, application: Application) -> None:
        await self.session.delete(application)
        await self.session.flush()

    def _filtered(self, user_id: uuid.UUID, f: ApplicationFilters) -> tuple[Select[Any], Any]:
        conditions: list[ColumnElement[bool]] = [Application.user_id == user_id]
        rank = None
        if f.status:
            conditions.append(Application.status.in_(f.status))
        if f.company:
            conditions.append(
                Application.company.ilike(f"%{_escape_like(f.company.strip())}%", escape="\\")
            )
        if f.applied_from:
            conditions.append(Application.applied_at >= f.applied_from)
        if f.applied_to:
            conditions.append(Application.applied_at <= f.applied_to)
        if f.q and f.q.strip():
            q = f.q.strip()
            tsquery = func.websearch_to_tsquery("english", q)
            pattern = f"%{_escape_like(q)}%"
            # Full-text search over the weighted generated tsvector, plus substring
            # matching so partial words ("goo" -> Google) still hit.
            conditions.append(
                or_(
                    Application.search_vector.op("@@")(tsquery),
                    Application.company.ilike(pattern, escape="\\"),
                    Application.role_title.ilike(pattern, escape="\\"),
                )
            )
            rank = func.ts_rank(Application.search_vector, tsquery)
        return select(Application).where(*conditions), rank

    async def search(
        self, user_id: uuid.UUID, filters: ApplicationFilters
    ) -> tuple[list[Application], int]:
        stmt, rank = self._filtered(user_id, filters)
        total = await self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        order: list[Any]
        match filters.sort:
            case ApplicationSort.CREATED_ASC:
                order = [Application.created_at.asc()]
            case ApplicationSort.UPDATED_DESC:
                order = [Application.updated_at.desc()]
            case ApplicationSort.APPLIED_DESC:
                order = [Application.applied_at.desc().nulls_last()]
            case ApplicationSort.APPLIED_ASC:
                order = [Application.applied_at.asc().nulls_last()]
            case ApplicationSort.COMPANY_ASC:
                order = [func.lower(Application.company).asc()]
            case ApplicationSort.COMPANY_DESC:
                order = [func.lower(Application.company).desc()]
            case ApplicationSort.FOLLOW_UP_ASC:
                order = [Application.follow_up_at.asc().nulls_last()]
            case ApplicationSort.RELEVANCE if rank is not None:
                order = [rank.desc()]
            case _:
                order = [Application.created_at.desc()]
        # Tie-breaker on the PK makes pagination deterministic.
        stmt = stmt.order_by(*order, Application.id).limit(filters.limit).offset(filters.offset)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), int(total or 0)

    async def add_event(self, event: ApplicationEvent) -> ApplicationEvent:
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_events(
        self, user_id: uuid.UUID, application_id: uuid.UUID
    ) -> list[ApplicationEvent]:
        stmt = (
            select(ApplicationEvent)
            .join(Application, Application.id == ApplicationEvent.application_id)
            .where(Application.user_id == user_id, Application.id == application_id)
            .order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

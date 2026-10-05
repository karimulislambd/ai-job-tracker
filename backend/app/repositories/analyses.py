from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIAnalysis, Application


class AnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user(self, user_id: uuid.UUID, analysis_id: uuid.UUID) -> AIAnalysis | None:
        # Ownership is derived through the parent application.
        stmt = (
            select(AIAnalysis)
            .join(Application, Application.id == AIAnalysis.application_id)
            .where(AIAnalysis.id == analysis_id, Application.user_id == user_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_application(
        self, user_id: uuid.UUID, application_id: uuid.UUID, limit: int = 20
    ) -> list[AIAnalysis]:
        stmt = (
            select(AIAnalysis)
            .join(Application, Application.id == AIAnalysis.application_id)
            .where(Application.id == application_id, Application.user_id == user_id)
            .order_by(AIAnalysis.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_unscoped(self, analysis_id: uuid.UUID) -> AIAnalysis | None:
        """Worker-only: background jobs act on behalf of the owner recorded in the row."""
        return await self.session.get(AIAnalysis, analysis_id)

    async def add(self, analysis: AIAnalysis) -> AIAnalysis:
        self.session.add(analysis)
        await self.session.flush()
        return analysis

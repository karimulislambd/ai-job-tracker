from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Resume


class ResumeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID, resume_id: uuid.UUID) -> Resume | None:
        result = await self.session.execute(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_active(self, user_id: uuid.UUID) -> Resume | None:
        result = await self.session.execute(
            select(Resume).where(Resume.user_id == user_id, Resume.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Resume]:
        result = await self.session.execute(
            select(Resume).where(Resume.user_id == user_id).order_by(Resume.version.desc())
        )
        return list(result.scalars().all())

    async def next_version(self, user_id: uuid.UUID) -> int:
        current = await self.session.scalar(
            select(func.coalesce(func.max(Resume.version), 0)).where(Resume.user_id == user_id)
        )
        return int(current or 0) + 1

    async def deactivate_all(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Resume)
            .where(Resume.user_id == user_id, Resume.is_active.is_(True))
            .values(is_active=False)
        )

    async def add(self, resume: Resume) -> Resume:
        self.session.add(resume)
        await self.session.flush()
        return resume

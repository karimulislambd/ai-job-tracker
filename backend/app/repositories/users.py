from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_demo_template(self) -> User | None:
        result = await self.session.execute(
            select(User).where(User.is_demo_template.is_(True)).limit(1)
        )
        return result.scalar_one_or_none()

    async def delete_expired_demo_users(self, now: datetime) -> int:
        """Delete expired demo users; FK ``ON DELETE CASCADE`` removes all their data."""
        result = await self.session.execute(
            delete(User)
            .where(User.is_demo.is_(True), User.demo_expires_at < now)
            .returning(User.id)
        )
        return len(result.scalars().all())

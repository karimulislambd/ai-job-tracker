"""Scheduled maintenance jobs (enqueued periodically by the scheduler loop)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.users import UserRepository

logger = logging.getLogger(__name__)

FLAG_OVERDUE_JOB = "flag_overdue_follow_ups"
CLEANUP_DEMO_JOB = "cleanup_demo_users"

# One statement: flag every newly-overdue application across all users and append a
# timeline event for each, atomically (data-modifying CTE).
_FLAG_OVERDUE_SQL = text(
    """
    WITH flagged AS (
        UPDATE applications
           SET follow_up_flagged_at = :now
         WHERE follow_up_at < :now
           AND follow_up_flagged_at IS NULL
           AND status IN ('wishlist', 'applied', 'interviewing', 'offer')
        RETURNING id, follow_up_at
    )
    INSERT INTO application_events (application_id, event_type, note, occurred_at)
    SELECT id, 'follow_up_overdue',
           'Follow-up was due ' || to_char(follow_up_at AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
           :now
    FROM flagged
    RETURNING application_id
    """
)


async def flag_overdue_follow_ups(
    session: AsyncSession, payload: dict[str, Any] | None = None, now: datetime | None = None
) -> int:
    result = await session.execute(_FLAG_OVERDUE_SQL, {"now": now or datetime.now(UTC)})
    count = len(result.all())
    await session.commit()
    if count:
        logger.info("follow_ups_flagged", extra={"count": count})
    return count


async def cleanup_demo_users(
    session: AsyncSession, payload: dict[str, Any] | None = None, now: datetime | None = None
) -> int:
    count = await UserRepository(session).delete_expired_demo_users(now or datetime.now(UTC))
    await session.commit()
    if count:
        logger.info("demo_users_deleted", extra={"count": count})
    return count

"""Postgres job queue primitives.

Claiming uses ``SELECT ... FOR UPDATE SKIP LOCKED`` inside a single ``UPDATE ... RETURNING``,
so N workers can poll concurrently and each runnable row is handed to exactly one of
them without blocking on rows another worker is already claiming.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobStatus

MAX_ERROR_LEN = 4_000


def backoff_delay(attempts: int, base_seconds: float, cap_seconds: float = 3_600) -> float:
    """Exponential backoff with full jitter: uniform(0.5, 1.0) * base * 2^(attempts-1)."""
    exp = min(base_seconds * (2 ** max(attempts - 1, 0)), cap_seconds)
    return float(exp * (0.5 + random.random() / 2))  # noqa: S311 - jitter, not crypto


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any] | None = None,
        *,
        run_after: datetime | None = None,
        max_attempts: int = 4,
        dedupe_key: str | None = None,
    ) -> Job | None:
        """Insert a job. With ``dedupe_key``, returns ``None`` if an identical job is
        already queued/running (enforced by a partial unique index, so it is race-free)."""
        values: dict[str, Any] = {
            "type": job_type,
            "payload": payload or {},
            "max_attempts": max_attempts,
            "dedupe_key": dedupe_key,
        }
        if run_after is not None:
            values["run_after"] = run_after
        stmt = insert(Job).values(**values)
        if dedupe_key is not None:
            stmt = stmt.on_conflict_do_nothing(
                index_elements=[Job.dedupe_key],
                index_where=text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
            )
        result = await self.session.execute(stmt.returning(Job))
        return result.scalar_one_or_none()

    async def claim(self, worker_id: str, limit: int = 1) -> list[Job]:
        runnable = (
            select(Job.id)
            .where(Job.status == JobStatus.QUEUED, Job.run_after <= func.now())
            .order_by(Job.run_after, Job.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(Job)
            .where(Job.id.in_(runnable))
            .values(
                status=JobStatus.RUNNING,
                attempts=Job.attempts + 1,
                locked_at=func.now(),
                locked_by=worker_id,
            )
            .returning(Job)
            # Refresh any instances already in the identity map with the RETURNING values.
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        result = await self.session.execute(stmt)
        # UPDATE ... RETURNING doesn't preserve the subquery's order; restore FIFO.
        return sorted(result.scalars().all(), key=lambda j: (j.run_after, j.id))

    async def complete(self, job_id: int) -> None:
        await self.session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=JobStatus.SUCCEEDED, finished_at=func.now(), locked_at=None, locked_by=None
            )
            .execution_options(synchronize_session=False)
        )

    async def fail(
        self,
        job: Job,
        error: str,
        *,
        base_backoff_seconds: float,
        retryable: bool = True,
    ) -> JobStatus:
        """Record a failure. Re-queues with backoff, or marks the job permanently failed.

        Times come from the database clock (``now()``), the same clock ``claim`` compares
        ``run_after`` against, so app/DB clock skew can't stall or rush retries.
        """
        terminal = (not retryable) or job.attempts >= job.max_attempts
        values: dict[str, Any] = {
            "last_error": error[:MAX_ERROR_LEN],
            "locked_at": None,
            "locked_by": None,
        }
        if terminal:
            values.update(status=JobStatus.FAILED, finished_at=func.now())
        else:
            delay = backoff_delay(job.attempts, base_backoff_seconds)
            values.update(status=JobStatus.QUEUED, run_after=func.now() + timedelta(seconds=delay))
        await self.session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return JobStatus.FAILED if terminal else JobStatus.QUEUED

    async def requeue_stale(self, lock_timeout_seconds: int) -> int:
        """Recover jobs whose worker died mid-run (lock older than the timeout)."""
        result = await self.session.execute(
            update(Job)
            .where(
                Job.status == JobStatus.RUNNING,
                Job.locked_at < func.now() - timedelta(seconds=lock_timeout_seconds),
            )
            .values(
                status=JobStatus.QUEUED,
                locked_at=None,
                locked_by=None,
                last_error="lock expired: worker presumed dead",
            )
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        )
        return len(result.scalars().all())

    async def get(self, job_id: int) -> Job | None:
        return await self.session.get(Job, job_id, populate_existing=True)

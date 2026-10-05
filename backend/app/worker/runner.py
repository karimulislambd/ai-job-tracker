"""Queue worker + periodic scheduler.

* ``Worker.run_once`` claims a batch in a short transaction (SKIP LOCKED), then runs each
  job in its own session so a slow LLM call never holds a row lock or a transaction open.
* Failures are retried with exponential backoff up to ``max_attempts``; the final error is
  kept in ``jobs.last_error``. Jobs whose worker died are re-queued after a lock timeout.
* ``Scheduler`` enqueues recurring maintenance jobs with a dedupe key, so running several
  API instances never double-schedules them.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import traceback
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import Job, JobStatus
from app.repositories.jobs import JobRepository
from app.services.maintenance import CLEANUP_DEMO_JOB, FLAG_OVERDUE_JOB
from app.worker.handlers import JobHandler

logger = logging.getLogger("app.worker")


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class Worker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        handlers: dict[str, JobHandler],
        settings: Settings,
        worker_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.handlers = handlers
        self.settings = settings
        self.worker_id = worker_id or default_worker_id()

    async def claim(self, limit: int) -> list[Job]:
        async with self.session_factory() as session:
            jobs = await JobRepository(session).claim(self.worker_id, limit=limit)
            await session.commit()
            return jobs

    async def run_once(self, limit: int | None = None) -> int:
        """Claim and process up to ``limit`` jobs concurrently. Returns the number processed."""
        jobs = await self.claim(limit or self.settings.worker_concurrency)
        if jobs:
            await asyncio.gather(*(self.process(job) for job in jobs))
        return len(jobs)

    async def process(self, job: Job) -> JobStatus:
        handler = self.handlers.get(job.type)
        log_ctx = {"job_id": job.id, "job_type": job.type, "attempt": job.attempts}
        if handler is None:
            return await self._record_failure(
                job, None, f"no handler registered for job type {job.type!r}", retryable=False
            )
        started = asyncio.get_running_loop().time()
        try:
            async with self.session_factory() as session:
                await handler.run(session, job.payload)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("job_failed", extra={**log_ctx, "error": error})
            logger.debug("job_traceback", extra={**log_ctx, "tb": traceback.format_exc()})
            return await self._record_failure(
                job, handler, error, retryable=handler.is_retryable(exc)
            )
        async with self.session_factory() as session:
            await JobRepository(session).complete(job.id)
            await session.commit()
        logger.info(
            "job_succeeded",
            extra={
                **log_ctx,
                "duration_ms": round((asyncio.get_running_loop().time() - started) * 1000),
            },
        )
        return JobStatus.SUCCEEDED

    async def _record_failure(
        self, job: Job, handler: JobHandler | None, error: str, *, retryable: bool
    ) -> JobStatus:
        async with self.session_factory() as session:
            status = await JobRepository(session).fail(
                job,
                error,
                base_backoff_seconds=self.settings.job_backoff_base_seconds,
                retryable=retryable,
            )
            await session.commit()
        if handler is not None and handler.on_failure is not None:
            try:
                async with self.session_factory() as session:
                    await handler.on_failure(
                        session, job.payload, error, status == JobStatus.FAILED
                    )
            except Exception:
                logger.exception("job_failure_hook_error", extra={"job_id": job.id})
        return status

    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("worker_started", extra={"worker_id": self.worker_id})
        while not stop.is_set():
            try:
                processed = await self.run_once()
            except Exception:
                logger.exception("worker_loop_error")
                processed = 0
            if processed == 0:
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        stop.wait(), timeout=self.settings.worker_poll_interval_seconds
                    )
        logger.info("worker_stopped", extra={"worker_id": self.worker_id})


class Scheduler:
    """Enqueues periodic maintenance jobs and recovers stale locks."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings

    async def tick(self) -> None:
        async with self.session_factory() as session:
            jobs = JobRepository(session)
            recovered = await jobs.requeue_stale(self.settings.job_lock_timeout_seconds)
            await jobs.enqueue(FLAG_OVERDUE_JOB, dedupe_key=FLAG_OVERDUE_JOB, max_attempts=3)
            if self.settings.demo_enabled:
                await jobs.enqueue(CLEANUP_DEMO_JOB, dedupe_key=CLEANUP_DEMO_JOB, max_attempts=3)
            await session.commit()
        if recovered:
            logger.warning("stale_jobs_requeued", extra={"count": recovered})

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("scheduler_tick_error", extra={"at": datetime.now(UTC)})
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    stop.wait(), timeout=self.settings.scheduler_interval_seconds
                )

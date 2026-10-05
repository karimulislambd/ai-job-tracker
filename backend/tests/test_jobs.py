"""Job queue: enqueue/claim/complete, retries with backoff, terminal failure, dedupe,
stale-lock recovery and real multi-connection SKIP LOCKED concurrency."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import Job, JobStatus
from app.repositories.jobs import JobRepository, backoff_delay
from app.worker.handlers import JobHandler
from app.worker.runner import Scheduler, Worker


async def _reload(session: AsyncSession, job_id: int) -> Job:
    job = await JobRepository(session).get(job_id)
    assert job is not None
    return job


async def test_enqueue_claim_complete(db_session: AsyncSession) -> None:
    repo = JobRepository(db_session)
    job = await repo.enqueue("demo", {"x": 1})
    assert job is not None
    assert job.status == JobStatus.QUEUED
    assert job.attempts == 0

    claimed = await repo.claim("w1", limit=5)
    assert [j.id for j in claimed] == [job.id]
    assert claimed[0].status == JobStatus.RUNNING
    assert claimed[0].attempts == 1
    assert claimed[0].locked_by == "w1"
    assert claimed[0].locked_at is not None
    assert await repo.claim("w1") == []  # running jobs aren't claimable

    await repo.complete(job.id)
    done = await _reload(db_session, job.id)
    assert done.status == JobStatus.SUCCEEDED
    assert done.finished_at is not None
    assert done.locked_by is None


async def test_claim_respects_run_after_and_fifo_order(db_session: AsyncSession) -> None:
    repo = JobRepository(db_session)
    future = await repo.enqueue("t", run_after=datetime.now(UTC) + timedelta(hours=1))
    first = await repo.enqueue("t", run_after=datetime.now(UTC) - timedelta(minutes=2))
    second = await repo.enqueue("t", run_after=datetime.now(UTC) - timedelta(minutes=1))
    assert future and first and second
    claimed = await repo.claim("w", limit=10)
    assert [j.id for j in claimed] == [first.id, second.id]


async def test_fail_requeues_with_backoff_then_fails_terminally(db_session: AsyncSession) -> None:
    repo = JobRepository(db_session)
    job = await repo.enqueue("t", max_attempts=2)
    assert job

    (claimed,) = await repo.claim("w")
    status = await repo.fail(claimed, "boom 1", base_backoff_seconds=60)
    assert status == JobStatus.QUEUED
    retried = await _reload(db_session, job.id)
    assert retried.status == JobStatus.QUEUED
    assert retried.last_error == "boom 1"
    db_now = await db_session.scalar(text("SELECT now()"))
    # First retry waits 30-60s (base 60 * 2^0 with jitter in [0.5, 1.0]).
    delay = (retried.run_after - db_now).total_seconds()
    assert 29 <= delay <= 61
    assert await repo.claim("w") == []  # not yet runnable

    retried.run_after = db_now - timedelta(seconds=1)
    await db_session.flush()
    (claimed,) = await repo.claim("w")
    assert claimed.attempts == 2
    status = await repo.fail(claimed, "boom 2" + "x" * 10_000, base_backoff_seconds=60)
    assert status == JobStatus.FAILED
    failed = await _reload(db_session, job.id)
    assert failed.status == JobStatus.FAILED
    assert failed.finished_at is not None
    assert failed.last_error is not None
    assert failed.last_error.startswith("boom 2")
    assert len(failed.last_error) == 4_000  # truncated


async def test_non_retryable_failure_is_terminal(db_session: AsyncSession) -> None:
    repo = JobRepository(db_session)
    await repo.enqueue("t", max_attempts=5)
    (claimed,) = await repo.claim("w")
    assert await repo.fail(claimed, "fatal", base_backoff_seconds=1, retryable=False) == (
        JobStatus.FAILED
    )


def test_backoff_is_exponential_with_jitter_and_capped() -> None:
    for attempts, lo, hi in [(1, 2.5, 5), (2, 5, 10), (3, 10, 20), (4, 20, 40)]:
        samples = [backoff_delay(attempts, 5) for _ in range(50)]
        assert all(lo <= s <= hi for s in samples)
    assert backoff_delay(50, 5, cap_seconds=100) <= 100


async def test_dedupe_key_allows_one_active_job(db_session: AsyncSession) -> None:
    repo = JobRepository(db_session)
    a = await repo.enqueue("cron", dedupe_key="cron")
    b = await repo.enqueue("cron", dedupe_key="cron")
    assert a is not None
    assert b is None
    (claimed,) = await repo.claim("w")
    assert await repo.enqueue("cron", dedupe_key="cron") is None  # still running
    await repo.complete(claimed.id)
    assert await repo.enqueue("cron", dedupe_key="cron") is not None  # finished -> allowed


async def test_stale_running_jobs_are_requeued(db_session: AsyncSession) -> None:
    repo = JobRepository(db_session)
    job = await repo.enqueue("t")
    assert job
    (claimed,) = await repo.claim("dead-worker")
    assert await repo.requeue_stale(lock_timeout_seconds=300) == 0
    claimed.locked_at = datetime.now(UTC) - timedelta(minutes=10)
    await db_session.flush()
    assert await repo.requeue_stale(lock_timeout_seconds=300) == 1
    recovered = await _reload(db_session, job.id)
    assert recovered.status == JobStatus.QUEUED
    assert recovered.locked_by is None
    assert "lock expired" in (recovered.last_error or "")


async def test_worker_handles_unknown_type_and_handler_errors(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings, db_session: AsyncSession
) -> None:
    calls: list[tuple[str, bool]] = []

    async def explode(session: AsyncSession, payload: dict[str, Any]) -> None:
        raise ValueError("kaboom")

    async def on_failure(
        session: AsyncSession, payload: dict[str, Any], err: str, terminal: bool
    ) -> None:
        calls.append((err, terminal))

    async def broken_hook(*args: Any) -> None:
        raise RuntimeError("hook broke")

    handlers = {
        "explode": JobHandler(run=explode, on_failure=on_failure),
        "explode_bad_hook": JobHandler(run=explode, on_failure=broken_hook),
    }
    worker = Worker(session_factory, handlers, settings, worker_id="w")
    repo = JobRepository(db_session)
    unknown = await repo.enqueue("nope")
    exploding = await repo.enqueue("explode", max_attempts=1)
    bad_hook = await repo.enqueue("explode_bad_hook", max_attempts=1)
    await db_session.commit()
    assert unknown and exploding and bad_hook

    for _ in range(3):
        await worker.run_once(limit=1)

    assert (await _reload(db_session, unknown.id)).status == JobStatus.FAILED
    assert "no handler" in ((await _reload(db_session, unknown.id)).last_error or "")
    assert (await _reload(db_session, exploding.id)).status == JobStatus.FAILED
    assert calls == [("ValueError: kaboom", True)]
    # A failing hook doesn't break the worker; the job is still marked failed.
    assert (await _reload(db_session, bad_hook.id)).status == JobStatus.FAILED


async def test_worker_run_forever_stops_cleanly(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings, db_session: AsyncSession
) -> None:
    done = asyncio.Event()

    async def ok(session: AsyncSession, payload: dict[str, Any]) -> None:
        done.set()

    fast = settings.model_copy(update={"worker_poll_interval_seconds": 0.05})
    worker = Worker(session_factory, {"ok": JobHandler(run=ok)}, fast)
    await JobRepository(db_session).enqueue("ok")
    await db_session.commit()
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run_forever(stop))
    await asyncio.wait_for(done.wait(), timeout=5)
    stop.set()
    await asyncio.wait_for(task, timeout=5)


async def test_scheduler_tick_enqueues_maintenance_once(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings, db_session: AsyncSession
) -> None:
    scheduler = Scheduler(session_factory, settings)
    await scheduler.tick()
    await scheduler.tick()  # deduplicated while the first ones are still queued
    types = sorted((await db_session.execute(select(Job.type))).scalars().all())
    assert types == ["cleanup_demo_users", "flag_overdue_follow_ups"]


async def test_scheduler_run_forever_survives_errors(settings: Settings) -> None:
    class Boom:
        def __call__(self) -> Any:
            raise RuntimeError("db down")

    fast = settings.model_copy(update={"scheduler_interval_seconds": 0})
    scheduler = Scheduler(Boom(), fast)  # type: ignore[arg-type]
    stop = asyncio.Event()
    task = asyncio.create_task(scheduler.run_forever(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)


# --------------------------------------------------------------------------- concurrency


@pytest.fixture
async def committed(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Real, independently-committing sessions on separate connections."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with factory() as s:
        await s.execute(delete(Job).where(Job.type.like("conc-%")))
        await s.commit()


async def test_skip_locked_lets_a_second_worker_bypass_a_locked_row(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    async with committed() as s:
        repo = JobRepository(s)
        first = await repo.enqueue("conc-a", run_after=datetime.now(UTC) - timedelta(minutes=1))
        second = await repo.enqueue("conc-a", run_after=datetime.now(UTC) - timedelta(seconds=30))
        await s.commit()
    assert first and second

    async with committed() as s1, committed() as s2:
        # Worker 1 claims the oldest row and keeps its transaction (row lock) open.
        (got1,) = await JobRepository(s1).claim("w1", limit=1)
        # Worker 2 does not block on that lock: it skips it and gets the next row.
        (got2,) = await asyncio.wait_for(JobRepository(s2).claim("w2", limit=1), timeout=5)
        assert got1.id == first.id
        assert got2.id == second.id
        await s1.commit()
        await s2.commit()


async def test_concurrent_workers_never_double_claim(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    n_jobs, n_workers = 60, 6
    async with committed() as s:
        repo = JobRepository(s)
        ids = set()
        for i in range(n_jobs):
            job = await repo.enqueue(
                "conc-b", {"i": i}, run_after=datetime.now(UTC) - timedelta(minutes=1)
            )
            assert job
            ids.add(job.id)
        await s.commit()

    claims: dict[str, list[int]] = {}

    async def worker(name: str) -> None:
        claims[name] = []
        while True:
            async with committed() as s:
                batch = await JobRepository(s).claim(name, limit=3)
                await asyncio.sleep(0.001)  # hold the lock briefly to force overlap
                await s.commit()
            batch = [j for j in batch if j.type == "conc-b"]
            if not batch:
                return
            claims[name] += [j.id for j in batch]

    await asyncio.gather(*(worker(f"w{i}") for i in range(n_workers)))
    all_claimed = [jid for c in claims.values() for jid in c]
    assert len(all_claimed) == n_jobs  # no job claimed twice
    assert set(all_claimed) == ids  # and none left behind
    assert sum(1 for c in claims.values() if c) > 1  # work was actually shared

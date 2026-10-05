"""Job type → handler registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import analysis, maintenance
from app.services.llm import LLMClient

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[object]]
FailureHook = Callable[[AsyncSession, dict[str, Any], str, bool], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class JobHandler:
    run: Handler
    on_failure: FailureHook | None = None
    is_retryable: Callable[[BaseException], bool] = lambda exc: True


def build_registry(llm: LLMClient) -> dict[str, JobHandler]:
    async def _analysis(session: AsyncSession, payload: dict[str, Any]) -> None:
        await analysis.run_analysis_job(session, payload, llm)

    return {
        analysis.JOB_TYPE: JobHandler(
            run=_analysis,
            on_failure=analysis.on_analysis_failure,
            is_retryable=analysis.is_retryable,
        ),
        maintenance.FLAG_OVERDUE_JOB: JobHandler(run=maintenance.flag_overdue_follow_ups),
        maintenance.CLEANUP_DEMO_JOB: JobHandler(run=maintenance.cleanup_demo_users),
    }

"""AI match analysis: request (enqueue) and the background job handler that runs the LLM."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.models import AIAnalysis, AnalysisStatus, Application, Resume
from app.repositories.analyses import AnalysisRepository
from app.repositories.applications import ApplicationRepository
from app.repositories.jobs import JobRepository
from app.repositories.resumes import ResumeRepository
from app.schemas.analysis import MatchResult
from app.services.llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

JOB_TYPE = "ai_analysis"
MAX_JD_CHARS = 12_000
MAX_CV_CHARS = 12_000

SYSTEM_PROMPT = """You are an expert technical recruiter and career coach.
Compare the candidate's CV with the job description and respond with ONE JSON object only,
no markdown, matching exactly this schema:
{
  "match_score": integer 0-100 (how well the CV matches the role's requirements),
  "summary": string (2-3 sentences, plain, specific),
  "matched_skills": [string] (skills/technologies required by the job AND evidenced in the CV),
  "missing_skills": [string] (required or preferred by the job but NOT evidenced in the CV),
  "strengths": [string] (2-5 concrete strengths for this role),
  "gaps": [string] (0-5 concrete gaps or risks),
  "cv_bullet_suggestions": [string] (3-5 rewritten CV bullet points tailored to this job,
      action verb first, quantified where the CV supports it; never invent experience),
  "cover_letter": string (120-200 words, professional, specific to the company and role)
}
Base every claim strictly on the CV text. Do not fabricate employers, metrics or skills."""


class PermanentJobError(Exception):
    """A job failure that retrying cannot fix."""


class InvalidModelOutputError(Exception):
    """The model returned something that is not valid JSON for ``MatchResult``."""


def build_user_prompt(app: Application, resume: Resume) -> str:
    jd = (app.job_description or "")[:MAX_JD_CHARS]
    cv = resume.content_text[:MAX_CV_CHARS]
    return (
        f"Company: {app.company}\nRole: {app.role_title}\n"
        f"Location: {app.location or 'n/a'}\n\n"
        f"### JOB DESCRIPTION\n{jd}\n\n### CANDIDATE CV\n{cv}\n"
    )


def parse_model_output(content: str) -> MatchResult:
    text = content.strip()
    # Tolerate a fenced code block even though JSON mode should prevent it.
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidModelOutputError(f"model returned invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise InvalidModelOutputError("model returned JSON that is not an object")
    try:
        return MatchResult.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors()[:5])
        raise InvalidModelOutputError(f"model output failed schema validation: {fields}") from exc


class AnalysisService:
    def __init__(self, session: AsyncSession, max_attempts: int = 4) -> None:
        self.session = session
        self.max_attempts = max_attempts
        self.analyses = AnalysisRepository(session)
        self.applications = ApplicationRepository(session)
        self.resumes = ResumeRepository(session)
        self.jobs = JobRepository(session)

    async def request(self, user_id: uuid.UUID, application_id: uuid.UUID) -> AIAnalysis:
        app = await self.applications.get(user_id, application_id)
        if app is None:
            raise NotFoundError("Application not found")
        if not (app.job_description or "").strip():
            raise ValidationFailedError("Add a job description to this application first")
        resume = await self.resumes.get_active(user_id)
        if resume is None:
            raise ValidationFailedError("Upload a CV before requesting an analysis")

        analysis = await self.analyses.add(
            AIAnalysis(application_id=app.id, resume_id=resume.id, status=AnalysisStatus.QUEUED)
        )
        job = await self.jobs.enqueue(
            JOB_TYPE, {"analysis_id": str(analysis.id)}, max_attempts=self.max_attempts
        )
        assert job is not None
        analysis.job_id = job.id
        await self.session.commit()
        return analysis

    async def get(self, user_id: uuid.UUID, analysis_id: uuid.UUID) -> AIAnalysis:
        analysis = await self.analyses.get_for_user(user_id, analysis_id)
        if analysis is None:
            raise NotFoundError("Analysis not found")
        return analysis

    async def list_for_application(
        self, user_id: uuid.UUID, application_id: uuid.UUID
    ) -> list[AIAnalysis]:
        if await self.applications.get(user_id, application_id) is None:
            raise NotFoundError("Application not found")
        return await self.analyses.list_for_application(user_id, application_id)


# --------------------------------------------------------------------------- job handler


async def run_analysis_job(session: AsyncSession, payload: dict[str, Any], llm: LLMClient) -> None:
    analysis_id = uuid.UUID(str(payload["analysis_id"]))
    analyses = AnalysisRepository(session)
    analysis = await analyses.get_unscoped(analysis_id)
    if analysis is None:
        raise PermanentJobError(f"analysis {analysis_id} no longer exists")
    if analysis.status == AnalysisStatus.SUCCEEDED:
        return  # idempotent re-delivery

    app = await session.get(Application, analysis.application_id)
    resume = await session.get(Resume, analysis.resume_id) if analysis.resume_id else None
    if app is None or resume is None:
        raise PermanentJobError("application or resume was deleted")

    now = datetime.now(UTC)
    analysis.status = AnalysisStatus.RUNNING
    analysis.started_at = analysis.started_at or now
    analysis.error = None
    await session.commit()  # make "running" visible to pollers immediately

    response = await llm.complete_json(SYSTEM_PROMPT, build_user_prompt(app, resume))
    result = parse_model_output(response.content)

    finished = datetime.now(UTC)
    analysis.status = AnalysisStatus.SUCCEEDED
    analysis.result = result.model_dump()
    analysis.model = response.model
    analysis.prompt_tokens = response.prompt_tokens
    analysis.completion_tokens = response.completion_tokens
    analysis.completed_at = finished
    analysis.duration_ms = int((finished - (analysis.started_at or now)).total_seconds() * 1000)
    await session.commit()
    logger.info(
        "analysis_succeeded",
        extra={
            "analysis_id": str(analysis.id),
            "model": response.model,
            "llm_latency_ms": response.latency_ms,
            "match_score": result.match_score,
        },
    )


async def on_analysis_failure(
    session: AsyncSession, payload: dict[str, Any], error: str, terminal: bool
) -> None:
    analysis = await AnalysisRepository(session).get_unscoped(
        uuid.UUID(str(payload["analysis_id"]))
    )
    if analysis is None:
        return
    if terminal:
        analysis.status = AnalysisStatus.FAILED
        analysis.error = error
        analysis.completed_at = datetime.now(UTC)
    else:
        analysis.status = AnalysisStatus.QUEUED
        analysis.error = f"Retrying after error: {error}"
    await session.commit()


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, PermanentJobError):
        return False
    if isinstance(exc, LLMError):
        return exc.retryable
    return True  # includes InvalidModelOutputError: LLM output is non-deterministic

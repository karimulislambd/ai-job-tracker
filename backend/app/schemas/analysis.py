from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import AnalysisStatus
from app.schemas.common import ORMModel


def _clean_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        item = " ".join(str(v).split())
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item[:300])
    return out


class MatchResult(BaseModel):
    """The contract the LLM must satisfy. Anything else is rejected and retried."""

    model_config = ConfigDict(extra="ignore")

    match_score: int = Field(ge=0, le=100)
    summary: str = Field(default="", max_length=1_000)
    matched_skills: list[str] = Field(default_factory=list, max_length=40)
    missing_skills: list[str] = Field(default_factory=list, max_length=40)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    gaps: list[str] = Field(default_factory=list, max_length=10)
    cv_bullet_suggestions: list[str] = Field(min_length=3, max_length=5)
    cover_letter: str = Field(min_length=50, max_length=4_000)

    @field_validator(
        "matched_skills", "missing_skills", "strengths", "gaps", "cv_bullet_suggestions"
    )
    @classmethod
    def _normalise(cls, v: list[str]) -> list[str]:
        return _clean_list(v)


class AnalysisAccepted(BaseModel):
    analysis_id: uuid.UUID
    status: AnalysisStatus
    poll_url: str


class AnalysisOut(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    resume_id: uuid.UUID | None
    status: AnalysisStatus
    result: MatchResult | None
    error: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_ms: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

"""LLM client abstraction.

``GroqLLMClient`` is the production client. ``HeuristicLLMClient`` is a deterministic,
offline fallback used when ``GROQ_API_KEY`` is not configured (local dev, demos, CI) —
it produces output in exactly the same JSON contract via keyword overlap, so the rest of
the pipeline (queue, validation, storage, UI) is exercised identically.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


class LLMError(Exception):
    """Raised for provider failures. ``retryable`` tells the worker whether to back off."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMClient(Protocol):
    model: str

    async def complete_json(self, system: str, user: str) -> LLMResponse: ...


class GroqLLMClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        from groq import AsyncGroq

        self.model = model
        # Retries are owned by the job queue (with backoff + persisted errors), not the SDK.
        self._client = AsyncGroq(
            api_key=api_key, timeout=timeout, max_retries=0, http_client=http_client
        )

    async def complete_json(self, system: str, user: str) -> LLMResponse:
        import groq

        started = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=4_096,  # gpt-oss spends part of the budget on reasoning
            )
        except groq.RateLimitError as exc:
            raise LLMError(f"Groq rate limited: {exc}") from exc
        except groq.APIStatusError as exc:
            # 4xx (other than 429) won't succeed on retry; 5xx might.
            raise LLMError(
                f"Groq API error {exc.status_code}: {exc.message}",
                retryable=exc.status_code >= 500,
            ) from exc
        except (groq.APIConnectionError, groq.APITimeoutError) as exc:
            raise LLMError(f"Groq connection error: {exc}") from exc
        usage = resp.usage
        return LLMResponse(
            content=resp.choices[0].message.content or "",
            model=resp.model or self.model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


# A compact skills vocabulary for the offline heuristic.
_SKILLS = [
    "python",
    "fastapi",
    "django",
    "flask",
    "sqlalchemy",
    "postgresql",
    "postgres",
    "mysql",
    "sql",
    "redis",
    "celery",
    "kafka",
    "rabbitmq",
    "docker",
    "kubernetes",
    "terraform",
    "aws",
    "gcp",
    "azure",
    "ci/cd",
    "github actions",
    "rest",
    "graphql",
    "grpc",
    "microservices",
    "typescript",
    "javascript",
    "react",
    "next.js",
    "node.js",
    "go",
    "java",
    "rust",
    "c#",
    "linux",
    "git",
    "pytest",
    "testing",
    "mongodb",
    "elasticsearch",
    "airflow",
    "spark",
    "machine learning",
    "llm",
    "openai",
    "data modeling",
    "api design",
    "oauth",
    "jwt",
    "observability",
    "prometheus",
    "grafana",
    "system design",
    "agile",
    "tailwind",
]


def _find_skills(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for skill in _SKILLS:
        pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"
        if re.search(pattern, lowered):
            found.append(skill)
    return found


class HeuristicLLMClient:
    model = "heuristic-offline-v1"

    async def complete_json(self, system: str, user: str) -> LLMResponse:
        started = time.perf_counter()
        jd = user.split("### JOB DESCRIPTION", 1)[-1].split("### CANDIDATE CV", 1)[0]
        cv = user.split("### CANDIDATE CV", 1)[-1]
        jd_skills = _find_skills(jd)
        cv_skills = set(_find_skills(cv))
        matched = [s for s in jd_skills if s in cv_skills]
        missing = [s for s in jd_skills if s not in cv_skills]
        score = round(100 * len(matched) / len(jd_skills)) if jd_skills else 50
        score = max(5, min(95, score))
        title = "the role"
        m = re.search(r"Role:\s*(.+)", user)
        if m:
            title = m.group(1).strip()
        top = ", ".join(matched[:3]) or "backend engineering"
        payload = {
            "match_score": score,
            "summary": (
                f"Keyword-overlap estimate: {len(matched)} of {len(jd_skills)} skills found in "
                "the job description also appear in the CV. (Offline heuristic — set "
                "GROQ_API_KEY for a full LLM analysis.)"
            ),
            "matched_skills": matched,
            "missing_skills": missing,
            "strengths": [f"Hands-on experience with {s}" for s in matched[:4]]
            or ["General software engineering background"],
            "gaps": [f"No evidence of {s} in the CV" for s in missing[:4]],
            "cv_bullet_suggestions": [
                f"Lead with a quantified achievement that uses {top}.",
                "Describe the scale you worked at (requests/sec, rows, users) for one system.",
                "Show ownership: a feature you designed, shipped, tested and monitored end to end.",
            ]
            + ([f"Add a project or course that demonstrates {missing[0]}."] if missing else []),
            "cover_letter": (
                f"Dear Hiring Team,\n\nI am excited to apply for {title}. My experience with "
                f"{top} maps directly onto what you are looking for, and I enjoy building "
                "reliable, well-tested backend systems. I would welcome the chance to discuss "
                "how I can contribute to your team.\n\nBest regards"
            ),
        }
        content = json.dumps(payload)
        return LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=len(user) // 4,
            completion_tokens=len(content) // 4,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.groq_api_key:
        return GroqLLMClient(
            settings.groq_api_key, settings.groq_model, settings.llm_timeout_seconds
        )
    return HeuristicLLMClient()

"""AI match analysis: API contract, worker pipeline, output validation, Groq client.

The network is never called: the pipeline uses a scripted ``FakeLLM``, and the real Groq
SDK is exercised through an ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import AIAnalysis, Job, JobStatus
from app.services.analysis import (
    InvalidModelOutputError,
    is_retryable,
    parse_model_output,
)
from app.services.llm import (
    GroqLLMClient,
    HeuristicLLMClient,
    LLMError,
    build_llm_client,
)
from app.worker.handlers import build_registry
from app.worker.runner import Worker
from tests.conftest import JOB_DESCRIPTION, VALID_RESULT, AuthedUser, FakeLLM, create_application
from tests.pdf_utils import CV_LINES, make_pdf


@pytest.fixture
async def ready_app(client: httpx.AsyncClient, user: AuthedUser) -> dict[str, Any]:
    app = await create_application(
        client,
        user,
        company="Northwind",
        role_title="Backend Engineer",
        job_description=JOB_DESCRIPTION,
    )
    resp = await client.post(
        "/api/v1/resumes",
        files={"file": ("cv.pdf", make_pdf(CV_LINES), "application/pdf")},
        headers=user.headers,
    )
    assert resp.status_code == 201
    return app


def make_worker(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings, llm: Any
) -> Worker:
    fast = settings.model_copy(update={"job_backoff_base_seconds": 0.0})
    return Worker(session_factory, build_registry(llm), fast, worker_id="test-worker")


async def _request(client: httpx.AsyncClient, user: AuthedUser, app_id: str) -> dict[str, Any]:
    resp = await client.post(f"/api/v1/applications/{app_id}/analyze", headers=user.headers)
    assert resp.status_code == 202, resp.text
    return dict(resp.json())


async def _poll(client: httpx.AsyncClient, user: AuthedUser, analysis_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/v1/analyses/{analysis_id}", headers=user.headers)
    assert resp.status_code == 200
    return dict(resp.json())


async def test_analyze_returns_202_and_enqueues_job(
    client: httpx.AsyncClient, user: AuthedUser, ready_app: dict[str, Any], db_session: AsyncSession
) -> None:
    accepted = await _request(client, user, ready_app["id"])
    assert accepted["status"] == "queued"
    assert accepted["poll_url"] == f"/api/v1/analyses/{accepted['analysis_id']}"

    job = (await db_session.execute(select(Job))).scalar_one()
    assert job.type == "ai_analysis"
    assert job.payload == {"analysis_id": accepted["analysis_id"]}
    assert job.status == JobStatus.QUEUED

    polled = await _poll(client, user, accepted["analysis_id"])
    assert polled["status"] == "queued"
    assert polled["result"] is None


async def test_worker_completes_analysis(
    client: httpx.AsyncClient,
    user: AuthedUser,
    ready_app: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    accepted = await _request(client, user, ready_app["id"])
    llm = FakeLLM(json.dumps(VALID_RESULT))
    worker = make_worker(session_factory, settings, llm)

    assert await worker.run_once() == 1
    assert await worker.run_once() == 0  # nothing left

    result = await _poll(client, user, accepted["analysis_id"])
    assert result["status"] == "succeeded"
    assert result["result"]["match_score"] == 82
    # Normalised: case-insensitive de-duplication of skills.
    assert result["result"]["matched_skills"] == ["Python", "FastAPI", "PostgreSQL"]
    assert len(result["result"]["cv_bullet_suggestions"]) == 3
    assert result["model"] == "fake-llm"
    assert result["prompt_tokens"] == 120
    assert result["completion_tokens"] == 80
    assert result["duration_ms"] is not None
    assert result["started_at"] and result["completed_at"]

    # The prompt contains the job description and the CV text.
    _, prompt = llm.calls[0]
    assert "Northwind" in prompt
    assert "Kubernetes" in prompt
    assert "Taylor Tester" in prompt

    history = await client.get(
        f"/api/v1/applications/{ready_app['id']}/analyses", headers=user.headers
    )
    assert [a["id"] for a in history.json()] == [accepted["analysis_id"]]


async def test_invalid_json_is_retried_then_succeeds(
    client: httpx.AsyncClient,
    user: AuthedUser,
    ready_app: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    accepted = await _request(client, user, ready_app["id"])
    llm = FakeLLM("this is not json", json.dumps(VALID_RESULT))
    worker = make_worker(session_factory, settings, llm)

    await worker.run_once()
    mid = await _poll(client, user, accepted["analysis_id"])
    assert mid["status"] == "queued"
    assert "invalid JSON" in mid["error"]
    job = (
        await db_session.execute(select(Job).execution_options(populate_existing=True))
    ).scalar_one()
    assert job.status == JobStatus.QUEUED
    assert job.attempts == 1
    assert "invalid JSON" in (job.last_error or "")

    await worker.run_once()
    done = await _poll(client, user, accepted["analysis_id"])
    assert done["status"] == "succeeded"
    assert done["error"] is None


@pytest.mark.parametrize(
    "bad_output",
    [
        "not json at all",
        json.dumps([1, 2, 3]),
        json.dumps({**VALID_RESULT, "match_score": 150}),
        json.dumps({**VALID_RESULT, "cv_bullet_suggestions": ["only one"]}),
        json.dumps({k: v for k, v in VALID_RESULT.items() if k != "cover_letter"}),
    ],
    ids=["not-json", "json-array", "score-out-of-range", "too-few-bullets", "missing-field"],
)
async def test_persistently_invalid_output_fails_after_max_attempts(
    client: httpx.AsyncClient,
    user: AuthedUser,
    ready_app: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    db_session: AsyncSession,
    bad_output: str,
) -> None:
    accepted = await _request(client, user, ready_app["id"])
    worker = make_worker(session_factory, settings, FakeLLM(bad_output))
    for _ in range(settings.job_max_attempts):
        assert await worker.run_once() == 1
    assert await worker.run_once() == 0

    failed = await _poll(client, user, accepted["analysis_id"])
    assert failed["status"] == "failed"
    assert failed["result"] is None
    assert "InvalidModelOutputError" in failed["error"]
    job = (
        await db_session.execute(select(Job).execution_options(populate_existing=True))
    ).scalar_one()
    assert job.status == JobStatus.FAILED
    assert job.attempts == settings.job_max_attempts
    assert job.finished_at is not None


async def test_non_retryable_llm_error_fails_immediately(
    client: httpx.AsyncClient,
    user: AuthedUser,
    ready_app: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    accepted = await _request(client, user, ready_app["id"])
    llm = FakeLLM(LLMError("Groq API error 400: bad request", retryable=False))
    await make_worker(session_factory, settings, llm).run_once()
    failed = await _poll(client, user, accepted["analysis_id"])
    assert failed["status"] == "failed"
    assert "400" in failed["error"]


async def test_analysis_deleted_before_processing_is_permanent_failure(
    client: httpx.AsyncClient,
    user: AuthedUser,
    ready_app: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    await _request(client, user, ready_app["id"])
    # Deleting the application cascades to the analysis; the queued job remains.
    await client.delete(f"/api/v1/applications/{ready_app['id']}", headers=user.headers)
    await make_worker(session_factory, settings, FakeLLM(json.dumps(VALID_RESULT))).run_once()
    job = (
        await db_session.execute(select(Job).execution_options(populate_existing=True))
    ).scalar_one()
    assert job.status == JobStatus.FAILED
    assert job.attempts == 1
    assert "PermanentJobError" in (job.last_error or "")


async def test_redelivered_succeeded_analysis_is_idempotent(
    client: httpx.AsyncClient,
    user: AuthedUser,
    ready_app: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    db_session: AsyncSession,
) -> None:
    accepted = await _request(client, user, ready_app["id"])
    llm = FakeLLM(json.dumps(VALID_RESULT))
    worker = make_worker(session_factory, settings, llm)
    await worker.run_once()
    # Simulate at-least-once redelivery of the same job.
    job = (await db_session.execute(select(Job))).scalar_one()
    job.status = JobStatus.QUEUED
    await db_session.commit()
    await worker.run_once()
    assert len(llm.calls) == 1
    assert (await _poll(client, user, accepted["analysis_id"]))["status"] == "succeeded"


@pytest.mark.parametrize(
    ("fields", "upload_cv", "message"),
    [
        ({"job_description": None}, True, "job description"),
        ({"job_description": "   "}, True, "job description"),
        ({"job_description": JOB_DESCRIPTION}, False, "Upload a CV"),
    ],
)
async def test_analyze_preconditions(
    client: httpx.AsyncClient,
    user: AuthedUser,
    fields: dict[str, Any],
    upload_cv: bool,
    message: str,
) -> None:
    app = await create_application(client, user, **fields)
    if upload_cv:
        await client.post(
            "/api/v1/resumes",
            files={"file": ("cv.pdf", make_pdf(CV_LINES), "application/pdf")},
            headers=user.headers,
        )
    resp = await client.post(f"/api/v1/applications/{app['id']}/analyze", headers=user.headers)
    assert resp.status_code == 422
    assert message in resp.json()["error"]["message"]


async def test_unknown_analysis_404(client: httpx.AsyncClient, user: AuthedUser) -> None:
    resp = await client.get(
        "/api/v1/analyses/00000000-0000-0000-0000-000000000000", headers=user.headers
    )
    assert resp.status_code == 404
    resp = await client.get(
        "/api/v1/applications/00000000-0000-0000-0000-000000000000/analyses",
        headers=user.headers,
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- parsing


def test_parse_accepts_code_fenced_json() -> None:
    fenced = "```json\n" + json.dumps(VALID_RESULT) + "\n```"
    assert parse_model_output(fenced).match_score == 82


def test_parse_ignores_unknown_keys_and_trims() -> None:
    data = {**VALID_RESULT, "extra": "ignored", "strengths": ["  spaced   out  ", ""]}
    result = parse_model_output(json.dumps(data))
    assert result.strengths == ["spaced out"]


def test_retryability_classification() -> None:
    from app.services.analysis import PermanentJobError

    assert is_retryable(InvalidModelOutputError("x"))
    assert is_retryable(LLMError("timeout"))
    assert not is_retryable(LLMError("bad request", retryable=False))
    assert not is_retryable(PermanentJobError("gone"))
    assert is_retryable(RuntimeError("db blip"))


# --------------------------------------------------------------------------- Groq client


def _groq_with(handler: Any) -> GroqLLMClient:
    transport = httpx.MockTransport(handler)
    return GroqLLMClient(
        "gsk_test",
        "openai/gpt-oss-120b",
        5.0,
        http_client=httpx.AsyncClient(transport=transport),
    )


def _completion(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "openai/gpt-oss-120b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 900, "completion_tokens": 300, "total_tokens": 1200},
    }


async def test_groq_client_sends_json_mode_request_and_parses_usage() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion(json.dumps(VALID_RESULT)))

    resp = await _groq_with(handler).complete_json("system prompt", "user prompt")
    assert seen["url"].endswith("/openai/v1/chat/completions")
    assert seen["auth"] == "Bearer gsk_test"
    assert seen["body"]["model"] == "openai/gpt-oss-120b"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"][0] == {"role": "system", "content": "system prompt"}
    assert resp.prompt_tokens == 900
    assert resp.completion_tokens == 300
    assert parse_model_output(resp.content).match_score == 82


@pytest.mark.parametrize(
    ("status", "retryable"), [(429, True), (500, True), (503, True), (400, False), (401, False)]
)
async def test_groq_client_maps_http_errors(status: int, retryable: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "nope", "type": "x"}})

    with pytest.raises(LLMError) as info:
        await _groq_with(handler).complete_json("s", "u")
    assert info.value.retryable is retryable


async def test_groq_client_maps_connection_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(LLMError) as info:
        await _groq_with(handler).complete_json("s", "u")
    assert info.value.retryable is True


async def test_groq_pipeline_end_to_end_with_mocked_http(
    client: httpx.AsyncClient,
    user: AuthedUser,
    ready_app: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    accepted = await _request(client, user, ready_app["id"])
    groq = _groq_with(lambda r: httpx.Response(200, json=_completion(json.dumps(VALID_RESULT))))
    await make_worker(session_factory, settings, groq).run_once()
    done = await _poll(client, user, accepted["analysis_id"])
    assert done["status"] == "succeeded"
    assert done["model"] == "openai/gpt-oss-120b"
    assert done["prompt_tokens"] == 900


def test_llm_client_factory(settings: Settings) -> None:
    assert isinstance(build_llm_client(settings), HeuristicLLMClient)
    with_key = settings.model_copy(update={"groq_api_key": "gsk_x"})
    assert isinstance(build_llm_client(with_key), GroqLLMClient)


async def test_heuristic_client_output_satisfies_schema() -> None:
    prompt = (
        "Company: X\nRole: Backend Engineer\n\n### JOB DESCRIPTION\n"
        + JOB_DESCRIPTION
        + "\n\n### CANDIDATE CV\n"
        + "\n".join(CV_LINES)
    )
    resp = await HeuristicLLMClient().complete_json("s", prompt)
    result = parse_model_output(resp.content)
    assert "kubernetes" in result.missing_skills
    assert "fastapi" in result.matched_skills
    assert 0 <= result.match_score <= 100


async def test_analysis_rows_reference_resume(
    client: httpx.AsyncClient, user: AuthedUser, ready_app: dict[str, Any], db_session: AsyncSession
) -> None:
    accepted = await _request(client, user, ready_app["id"])
    active = (await client.get("/api/v1/resumes/active", headers=user.headers)).json()
    row = await db_session.get(AIAnalysis, accepted["analysis_id"])
    assert row is not None
    assert str(row.resume_id) == active["id"]
    assert row.job_id is not None

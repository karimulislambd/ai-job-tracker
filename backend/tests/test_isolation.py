"""Cross-user isolation: user B must get 404 (never 403, never data) for every one of
user A's resources, on every endpoint that takes an id."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.conftest import JOB_DESCRIPTION, AuthedUser, create_application
from tests.pdf_utils import CV_LINES, make_pdf


@pytest.fixture
async def owned(client: httpx.AsyncClient, user: AuthedUser) -> dict[str, Any]:
    app = await create_application(client, user, job_description=JOB_DESCRIPTION, status="applied")
    resume = await client.post(
        "/api/v1/resumes",
        files={"file": ("cv.pdf", make_pdf(CV_LINES), "application/pdf")},
        headers=user.headers,
    )
    assert resume.status_code == 201
    analysis = await client.post(f"/api/v1/applications/{app['id']}/analyze", headers=user.headers)
    assert analysis.status_code == 202
    return {
        "application": app["id"],
        "resume": resume.json()["id"],
        "analysis": analysis.json()["analysis_id"],
    }


def _requests(ids: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    a, r, x = ids["application"], ids["resume"], ids["analysis"]
    return [
        ("GET", f"/api/v1/applications/{a}", {}),
        ("PATCH", f"/api/v1/applications/{a}", {"json": {"notes": "pwned"}}),
        ("PATCH", f"/api/v1/applications/{a}/status", {"json": {"status": "rejected"}}),
        ("DELETE", f"/api/v1/applications/{a}", {}),
        ("GET", f"/api/v1/applications/{a}/events", {}),
        ("POST", f"/api/v1/applications/{a}/analyze", {}),
        ("GET", f"/api/v1/applications/{a}/analyses", {}),
        ("GET", f"/api/v1/analyses/{x}", {}),
        ("GET", f"/api/v1/resumes/{r}", {}),
        ("POST", f"/api/v1/resumes/{r}/activate", {}),
    ]


async def test_other_user_gets_404_on_every_resource(
    client: httpx.AsyncClient, user: AuthedUser, other_user: AuthedUser, owned: dict[str, Any]
) -> None:
    for method, url, kwargs in _requests(owned):
        resp = await client.request(method, url, headers=other_user.headers, **kwargs)
        assert resp.status_code == 404, f"{method} {url} -> {resp.status_code}"
        assert resp.json()["error"]["code"] == "not_found"

    # Nothing was modified: the owner still sees the original data.
    app = await client.get(f"/api/v1/applications/{owned['application']}", headers=user.headers)
    assert app.status_code == 200
    assert app.json()["notes"] is None
    assert app.json()["status"] == "applied"


async def test_owner_can_access_every_resource(
    client: httpx.AsyncClient, user: AuthedUser, owned: dict[str, Any]
) -> None:
    for method, url, kwargs in _requests(owned):
        if method == "DELETE":
            continue
        resp = await client.request(method, url, headers=user.headers, **kwargs)
        assert resp.status_code < 300, f"{method} {url} -> {resp.status_code}"


async def test_collections_and_stats_only_show_own_data(
    client: httpx.AsyncClient, user: AuthedUser, other_user: AuthedUser, owned: dict[str, Any]
) -> None:
    apps = await client.get("/api/v1/applications", headers=other_user.headers)
    assert apps.json()["total"] == 0
    searched = await client.get(
        "/api/v1/applications", params={"q": "Acme"}, headers=other_user.headers
    )
    assert searched.json()["items"] == []
    resumes = await client.get("/api/v1/resumes", headers=other_user.headers)
    assert resumes.json() == []
    active = await client.get("/api/v1/resumes/active", headers=other_user.headers)
    assert active.status_code == 404
    stats = await client.get("/api/v1/stats/dashboard", headers=other_user.headers)
    assert stats.json()["total"] == 0

    mine = await client.get("/api/v1/stats/dashboard", headers=user.headers)
    assert mine.json()["total"] == 1


async def test_cannot_analyze_with_other_users_cv(
    client: httpx.AsyncClient, user: AuthedUser, other_user: AuthedUser, owned: dict[str, Any]
) -> None:
    """B has an application but no CV; A's active CV must not be used for B's analysis."""
    b_app = await create_application(client, other_user, job_description=JOB_DESCRIPTION)
    resp = await client.post(
        f"/api/v1/applications/{b_app['id']}/analyze", headers=other_user.headers
    )
    assert resp.status_code == 422
    assert "Upload a CV" in resp.json()["error"]["message"]

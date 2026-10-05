from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from tests.conftest import AuthedUser, create_application

API = "/api/v1/applications"


async def test_crud_roundtrip(client: httpx.AsyncClient, user: AuthedUser) -> None:
    created = await create_application(
        client,
        user,
        company="  Northwind  ",
        role_title="Backend Engineer",
        job_url="https://jobs.example.com/1",
        location="Remote",
        salary_min=50000,
        salary_max=70000,
        currency="eur",
        notes="Referral from Sam",
    )
    assert created["company"] == "Northwind"  # stripped
    assert created["currency"] == "EUR"  # normalised
    assert created["status"] == "wishlist"
    assert created["applied_at"] is None

    app_id = created["id"]
    got = await client.get(f"{API}/{app_id}", headers=user.headers)
    assert got.status_code == 200
    assert got.json() == created

    patched = await client.patch(
        f"{API}/{app_id}", json={"notes": "Updated", "location": None}, headers=user.headers
    )
    assert patched.status_code == 200
    assert patched.json()["notes"] == "Updated"
    assert patched.json()["location"] is None
    assert patched.json()["company"] == "Northwind"  # untouched

    deleted = await client.delete(f"{API}/{app_id}", headers=user.headers)
    assert deleted.status_code == 204
    assert (await client.get(f"{API}/{app_id}", headers=user.headers)).status_code == 404
    assert (await client.delete(f"{API}/{app_id}", headers=user.headers)).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"company": "", "role_title": "x"},
        {"company": "   ", "role_title": "x"},
        {"company": "x"},
        {"company": "x", "role_title": "y", "salary_min": 10, "salary_max": 5},
        {"company": "x", "role_title": "y", "salary_min": -1},
        {"company": "x", "role_title": "y", "currency": "EURO"},
        {"company": "x", "role_title": "y", "status": "hired"},
        {"company": "x", "role_title": "y", "job_url": "not a url"},
    ],
)
async def test_create_validation(
    client: httpx.AsyncClient, user: AuthedUser, payload: dict[str, Any]
) -> None:
    resp = await client.post(API, json=payload, headers=user.headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_patch_validation(client: httpx.AsyncClient, user: AuthedUser) -> None:
    app = await create_application(client, user, salary_min=100, salary_max=200)
    # Violates the range against the *stored* max.
    resp = await client.patch(f"{API}/{app['id']}", json={"salary_min": 500}, headers=user.headers)
    assert resp.status_code == 422
    resp = await client.patch(f"{API}/{app['id']}", json={"company": None}, headers=user.headers)
    assert resp.status_code == 422


async def test_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get(API)).status_code == 401
    assert (await client.post(API, json={"company": "a", "role_title": "b"})).status_code == 401


async def test_creation_records_event_and_sets_applied_at(
    client: httpx.AsyncClient, user: AuthedUser
) -> None:
    app = await create_application(client, user, status="applied")
    assert app["applied_at"] is not None
    events = (await client.get(f"{API}/{app['id']}/events", headers=user.headers)).json()
    assert len(events) == 1
    assert events[0]["event_type"] == "created"
    assert events[0]["to_status"] == "applied"


async def test_status_change_records_events(client: httpx.AsyncClient, user: AuthedUser) -> None:
    app = await create_application(client, user)
    app_id = app["id"]

    r1 = await client.patch(
        f"{API}/{app_id}/status", json={"status": "applied"}, headers=user.headers
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "applied"
    assert r1.json()["applied_at"] is not None

    await client.patch(
        f"{API}/{app_id}/status",
        json={"status": "interviewing", "note": "Recruiter call booked"},
        headers=user.headers,
    )
    # No-op transition must not create an event.
    await client.patch(
        f"{API}/{app_id}/status", json={"status": "interviewing"}, headers=user.headers
    )
    # Status change through the generic PATCH is recorded too.
    await client.patch(f"{API}/{app_id}", json={"status": "offer"}, headers=user.headers)

    events = (await client.get(f"{API}/{app_id}/events", headers=user.headers)).json()
    assert [(e["event_type"], e["from_status"], e["to_status"]) for e in events] == [
        ("created", None, "wishlist"),
        ("status_changed", "wishlist", "applied"),
        ("status_changed", "applied", "interviewing"),
        ("status_changed", "interviewing", "offer"),
    ]
    assert events[2]["note"] == "Recruiter call booked"

    bad = await client.patch(
        f"{API}/{app_id}/status", json={"status": "bogus"}, headers=user.headers
    )
    assert bad.status_code == 422


async def test_follow_up_change_clears_overdue_flag(
    client: httpx.AsyncClient, user: AuthedUser, db_session: Any
) -> None:
    from app.services.maintenance import flag_overdue_follow_ups

    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    app = await create_application(client, user, status="applied", follow_up_at=past)
    await flag_overdue_follow_ups(db_session)
    flagged = (await client.get(f"{API}/{app['id']}", headers=user.headers)).json()
    assert flagged["follow_up_flagged_at"] is not None

    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    resp = await client.patch(
        f"{API}/{app['id']}", json={"follow_up_at": future}, headers=user.headers
    )
    assert resp.json()["follow_up_flagged_at"] is None


@pytest.fixture
async def seeded(client: httpx.AsyncClient, user: AuthedUser) -> dict[str, str]:
    now = datetime.now(UTC)
    specs = [
        ("Google", "Backend Engineer", "applied", 10, "Python and Kubernetes"),
        ("Googleplex Labs", "Data Engineer", "interviewing", 5, None),
        ("Stripe", "API Engineer", "rejected", 30, "payments infrastructure"),
        ("Shopify", "Platform Engineer", "offer", 20, None),
        ("Acme", "Frontend Developer", "wishlist", None, "React role, maybe"),
        ("100% Remote_Co", "Python Developer", "applied", 2, None),
    ]
    ids = {}
    for company, role, status, days_ago, notes in specs:
        fields: dict[str, Any] = {"status": status, "notes": notes}
        if days_ago is not None:
            fields["applied_at"] = (now - timedelta(days=days_ago)).isoformat()
        app = await create_application(client, user, company=company, role_title=role, **fields)
        ids[company] = app["id"]
    return ids


async def _list(client: httpx.AsyncClient, user: AuthedUser, **params: Any) -> dict[str, Any]:
    resp = await client.get(API, params=params, headers=user.headers)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def _companies(page: dict[str, Any]) -> list[str]:
    return [a["company"] for a in page["items"]]


async def test_filter_by_status(
    client: httpx.AsyncClient, user: AuthedUser, seeded: dict[str, str]
) -> None:
    page = await _list(client, user, status="applied")
    assert sorted(_companies(page)) == ["100% Remote_Co", "Google"]
    multi = await client.get(
        API, params=[("status", "offer"), ("status", "rejected")], headers=user.headers
    )
    assert sorted(_companies(multi.json())) == ["Shopify", "Stripe"]
    assert multi.json()["total"] == 2


async def test_filter_by_company_is_case_insensitive_substring(
    client: httpx.AsyncClient, user: AuthedUser, seeded: dict[str, str]
) -> None:
    page = await _list(client, user, company="goo")
    assert sorted(_companies(page)) == ["Google", "Googleplex Labs"]
    # LIKE wildcards in user input are escaped, not interpreted.
    assert _companies(await _list(client, user, company="%")) == ["100% Remote_Co"]
    assert _companies(await _list(client, user, company="_")) == ["100% Remote_Co"]


async def test_filter_by_applied_date_range(
    client: httpx.AsyncClient, user: AuthedUser, seeded: dict[str, str]
) -> None:
    now = datetime.now(UTC)
    page = await _list(
        client,
        user,
        applied_from=(now - timedelta(days=15)).isoformat(),
        applied_to=(now - timedelta(days=3)).isoformat(),
    )
    assert sorted(_companies(page)) == ["Google", "Googleplex Labs"]


async def test_full_text_search(
    client: httpx.AsyncClient, user: AuthedUser, seeded: dict[str, str]
) -> None:
    # Stemmed full-text match on notes ("payments" -> "payment").
    assert _companies(await _list(client, user, q="payment")) == ["Stripe"]
    # Matches role titles.
    assert sorted(_companies(await _list(client, user, q="platform"))) == ["Shopify"]
    # Partial word falls back to substring search.
    assert sorted(_companies(await _list(client, user, q="googlep"))) == ["Googleplex Labs"]
    # websearch syntax: OR
    page = await _list(client, user, q="kubernetes or react", sort="relevance")
    assert sorted(_companies(page)) == ["Acme", "Google"]
    assert _companies(await _list(client, user, q="zzzz-nothing")) == []


@pytest.mark.parametrize(
    ("sort", "expected_first"),
    [
        ("-applied_at", "100% Remote_Co"),
        ("applied_at", "Stripe"),
        ("company", "100% Remote_Co"),
        ("-company", "Stripe"),
    ],
)
async def test_sorting(
    client: httpx.AsyncClient,
    user: AuthedUser,
    seeded: dict[str, str],
    sort: str,
    expected_first: str,
) -> None:
    page = await _list(client, user, sort=sort)
    assert page["items"][0]["company"] == expected_first


async def test_pagination_is_stable_and_complete(
    client: httpx.AsyncClient, user: AuthedUser, seeded: dict[str, str]
) -> None:
    seen: list[str] = []
    offset = 0
    while True:
        page = await _list(client, user, limit=4, offset=offset, sort="company")
        assert page["total"] == 6
        assert page["limit"] == 4
        seen += [a["id"] for a in page["items"]]
        if len(page["items"]) < 4:
            break
        offset += 4
    assert len(seen) == 6
    assert set(seen) == set(seeded.values())

    assert (await client.get(API, params={"limit": 0}, headers=user.headers)).status_code == 422
    assert (await client.get(API, params={"limit": 500}, headers=user.headers)).status_code == 422
    assert (await client.get(API, params={"offset": -1}, headers=user.headers)).status_code == 422

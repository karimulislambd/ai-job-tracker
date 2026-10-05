from __future__ import annotations

import httpx
import pytest

from tests.conftest import AuthedUser
from tests.pdf_utils import CV_LINES, make_pdf

API = "/api/v1/resumes"


def _upload(
    client: httpx.AsyncClient,
    user: AuthedUser,
    data: bytes,
    filename: str = "cv.pdf",
    content_type: str = "application/pdf",
) -> object:
    return client.post(API, files={"file": (filename, data, content_type)}, headers=user.headers)


async def test_upload_extracts_text_and_versions(
    client: httpx.AsyncClient, user: AuthedUser
) -> None:
    first = await _upload(client, user, make_pdf(CV_LINES), filename="my-cv.pdf")  # type: ignore[misc]
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["version"] == 1
    assert body["is_active"] is True
    assert body["filename"] == "my-cv.pdf"
    assert body["page_count"] == 1
    assert "FastAPI" in body["content_text"]

    second = await _upload(client, user, make_pdf([*CV_LINES, "Kubernetes"], pages=2))  # type: ignore[misc]
    assert second.json()["version"] == 2
    assert second.json()["page_count"] == 2

    listing = (await client.get(API, headers=user.headers)).json()
    assert [(r["version"], r["is_active"]) for r in listing] == [(2, True), (1, False)]
    assert "content_text" not in listing[0]  # summaries only

    active = await client.get(f"{API}/active", headers=user.headers)
    assert active.json()["version"] == 2

    # Re-activate the older version: exactly one active version remains.
    reactivated = await client.post(f"{API}/{body['id']}/activate", headers=user.headers)
    assert reactivated.status_code == 200
    listing = (await client.get(API, headers=user.headers)).json()
    assert [(r["version"], r["is_active"]) for r in listing] == [(2, False), (1, True)]
    # Activating the already-active version is a no-op.
    again = await client.post(f"{API}/{body['id']}/activate", headers=user.headers)
    assert again.json()["is_active"] is True


@pytest.mark.parametrize(
    ("data", "filename", "content_type", "status", "code"),
    [
        (
            b"hello world, definitely not a pdf",
            "cv.pdf",
            "application/pdf",
            415,
            "unsupported_media_type",
        ),
        (make_pdf(CV_LINES), "cv.pdf", "text/plain", 415, "unsupported_media_type"),
        (make_pdf(CV_LINES), "cv.exe", "application/pdf", 415, "unsupported_media_type"),
        (b"", "cv.pdf", "application/pdf", 422, "validation_error"),
        (b"%PDF-1.4 this is garbage", "cv.pdf", "application/pdf", 422, "validation_error"),
        (make_pdf([]), "cv.pdf", "application/pdf", 422, "validation_error"),
        (make_pdf(["Hi"], pages=20), "cv.pdf", "application/pdf", 422, "validation_error"),
    ],
    ids=[
        "not-pdf-bytes",
        "wrong-content-type",
        "wrong-extension",
        "empty",
        "corrupt",
        "no-text",
        "too-many-pages",
    ],
)
async def test_upload_validation(
    client: httpx.AsyncClient,
    user: AuthedUser,
    data: bytes,
    filename: str,
    content_type: str,
    status: int,
    code: str,
) -> None:
    resp = await _upload(client, user, data, filename, content_type)  # type: ignore[misc]
    assert resp.status_code == status, resp.text
    assert resp.json()["error"]["code"] == code
    assert (await client.get(API, headers=user.headers)).json() == []


async def test_upload_too_large(app_factory: object, user: AuthedUser) -> None:
    app = app_factory(max_upload_bytes=1024)  # type: ignore[operator]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        big = make_pdf(CV_LINES * 40)
        assert len(big) > 1024
        resp = await c.post(
            API, files={"file": ("cv.pdf", big, "application/pdf")}, headers=user.headers
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "payload_too_large"

        huge = b"%PDF-" + b"0" * 200_000
        resp = await c.post(
            API, files={"file": ("cv.pdf", huge, "application/pdf")}, headers=user.headers
        )
        assert resp.status_code == 413  # rejected from Content-Length before parsing


async def test_missing_file_field(client: httpx.AsyncClient, user: AuthedUser) -> None:
    resp = await client.post(API, headers=user.headers)
    assert resp.status_code == 422


async def test_unknown_resume_404(client: httpx.AsyncClient, user: AuthedUser) -> None:
    resp = await client.get(f"{API}/00000000-0000-0000-0000-000000000000", headers=user.headers)
    assert resp.status_code == 404
    assert (await client.get(f"{API}/active", headers=user.headers)).status_code == 404

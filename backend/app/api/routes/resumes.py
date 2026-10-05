from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.deps import SessionDep, SettingsDep, UserId
from app.core.errors import PayloadTooLargeError
from app.schemas.resume import ResumeOut, ResumeSummary
from app.services.resumes import ResumeService

router = APIRouter(prefix="/resumes", tags=["resumes"])

_MULTIPART_OVERHEAD = 64 * 1024


async def _reject_oversized_body(request: Request, settings: SettingsDep) -> None:
    """Fail fast on Content-Length before the multipart body is parsed and spooled."""
    length = request.headers.get("content-length")
    if (
        length
        and length.isdigit()
        and int(length) > settings.max_upload_bytes + _MULTIPART_OVERHEAD
    ):
        raise PayloadTooLargeError(
            f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit"
        )


@router.post(
    "",
    response_model=ResumeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_reject_oversized_body)],
    summary="Upload a PDF CV; its text becomes the new active version",
)
async def upload_resume(
    file: Annotated[UploadFile, File(description="PDF, max 5 MB")],
    user_id: UserId,
    session: SessionDep,
    settings: SettingsDep,
) -> ResumeOut:
    # Read at most limit+1 bytes so an oversized upload is rejected without buffering it all.
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit"
        )
    resume = await ResumeService(session, settings.max_upload_bytes).upload(
        user_id, data, file.filename, file.content_type
    )
    return ResumeOut.model_validate(resume)


@router.get("", response_model=list[ResumeSummary])
async def list_resumes(
    user_id: UserId, session: SessionDep, settings: SettingsDep
) -> list[ResumeSummary]:
    rows = await ResumeService(session, settings.max_upload_bytes).list_for_user(user_id)
    return [ResumeSummary.model_validate(r) for r in rows]


@router.get("/active", response_model=ResumeOut)
async def get_active_resume(
    user_id: UserId, session: SessionDep, settings: SettingsDep
) -> ResumeOut:
    resume = await ResumeService(session, settings.max_upload_bytes).get_active(user_id)
    return ResumeOut.model_validate(resume)


@router.get("/{resume_id}", response_model=ResumeOut)
async def get_resume(
    resume_id: uuid.UUID, user_id: UserId, session: SessionDep, settings: SettingsDep
) -> ResumeOut:
    resume = await ResumeService(session, settings.max_upload_bytes).get(user_id, resume_id)
    return ResumeOut.model_validate(resume)


@router.post("/{resume_id}/activate", response_model=ResumeOut)
async def activate_resume(
    resume_id: uuid.UUID, user_id: UserId, session: SessionDep, settings: SettingsDep
) -> ResumeOut:
    resume = await ResumeService(session, settings.max_upload_bytes).activate(user_id, resume_id)
    return ResumeOut.model_validate(resume)

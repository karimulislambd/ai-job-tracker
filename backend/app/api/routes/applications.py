from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CacheDep, SessionDep, SettingsDep, UserId
from app.models import ApplicationStatus
from app.schemas.analysis import AnalysisAccepted, AnalysisOut
from app.schemas.application import (
    ApplicationCreate,
    ApplicationEventOut,
    ApplicationFilters,
    ApplicationOut,
    ApplicationSort,
    ApplicationUpdate,
    StatusUpdate,
)
from app.schemas.common import Page
from app.services.analysis import AnalysisService
from app.services.applications import ApplicationService

router = APIRouter(prefix="/applications", tags=["applications"])


def _service(session: SessionDep, cache: CacheDep) -> ApplicationService:
    return ApplicationService(session, cache)


Service = Annotated[ApplicationService, Depends(_service)]


def _filters(
    status_: Annotated[
        list[ApplicationStatus] | None,
        Query(alias="status", description="Repeat to filter by several statuses"),
    ] = None,
    company: Annotated[str | None, Query(max_length=200)] = None,
    q: Annotated[str | None, Query(max_length=200, description="Full-text search")] = None,
    applied_from: datetime | None = None,
    applied_to: datetime | None = None,
    sort: ApplicationSort = ApplicationSort.CREATED_DESC,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApplicationFilters:
    return ApplicationFilters(
        status=status_,
        company=company,
        q=q,
        applied_from=applied_from,
        applied_to=applied_to,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("", response_model=Page[ApplicationOut], summary="List, filter, search and paginate")
async def list_applications(
    user_id: UserId, service: Service, filters: Annotated[ApplicationFilters, Depends(_filters)]
) -> Page[ApplicationOut]:
    items, total = await service.search(user_id, filters)
    return Page[ApplicationOut](
        items=[ApplicationOut.model_validate(a) for a in items],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def create_application(
    body: ApplicationCreate, user_id: UserId, service: Service
) -> ApplicationOut:
    return ApplicationOut.model_validate(await service.create(user_id, body))


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: uuid.UUID, user_id: UserId, service: Service
) -> ApplicationOut:
    return ApplicationOut.model_validate(await service.get(user_id, application_id))


@router.patch("/{application_id}", response_model=ApplicationOut)
async def update_application(
    application_id: uuid.UUID, body: ApplicationUpdate, user_id: UserId, service: Service
) -> ApplicationOut:
    return ApplicationOut.model_validate(await service.update(user_id, application_id, body))


@router.patch(
    "/{application_id}/status",
    response_model=ApplicationOut,
    summary="Move to a new status (records a timeline event)",
)
async def change_status(
    application_id: uuid.UUID, body: StatusUpdate, user_id: UserId, service: Service
) -> ApplicationOut:
    app = await service.change_status(user_id, application_id, body.status, body.note)
    return ApplicationOut.model_validate(app)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    application_id: uuid.UUID, user_id: UserId, service: Service
) -> Response:
    await service.delete(user_id, application_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{application_id}/events", response_model=list[ApplicationEventOut])
async def list_events(
    application_id: uuid.UUID, user_id: UserId, service: Service
) -> list[ApplicationEventOut]:
    events = await service.events(user_id, application_id)
    return [ApplicationEventOut.model_validate(e) for e in events]


@router.post(
    "/{application_id}/analyze",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an AI CV-vs-job match analysis; poll the returned URL for the result",
)
async def analyze(
    application_id: uuid.UUID, user_id: UserId, session: SessionDep, settings: SettingsDep
) -> AnalysisAccepted:
    analysis = await AnalysisService(session, settings.job_max_attempts).request(
        user_id, application_id
    )
    return AnalysisAccepted(
        analysis_id=analysis.id,
        status=analysis.status,
        poll_url=f"/api/v1/analyses/{analysis.id}",
    )


@router.get("/{application_id}/analyses", response_model=list[AnalysisOut])
async def list_analyses(
    application_id: uuid.UUID, user_id: UserId, session: SessionDep
) -> list[AnalysisOut]:
    rows = await AnalysisService(session).list_for_application(user_id, application_id)
    return [AnalysisOut.model_validate(a) for a in rows]

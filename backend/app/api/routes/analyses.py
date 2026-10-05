from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import SessionDep, UserId
from app.schemas.analysis import AnalysisOut
from app.services.analysis import AnalysisService

router = APIRouter(prefix="/analyses", tags=["ai analysis"])


@router.get("/{analysis_id}", response_model=AnalysisOut, summary="Poll analysis status/result")
async def get_analysis(analysis_id: uuid.UUID, user_id: UserId, session: SessionDep) -> AnalysisOut:
    return AnalysisOut.model_validate(await AnalysisService(session).get(user_id, analysis_id))

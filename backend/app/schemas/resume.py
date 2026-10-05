from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import ORMModel


class ResumeSummary(ORMModel):
    id: uuid.UUID
    version: int
    filename: str
    page_count: int
    size_bytes: int
    is_active: bool
    created_at: datetime


class ResumeOut(ResumeSummary):
    content_text: str

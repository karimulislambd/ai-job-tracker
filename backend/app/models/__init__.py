"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.ai_analysis import AIAnalysis
from app.models.application import Application
from app.models.application_event import ApplicationEvent
from app.models.enums import AnalysisStatus, ApplicationStatus, EventType, JobStatus
from app.models.job import Job
from app.models.refresh_token import RefreshToken
from app.models.resume import Resume
from app.models.user import User

__all__ = [
    "AIAnalysis",
    "AnalysisStatus",
    "Application",
    "ApplicationEvent",
    "ApplicationStatus",
    "EventType",
    "Job",
    "JobStatus",
    "RefreshToken",
    "Resume",
    "User",
]

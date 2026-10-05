from fastapi import APIRouter

from app.api.routes import analyses, applications, auth, resumes, stats

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(applications.router)
api_router.include_router(analyses.router)
api_router.include_router(resumes.router)
api_router.include_router(stats.router)

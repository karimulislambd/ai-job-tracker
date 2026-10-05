"""Create (or re-create) the demo *template* account that demo users are cloned from."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import (
    AIAnalysis,
    AnalysisStatus,
    Application,
    ApplicationEvent,
    ApplicationStatus,
    EventType,
    Resume,
    User,
)
from app.repositories.users import UserRepository
from app.seed.data import APPLICATIONS, SAMPLE_CV

logger = logging.getLogger(__name__)

TEMPLATE_EMAIL = "demo-template@demo.ai-job-tracker.dev"


async def seed_demo_template(
    session: AsyncSession, *, now: datetime | None = None, force: bool = False
) -> User:
    now = now or datetime.now(UTC)
    # Serialise concurrent seeding (several API instances booting at once).
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('seed_demo_template'))"))
    users = UserRepository(session)
    existing = await users.get_demo_template()
    if existing is not None and not force:
        await session.commit()
        return existing
    if existing is not None:
        await session.execute(delete(User).where(User.id == existing.id))

    template = User(
        email=TEMPLATE_EMAIL,
        password_hash=hash_password("unusable-" + now.isoformat()),
        full_name="Demo Template",
        is_demo_template=True,
        created_at=now,
        updated_at=now,
    )
    await users.add(template)

    old_cv = Resume(
        user_id=template.id,
        version=1,
        filename="jordan-rahman-cv-2024.pdf",
        content_text=SAMPLE_CV.split("PROJECTS")[0],
        page_count=1,
        size_bytes=48_211,
        is_active=False,
        created_at=now - timedelta(days=70),
    )
    cv = Resume(
        user_id=template.id,
        version=2,
        filename="jordan-rahman-cv.pdf",
        content_text=SAMPLE_CV,
        page_count=2,
        size_bytes=61_532,
        is_active=True,
        created_at=now - timedelta(days=50),
    )
    session.add_all([old_cv, cv])
    await session.flush()

    for i, spec in enumerate(APPLICATIONS):
        first_status, first_days = spec.timeline[0]
        created = now - timedelta(days=first_days, hours=2 + i % 5)
        applied_at = None
        for status, days in spec.timeline:
            if status == "applied":
                applied_at = now - timedelta(days=days, hours=1 + i % 7)
        last_change = now - timedelta(days=spec.timeline[-1][1], hours=i % 3)
        app = Application(
            user_id=template.id,
            company=spec.company,
            role_title=spec.role_title,
            location=spec.location,
            status=ApplicationStatus(spec.status),
            salary_min=spec.salary[0] if spec.salary else None,
            salary_max=spec.salary[1] if spec.salary else None,
            currency=spec.salary[2] if spec.salary else None,
            applied_at=applied_at,
            follow_up_at=(
                now + timedelta(days=spec.follow_up_in_days, hours=3)
                if spec.follow_up_in_days is not None
                else None
            ),
            notes=spec.notes,
            job_description=spec.job_description,
            job_url=spec.job_url,
            created_at=created,
            updated_at=last_change,
        )
        session.add(app)
        await session.flush()

        session.add(
            ApplicationEvent(
                application_id=app.id,
                event_type=EventType.CREATED,
                to_status=ApplicationStatus(first_status),
                occurred_at=created,
            )
        )
        previous = first_status
        for status, days in spec.timeline[1:]:
            session.add(
                ApplicationEvent(
                    application_id=app.id,
                    event_type=EventType.STATUS_CHANGED,
                    from_status=ApplicationStatus(previous),
                    to_status=ApplicationStatus(status),
                    occurred_at=now - timedelta(days=days, hours=i % 3),
                )
            )
            previous = status

        if spec.analysis is not None:
            started = now - timedelta(days=max(spec.timeline[-1][1] - 1, 0), hours=5)
            session.add(
                AIAnalysis(
                    application_id=app.id,
                    resume_id=cv.id,
                    status=AnalysisStatus.SUCCEEDED,
                    result=spec.analysis,
                    model="llama-3.3-70b-versatile",
                    prompt_tokens=1_850 + i * 13,
                    completion_tokens=640 + i * 7,
                    duration_ms=2_400 + i * 90,
                    created_at=started,
                    started_at=started,
                    completed_at=started + timedelta(seconds=2.4),
                )
            )

    await session.commit()
    logger.info("demo_template_seeded", extra={"applications": len(APPLICATIONS)})
    return template

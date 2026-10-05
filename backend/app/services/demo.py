"""Demo mode: every visitor gets a private, throw-away copy of the seeded demo account.

The clone runs as one SQL statement (data-modifying CTEs), so it's atomic and fast.
All timestamps are shifted by ``now - template.created_at`` so the demo data always
looks fresh ("applied 3 days ago") no matter when the template was seeded.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.models import User
from app.repositories.users import UserRepository


class DemoUnavailableError(AppError):
    status_code = 503
    code = "demo_unavailable"


_CLONE_SQL = text(
    """
    WITH app_map AS MATERIALIZED (
        SELECT id AS old_id, gen_random_uuid() AS new_id
        FROM applications WHERE user_id = :template_id
    ),
    resume_map AS MATERIALIZED (
        SELECT id AS old_id, gen_random_uuid() AS new_id
        FROM resumes WHERE user_id = :template_id
    ),
    ins_apps AS (
        INSERT INTO applications (
            id, user_id, company, role_title, job_url, location, salary_min, salary_max,
            currency, status, applied_at, follow_up_at, follow_up_flagged_at, notes,
            job_description, created_at, updated_at)
        SELECT m.new_id, :user_id, a.company, a.role_title, a.job_url, a.location,
               a.salary_min, a.salary_max, a.currency, a.status,
               a.applied_at + CAST(:shift AS interval),
               a.follow_up_at + CAST(:shift AS interval), NULL, a.notes, a.job_description,
               a.created_at + CAST(:shift AS interval), a.updated_at + CAST(:shift AS interval)
        FROM applications a JOIN app_map m ON m.old_id = a.id
        RETURNING id
    ),
    ins_events AS (
        INSERT INTO application_events (
            application_id, event_type, from_status, to_status, note, occurred_at)
        SELECT m.new_id, e.event_type, e.from_status, e.to_status, e.note,
               e.occurred_at + CAST(:shift AS interval)
        FROM application_events e JOIN app_map m ON m.old_id = e.application_id
        WHERE e.event_type <> 'follow_up_overdue'
          -- the FK target rows are inserted by ins_apps in the same statement
          AND EXISTS (SELECT 1 FROM ins_apps)
        RETURNING id
    ),
    ins_resumes AS (
        INSERT INTO resumes (
            id, user_id, version, filename, content_text, page_count, size_bytes,
            is_active, created_at)
        SELECT rm.new_id, :user_id, r.version, r.filename, r.content_text, r.page_count,
               r.size_bytes, r.is_active, r.created_at + CAST(:shift AS interval)
        FROM resumes r JOIN resume_map rm ON rm.old_id = r.id
        RETURNING id
    ),
    ins_analyses AS (
        INSERT INTO ai_analyses (
            application_id, resume_id, status, result, model, prompt_tokens,
            completion_tokens, duration_ms, created_at, started_at, completed_at)
        SELECT am.new_id, rm.new_id, x.status, x.result, x.model, x.prompt_tokens,
               x.completion_tokens, x.duration_ms, x.created_at + CAST(:shift AS interval),
               x.started_at + CAST(:shift AS interval), x.completed_at + CAST(:shift AS interval)
        FROM ai_analyses x
        JOIN app_map am ON am.old_id = x.application_id
        JOIN resume_map rm ON rm.old_id = x.resume_id
        WHERE x.status = 'succeeded'
          AND EXISTS (SELECT 1 FROM ins_apps) AND EXISTS (SELECT 1 FROM ins_resumes)
        RETURNING id
    )
    SELECT (SELECT count(*) FROM ins_apps)     AS applications,
           (SELECT count(*) FROM ins_events)   AS events,
           (SELECT count(*) FROM ins_resumes)  AS resumes,
           (SELECT count(*) FROM ins_analyses) AS analyses
    """
)


class DemoService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)

    async def create_demo_user(self, now: datetime | None = None) -> User:
        if not self.settings.demo_enabled:
            raise DemoUnavailableError("Demo mode is disabled")
        template = await self.users.get_demo_template()
        if template is None:
            raise DemoUnavailableError("Demo data has not been seeded yet")
        now = now or datetime.now(UTC)
        user = await self.users.add(
            User(
                email=f"demo-{uuid.uuid4().hex[:12]}@demo.ai-job-tracker.dev",
                # Random unusable password: demo users can only get in via /auth/demo.
                password_hash=hash_password(secrets.token_urlsafe(32)),
                full_name="Demo User",
                is_demo=True,
                demo_expires_at=now + timedelta(hours=self.settings.demo_ttl_hours),
            )
        )
        await self.session.execute(
            _CLONE_SQL,
            {"template_id": template.id, "user_id": user.id, "shift": now - template.created_at},
        )
        # The refresh token is issued by AuthService in the same transaction.
        return user

"""Dashboard aggregations, computed entirely in SQL (no Python loops over rows).

Definitions (documented in the README):
* applied        — application has ``applied_at`` set
* responded      — an applied application that ever reached interviewing/offer/rejected
                   (taken from the event log, so later withdrawals don't erase it)
* interviewed    — ever reached interviewing/offer
* days to first response — first such event minus ``applied_at``
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SUMMARY_SQL = text(
    """
    WITH apps AS (
        SELECT a.id, a.status, a.applied_at
        FROM applications a
        WHERE a.user_id = :user_id
    ),
    first_response AS (
        SELECT e.application_id, min(e.occurred_at) AS first_response_at
        FROM application_events e
        JOIN apps ON apps.id = e.application_id
        WHERE e.to_status IN ('interviewing', 'offer', 'rejected')
        GROUP BY e.application_id
    ),
    reached AS (
        SELECT e.application_id,
               bool_or(e.to_status IN ('interviewing', 'offer')) AS interviewed,
               bool_or(e.to_status = 'offer') AS offered
        FROM application_events e
        JOIN apps ON apps.id = e.application_id
        GROUP BY e.application_id
    )
    SELECT
        count(*)                                                    AS total,
        count(*) FILTER (WHERE apps.applied_at IS NOT NULL)         AS applied,
        count(*) FILTER (WHERE apps.applied_at IS NOT NULL
                          AND fr.first_response_at IS NOT NULL)     AS responded,
        count(*) FILTER (WHERE apps.applied_at IS NOT NULL
                          AND coalesce(r.interviewed, false))       AS interviewed,
        count(*) FILTER (WHERE apps.applied_at IS NOT NULL
                          AND coalesce(r.offered, false))           AS offered,
        avg(EXTRACT(EPOCH FROM (fr.first_response_at - apps.applied_at)) / 86400.0)
            FILTER (WHERE apps.applied_at IS NOT NULL
                     AND fr.first_response_at >= apps.applied_at)   AS avg_days_to_response
    FROM apps
    LEFT JOIN first_response fr ON fr.application_id = apps.id
    LEFT JOIN reached r ON r.application_id = apps.id
    """
)

_BY_STATUS_SQL = text(
    """
    SELECT status::text AS status, count(*) AS n
    FROM applications
    WHERE user_id = :user_id
    GROUP BY status
    """
)

_WEEKLY_SQL = text(
    """
    WITH weeks AS (
        SELECT generate_series(
            date_trunc('week', CAST(:now AS timestamptz)) - interval '11 weeks',
            date_trunc('week', CAST(:now AS timestamptz)),
            interval '1 week'
        ) AS week_start
    )
    SELECT weeks.week_start::date AS week_start, count(a.id) AS n
    FROM weeks
    LEFT JOIN applications a
           ON a.user_id = :user_id
          AND a.applied_at >= weeks.week_start
          AND a.applied_at <  weeks.week_start + interval '1 week'
    GROUP BY weeks.week_start
    ORDER BY weeks.week_start
    """
)

_FOLLOW_UPS_SQL = text(
    """
    SELECT id, company, role_title, status::text AS status, follow_up_at,
           follow_up_at < CAST(:now AS timestamptz) AS overdue
    FROM applications
    WHERE user_id = :user_id
      AND follow_up_at IS NOT NULL
      AND status IN ('wishlist', 'applied', 'interviewing', 'offer')
      AND follow_up_at < CAST(:now AS timestamptz) + interval '14 days'
    ORDER BY follow_up_at
    LIMIT :limit
    """
)

_OVERDUE_COUNT_SQL = text(
    """
    SELECT count(*) FROM applications
    WHERE user_id = :user_id
      AND follow_up_at < CAST(:now AS timestamptz)
      AND status IN ('wishlist', 'applied', 'interviewing', 'offer')
    """
)


class StatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self, user_id: uuid.UUID) -> dict[str, Any]:
        row = (await self.session.execute(_SUMMARY_SQL, {"user_id": user_id})).mappings().one()
        return dict(row)

    async def by_status(self, user_id: uuid.UUID) -> dict[str, int]:
        rows = (await self.session.execute(_BY_STATUS_SQL, {"user_id": user_id})).all()
        return {str(r.status): int(r.n) for r in rows}

    async def weekly(self, user_id: uuid.UUID, now: datetime) -> list[tuple[date, int]]:
        rows = (await self.session.execute(_WEEKLY_SQL, {"user_id": user_id, "now": now})).all()
        return [(r.week_start, int(r.n)) for r in rows]

    async def follow_ups(
        self, user_id: uuid.UUID, now: datetime, limit: int = 10
    ) -> list[dict[str, Any]]:
        rows = await self.session.execute(
            _FOLLOW_UPS_SQL, {"user_id": user_id, "now": now, "limit": limit}
        )
        return [dict(r) for r in rows.mappings().all()]

    async def overdue_count(self, user_id: uuid.UUID, now: datetime) -> int:
        n = await self.session.scalar(_OVERDUE_COUNT_SQL, {"user_id": user_id, "now": now})
        return int(n or 0)

"""initial schema: users, auth tokens, applications, events, resumes, AI analyses, job queue

Revision ID: 0001
Revises: 
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPLICATION_STATUS = postgresql.ENUM(
    "wishlist", "applied", "interviewing", "offer", "rejected", "withdrawn",
    name="application_status", create_type=False,
)
EVENT_TYPE = postgresql.ENUM(
    "created", "status_changed", "follow_up_overdue",
    name="application_event_type", create_type=False,
)
ANALYSIS_STATUS = postgresql.ENUM(
    "queued", "running", "succeeded", "failed", name="analysis_status", create_type=False
)
JOB_STATUS = postgresql.ENUM(
    "queued", "running", "succeeded", "failed", name="job_status", create_type=False
)
ALL_ENUMS = (APPLICATION_STATUS, EVENT_TYPE, ANALYSIS_STATUS, JOB_STATUS)



def upgrade() -> None:
    # Trigram index support for fuzzy company search (available on Neon and stock Postgres).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    bind = op.get_bind()
    for enum in ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table('jobs',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('status', JOB_STATUS, server_default='queued', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default=sa.text('4'), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=128), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('dedupe_key', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs'))
    )
    op.create_index('ix_jobs_claimable', 'jobs', ['run_after', 'id'], unique=False, postgresql_where=sa.text("status = 'queued'"))
    op.create_index('ix_jobs_running_locked_at', 'jobs', ['locked_at'], unique=False, postgresql_where=sa.text("status = 'running'"))
    op.create_index('uq_jobs_active_dedupe_key', 'jobs', ['dedupe_key'], unique=True, postgresql_where=sa.text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"))
    op.create_table('users',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=True),
    sa.Column('is_demo', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_demo_template', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('demo_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index('ix_users_demo_expires_at', 'users', ['demo_expires_at'], unique=False, postgresql_where=sa.text('is_demo'))
    op.create_index('uq_users_email', 'users', ['email'], unique=True)
    op.create_table('applications',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('company', sa.String(length=200), nullable=False),
    sa.Column('role_title', sa.String(length=200), nullable=False),
    sa.Column('job_url', sa.String(length=2048), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=True),
    sa.Column('salary_min', sa.Integer(), nullable=True),
    sa.Column('salary_max', sa.Integer(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('status', APPLICATION_STATUS, server_default='wishlist', nullable=False),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('follow_up_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('follow_up_flagged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('job_description', sa.Text(), nullable=True),
    sa.Column('search_vector', postgresql.TSVECTOR(), sa.Computed("setweight(to_tsvector('english', coalesce(company, '')), 'A') || setweight(to_tsvector('english', coalesce(role_title, '')), 'A') || setweight(to_tsvector('english', coalesce(location, '')), 'B') || setweight(to_tsvector('english', coalesce(notes, '')), 'C')", persisted=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name=op.f('ck_applications_currency_iso4217')),
    sa.CheckConstraint('salary_min IS NULL OR salary_max IS NULL OR salary_min <= salary_max', name=op.f('ck_applications_salary_range_valid')),
    sa.CheckConstraint('salary_min IS NULL OR salary_min >= 0', name=op.f('ck_applications_salary_min_non_negative')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_applications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_applications'))
    )
    op.create_index('ix_applications_company_trgm', 'applications', ['company'], unique=False, postgresql_using='gin', postgresql_ops={'company': 'gin_trgm_ops'})
    op.create_index('ix_applications_follow_up_at', 'applications', ['follow_up_at'], unique=False, postgresql_where=sa.text('follow_up_at IS NOT NULL'))
    op.create_index('ix_applications_search_vector', 'applications', ['search_vector'], unique=False, postgresql_using='gin')
    op.create_index('ix_applications_user_id_applied_at', 'applications', ['user_id', 'applied_at'], unique=False)
    op.create_index('ix_applications_user_id_created_at', 'applications', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_applications_user_id_status', 'applications', ['user_id', 'status'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('family_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by_id', sa.UUID(), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['replaced_by_id'], ['refresh_tokens.id'], name=op.f('fk_refresh_tokens_replaced_by_id_refresh_tokens'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens'))
    )
    op.create_index('ix_refresh_tokens_family_id', 'refresh_tokens', ['family_id'], unique=False)
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'], unique=False)
    op.create_index('uq_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'], unique=True)
    op.create_table('resumes',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_text', sa.Text(), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_resumes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resumes')),
    sa.UniqueConstraint('user_id', 'version', name='uq_resumes_user_id_version')
    )
    op.create_index('uq_resumes_one_active_per_user', 'resumes', ['user_id'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('ai_analyses',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('resume_id', sa.UUID(), nullable=True),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('status', ANALYSIS_STATUS, server_default='queued', nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_ai_analyses_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_ai_analyses_job_id_jobs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], name=op.f('fk_ai_analyses_resume_id_resumes'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_analyses'))
    )
    op.create_index('ix_ai_analyses_application_id_created_at', 'ai_analyses', ['application_id', 'created_at'], unique=False)
    op.create_index('ix_ai_analyses_resume_id', 'ai_analyses', ['resume_id'], unique=False)
    op.create_table('application_events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('event_type', EVENT_TYPE, nullable=False),
    sa.Column('from_status', APPLICATION_STATUS, nullable=True),
    sa.Column('to_status', APPLICATION_STATUS, nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_events_application_id_applications'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_events'))
    )
    op.create_index('ix_application_events_application_id_occurred_at', 'application_events', ['application_id', 'occurred_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_application_events_application_id_occurred_at', table_name='application_events')
    op.drop_table('application_events')
    op.drop_index('ix_ai_analyses_resume_id', table_name='ai_analyses')
    op.drop_index('ix_ai_analyses_application_id_created_at', table_name='ai_analyses')
    op.drop_table('ai_analyses')
    op.drop_index('uq_resumes_one_active_per_user', table_name='resumes', postgresql_where=sa.text('is_active'))
    op.drop_table('resumes')
    op.drop_index('uq_refresh_tokens_token_hash', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_family_id', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index('ix_applications_user_id_status', table_name='applications')
    op.drop_index('ix_applications_user_id_created_at', table_name='applications')
    op.drop_index('ix_applications_user_id_applied_at', table_name='applications')
    op.drop_index('ix_applications_search_vector', table_name='applications', postgresql_using='gin')
    op.drop_index('ix_applications_follow_up_at', table_name='applications', postgresql_where=sa.text('follow_up_at IS NOT NULL'))
    op.drop_index('ix_applications_company_trgm', table_name='applications', postgresql_using='gin', postgresql_ops={'company': 'gin_trgm_ops'})
    op.drop_table('applications')
    op.drop_index('uq_users_email', table_name='users')
    op.drop_index('ix_users_demo_expires_at', table_name='users', postgresql_where=sa.text('is_demo'))
    op.drop_table('users')
    op.drop_index('uq_jobs_active_dedupe_key', table_name='jobs', postgresql_where=sa.text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"))
    op.drop_index('ix_jobs_running_locked_at', table_name='jobs', postgresql_where=sa.text("status = 'running'"))
    op.drop_index('ix_jobs_claimable', table_name='jobs', postgresql_where=sa.text("status = 'queued'"))
    op.drop_table('jobs')
    bind = op.get_bind()
    for enum in reversed(ALL_ENUMS):
        enum.drop(bind, checkfirst=True)

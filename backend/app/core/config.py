"""Application settings, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General -----------------------------------------------------------------
    app_name: str = "AI Job Tracker API"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True

    # --- Database ----------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/jobtracker"
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- Auth --------------------------------------------------------------------
    jwt_secret: str = Field(
        default="dev-insecure-secret-change-me-please-0123456789", min_length=32
    )
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    refresh_cookie_name: str = "ajt_refresh"
    refresh_cookie_path: str = "/api/v1/auth"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None

    # --- HTTP --------------------------------------------------------------------
    frontend_origin: str = "http://localhost:3000"
    trust_proxy_headers: bool = True

    # --- Rate limiting / cache ---------------------------------------------------
    redis_url: str | None = None
    auth_rate_limit: int = 10
    auth_rate_window_seconds: int = 60
    stats_cache_ttl_seconds: int = 60

    # --- LLM ---------------------------------------------------------------------
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = 45.0

    # --- Uploads -----------------------------------------------------------------
    max_upload_bytes: int = 5 * 1024 * 1024

    # --- Background worker -------------------------------------------------------
    run_worker_in_api: bool = True
    worker_poll_interval_seconds: float = 1.0
    worker_concurrency: int = 2
    job_max_attempts: int = 4
    job_backoff_base_seconds: float = 5.0
    job_lock_timeout_seconds: int = 300
    scheduler_interval_seconds: int = 300

    # --- Demo mode ---------------------------------------------------------------
    demo_enabled: bool = True
    demo_ttl_hours: int = 24

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg(cls, v: str) -> str:
        # Neon/Render hand out "postgres://" or "postgresql://" URLs; normalise to asyncpg.
        if v.startswith("postgres://"):
            v = "postgresql://" + v.removeprefix("postgres://")
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v.removeprefix("postgresql://")
        return v

    @field_validator("redis_url", "groq_api_key", "cookie_domain", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

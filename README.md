# AI Job Tracker

[![CI](https://github.com/karimulislambd/ai-job-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/karimulislambd/ai-job-tracker/actions/workflows/ci.yml)
![Python 3.11](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs)
![Coverage 98%](https://img.shields.io/badge/coverage-98%25-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

**Track your job search like a sales pipeline, and let AI tell you how well your CV fits each role.**

AI Job Tracker is a full-stack SaaS app: a Kanban board of job applications with a
status-change timeline, a dashboard of search analytics computed in SQL, versioned CV
uploads, and an **AI match analysis** (Groq · GPT-OSS 120B) that scores your CV against
a job description and writes tailored CV bullets and a cover-letter draft.

I built it to show **backend engineering**, not just an LLM call: a normalized
PostgreSQL schema built with Alembic migrations, JWT auth with rotating refresh tokens,
strict per-tenant isolation, a **Postgres-backed job queue** (`FOR UPDATE SKIP LOCKED`)
with retries and backoff, SQL aggregations, and 128 integration tests against a real database.

> **Live demo:** _coming soon: `https://<your-app>.vercel.app`_. Click **“Try the demo”**
> to get a private, pre-filled account. No sign-up needed.
> API docs: `https://<your-api>.onrender.com/docs`

| Kanban board | AI match analysis |
|---|---|
| ![Kanban board](docs/screenshots/board.png) | ![AI analysis](docs/screenshots/analysis.png) |
| **Dashboard (dark mode)** | **Mobile** |
| ![Dashboard](docs/screenshots/dashboard-dark.png) | <img src="docs/screenshots/mobile-board.png" alt="Mobile board" width="300"> |

More screenshots: [landing](docs/screenshots/landing.png) ·
[CV versions](docs/screenshots/cv.png) · [board (dark)](docs/screenshots/board-dark.png) ·
[analysis (dark)](docs/screenshots/analysis-dark.png) · [dashboard (light)](docs/screenshots/dashboard.png).
These screenshots come from the running app with seeded demo data. They were captured
by a Playwright script that also tests the main flows end to end.

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Data model](#data-model)
- [API overview](#api-overview)
- [Key engineering decisions](#key-engineering-decisions)
- [Local development](#local-development)
- [Configuration](#configuration)
- [Deployment: Neon → Render → Vercel](#deployment-neon--render--vercel)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)

## Features

- **Auth.** Register and log in with a 15-minute JWT access token and a **rotating
  refresh token** in an httpOnly cookie. Logout revokes the token family. The auth
  endpoints are rate-limited.
- **Applications.** Full CRUD with filters (status, company, applied-date range),
  **full-text search** (weighted `tsvector` plus substring fallback), sorting and
  pagination. Moving an application to a new status **records an event in the same transaction**.
- **Kanban board.** Drag and drop works with a mouse, touch or keyboard, with screen-reader
  announcements. Moves update optimistically and roll back if the API call fails.
- **CV upload.** Uploads are checked for size, MIME type and PDF magic bytes. The text
  is extracted with `pypdf` (in a threadpool) and saved as a new **versioned, active resume**.
- **AI match analysis.** `POST /applications/{id}/analyze` returns `202 Accepted` and
  enqueues a job. A worker calls Groq in JSON mode and validates the reply against a
  Pydantic schema: a 0–100 score, matched and missing skills, strengths, gaps, 3–5
  tailored CV bullets and a cover letter. Failed jobs retry with exponential backoff.
  The UI polls until the result is ready.
- **Job queue and scheduler.** The queue lives in Postgres and workers claim jobs with
  `SKIP LOCKED`. Workers run inside the API process by default (good for free hosting)
  or standalone with `python -m app.worker`. Scheduled jobs flag overdue follow-ups and
  delete expired demo users.
- **Dashboard.** Counts per status, response rate, interview rate, offer rate, average
  days to first response, applications per week (last 12 weeks) and upcoming follow-ups.
  It is **all SQL** and cached per user.
- **Demo mode.** `POST /auth/demo` clones a seeded template account into a fresh,
  isolated user in **one SQL statement**. Timestamps are shifted so the data always looks
  current. Demo users are deleted after 24 hours.
- **Optional Redis** for rate limiting and caching. If `REDIS_URL` is unset, in-memory
  fallbacks are used.
- **Operations.** `/health` includes a DB check, OpenAPI docs are at `/docs`, every error
  uses one envelope, logs are structured JSON with request ids, CORS is restricted to
  the frontend, and the Docker image runs as a non-root user.

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    UI["Next.js 16 app<br/>React 19 · Tailwind v4<br/>access token in memory"]
  end
  subgraph Vercel
    RW["Rewrites /api/* → API<br/>(refresh cookie stays first-party)"]
  end
  subgraph Render["Render · Docker (free plan)"]
    direction TB
    API["FastAPI<br/>api → services → repositories"]
    W["Worker<br/>(asyncio task in the API process)"]
    S["Scheduler<br/>(overdue follow-ups, demo cleanup,<br/>stale-lock recovery)"]
  end
  DB[("PostgreSQL 16 · Neon<br/>app data + jobs table")]
  RD[("Redis (optional)<br/>rate limits + stats cache")]
  G["Groq API<br/>openai/gpt-oss-120b"]

  UI -->|HTTPS| RW --> API
  API -->|async SQLAlchemy / asyncpg| DB
  API -.-> RD
  W -->|"UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED)"| DB
  S -->|"INSERT … ON CONFLICT DO NOTHING (dedupe key)"| DB
  W -->|JSON mode| G
```

**The backend is layered.** Routers in `api/` parse and validate HTTP. `services/` holds
the use-cases and owns the transaction boundaries. `repositories/` holds all SQL, and
every query is scoped by `user_id`. `models/` holds the SQLAlchemy 2.0 ORM classes and
`schemas/` the Pydantic v2 models. The DB session and the current user are injected with
FastAPI dependencies.

How an AI analysis flows through the system:

```mermaid
sequenceDiagram
  participant UI as Next.js UI
  participant API as FastAPI
  participant DB as Postgres
  participant W as Worker
  participant LLM as Groq
  UI->>API: POST /applications/{id}/analyze
  API->>DB: INSERT ai_analyses (queued) + INSERT jobs (one transaction)
  API-->>UI: 202 {analysis_id, poll_url}
  loop every 1.5s
    UI->>API: GET /analyses/{id}
    API-->>UI: queued / running / succeeded / failed
  end
  W->>DB: claim job (FOR UPDATE SKIP LOCKED), attempts += 1
  W->>DB: analysis.status = running (commit, visible to pollers)
  W->>LLM: chat.completions (response_format=json_object)
  LLM-->>W: JSON
  alt valid against MatchResult schema
    W->>DB: store result, tokens and timings, job succeeded
  else invalid JSON / 429 / 5xx
    W->>DB: job re-queued, run_after = now() + backoff, last_error saved
  else attempts exhausted or non-retryable (4xx)
    W->>DB: job failed, analysis failed with error
  end
```

## Data model

All tables are created **only by Alembic migrations**. A test fails the build if the
ORM models and the migrations drift apart.

```mermaid
erDiagram
  users ||--o{ applications : owns
  users ||--o{ resumes : owns
  users ||--o{ refresh_tokens : has
  applications ||--o{ application_events : "timeline"
  applications ||--o{ ai_analyses : "analyzed by"
  resumes ||--o{ ai_analyses : "used in"
  jobs ||--o| ai_analyses : "processes"

  users {
    uuid id PK
    varchar email UK "lower-cased"
    varchar password_hash "argon2id"
    bool is_demo
    bool is_demo_template
    timestamptz demo_expires_at "partial index WHERE is_demo"
  }
  refresh_tokens {
    uuid id PK
    uuid user_id FK
    uuid family_id "rotation chain"
    char64 token_hash UK "sha256, raw token never stored"
    timestamptz expires_at
    timestamptz revoked_at
    uuid replaced_by_id FK
  }
  applications {
    uuid id PK
    uuid user_id FK
    varchar company "GIN trigram index"
    varchar role_title
    varchar job_url
    varchar location
    int salary_min "CHECK >= 0, <= salary_max"
    int salary_max
    char3 currency "CHECK ISO-4217 shape"
    application_status status "enum"
    timestamptz applied_at
    timestamptz follow_up_at "partial index"
    timestamptz follow_up_flagged_at
    text notes
    text job_description
    tsvector search_vector "GENERATED, GIN index"
  }
  application_events {
    bigint id PK
    uuid application_id FK
    event_type event_type "created | status_changed | follow_up_overdue"
    application_status from_status
    application_status to_status
    text note
    timestamptz occurred_at
  }
  resumes {
    uuid id PK
    uuid user_id FK
    int version "UNIQUE (user_id, version)"
    text content_text
    bool is_active "UNIQUE (user_id) WHERE is_active"
  }
  ai_analyses {
    uuid id PK
    uuid application_id FK
    uuid resume_id FK
    bigint job_id FK
    analysis_status status
    jsonb result
    text error
    varchar model
    int prompt_tokens
    int completion_tokens
    int duration_ms
  }
  jobs {
    bigint id PK
    varchar type
    jsonb payload
    job_status status
    int attempts
    int max_attempts
    timestamptz run_after "partial index WHERE status='queued'"
    timestamptz locked_at
    varchar locked_by
    text last_error
    varchar dedupe_key "UNIQUE WHERE status IN (queued, running)"
  }
```

## API overview

Base path `/api/v1`. Interactive docs are at **`/docs`** (Swagger) and `/redoc`. Errors
always look like this:

```json
{ "error": { "code": "not_found", "message": "Application not found", "details": null, "request_id": "4f1c…" } }
```

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/register` | Create an account. Returns an access token and sets the refresh cookie. |
| `POST` | `/auth/login` | Log in (rate-limited per IP). |
| `POST` | `/auth/refresh` | Rotate the refresh cookie and return a new access token. Replaying an old token revokes the family. |
| `POST` | `/auth/logout` | Revoke the refresh-token family and clear the cookie. |
| `POST` | `/auth/demo` | Log in as a fresh, isolated demo user (expires in 24h). |
| `GET` | `/auth/me` | Current user. |
| `GET` | `/applications` | List applications. Query params: `status` (repeatable), `company`, `q` (full-text), `applied_from`, `applied_to`, `sort`, `limit`, `offset`. |
| `POST` | `/applications` | Create an application (records a `created` event). |
| `GET` / `PATCH` / `DELETE` | `/applications/{id}` | Read, partially update or delete an application. |
| `PATCH` | `/applications/{id}/status` | Change status with an optional note (records an event; idempotent). |
| `GET` | `/applications/{id}/events` | Status timeline. |
| `POST` | `/applications/{id}/analyze` | **202**: enqueue an AI analysis. |
| `GET` | `/applications/{id}/analyses` | Analysis history. |
| `GET` | `/analyses/{id}` | Poll an analysis's status and result. |
| `POST` | `/resumes` | Upload a PDF CV (multipart). It becomes the active version. |
| `GET` | `/resumes`, `/resumes/active`, `/resumes/{id}` | List versions, get the active one, get one by id. |
| `POST` | `/resumes/{id}/activate` | Switch the active version. |
| `GET` | `/stats/dashboard` | Aggregated dashboard metrics. |
| `GET` | `/health` | Liveness check plus a `SELECT 1` against the database. |

## Key engineering decisions

**Why a Postgres job queue instead of Celery.** The workload is a few LLM calls per user,
which doesn't justify a second stateful system to run. A broker such as Redis or RabbitMQ
would also be one more thing to break on a free host. Keeping jobs in Postgres gives:

- **Atomic enqueue.** The `ai_analyses` row and its job are inserted in the same
  transaction. A job never exists without its analysis, and vice versa (no dual-write problem).
- **Durability and visibility for free.** Every attempt, error and timestamp is a row you
  can query.
- **One dependency.** That matters on free tiers: Render has no free background workers,
  so the worker runs as an asyncio task inside the API process. The same code runs
  standalone with `python -m app.worker` when you scale out (`RUN_WORKER_IN_API=false`).

Celery becomes the better choice at much higher throughput, or when you need its routing,
canvas or beat ecosystem.

**Why `SELECT … FOR UPDATE SKIP LOCKED`.** Workers claim jobs with a single statement:
`UPDATE jobs SET status='running', attempts=attempts+1 … WHERE id IN (SELECT id … FOR
UPDATE SKIP LOCKED LIMIT n) RETURNING *`.

- Each runnable row goes to exactly one worker.
- A worker never blocks on rows another worker is claiming.
- A partial index (`WHERE status='queued'`) keeps the hot path tiny.

Claims commit right away and each job runs in its own session, so a 20-second LLM call
never holds a lock or keeps a transaction open. Crashed workers are handled by a lock
timeout: the scheduler re-queues stale `running` jobs. Failures retry with **exponential
backoff plus jitter**, computed on the database clock so app/DB clock skew can't stall
retries. Errors are classified: LLM 4xx errors fail permanently, while 429, 5xx and
invalid JSON are retried. The final error stays in `jobs.last_error`. Recurring jobs use
a `dedupe_key` with a partial unique index, so several API instances never schedule the
same job twice. A test runs 6 concurrent workers on separate connections over 60 jobs and
asserts that no job is claimed twice and none is lost.

**Refresh-token rotation.**

- **Two tokens.** The access token is a short-lived JWT, kept in **memory only** in the
  browser (never in `localStorage`). The refresh token is 384 bits of random data in an
  **httpOnly** cookie scoped to `Path=/api/v1/auth`. Only its SHA-256 hash is stored.
- **Rotation.** Every refresh issues a new token in the same *family* and revokes the
  old one, setting `replaced_by_id`.
- **Theft detection.** If a revoked token is ever presented again, it was stolen or
  replayed, so the **whole family is revoked** and the user has to log in again (the
  OAuth 2.0 Security BCP pattern). A row lock serializes concurrent refreshes.
- **CSRF.** Cookie-authenticated endpoints also check the `Origin` header.
- **Other hardening.** Passwords are hashed with Argon2id. Login runs a dummy hash for
  unknown emails so response time doesn't reveal which accounts exist.

**Per-user isolation strategy.** Isolation is enforced **structurally in the repository
layer**:

- Every repository method for user-owned data takes `user_id` and adds
  `WHERE user_id = :uid`. There is deliberately no unscoped "get by id"; the worker's one
  unscoped read is clearly named.
- Child resources (events, analyses) are scoped through a join to their parent
  application.
- Requests for another user's resources return **404, not 403**, so the API doesn't
  reveal that they exist.
- An analysis can only use the requesting user's own active CV.
- The test suite has a cross-user matrix: user B calls every id-taking endpoint on user
  A's application, resume and analysis, and must get 404 with no side effects.

Postgres Row-Level Security would add defense in depth (see the roadmap).

**Why SQL aggregation for stats.** The dashboard runs a handful of grouped queries with
`count(*) FILTER (WHERE …)`, CTEs, `generate_series` for the 12-week buckets, and the
event log for "first response" times.

- It costs O(1) round trips, and no rows reach Python.
- It stays correct as data grows and uses the composite `(user_id, …)` indexes.
- Metrics come from the **event log**, so withdrawing after an interview doesn't erase
  the fact that it was an interview.
- Results are cached per user (60s TTL) and invalidated on every write.
- A test checks every number against hand-computed values for a fixed dataset.

**Other choices.**

- **UUID primary keys** for user-facing resources (not enumerable). `bigint` identity
  keys for jobs and events (ordering, cheap).
- **Generated `tsvector` column** with weights (company/role > location > notes) and
  `websearch_to_tsquery`, plus an `ILIKE` fallback backed by a trigram index for partial
  words. LIKE wildcards in user input are escaped.
- **Demo cloning in one statement.** Data-modifying CTEs make the clone atomic and fast.
  An id-mapping CTE preserves every foreign key (applications → events/analyses, resumes →
  analyses).
- **LLM output is never trusted.** It is parsed as JSON, validated against a Pydantic
  schema with bounds, normalized (deduplicated, trimmed), and anything else is retried.
  Without `GROQ_API_KEY`, a deterministic **offline heuristic client** produces the same
  contract, so local dev, CI and demos never depend on the network.
- **Neon-ready connection handling.** `sslmode` and `channel_binding` are translated for
  asyncpg, the prepared-statement cache is disabled behind PgBouncer (`-pooler` hosts),
  and the session timezone is pinned to UTC.

## Local development

### Docker Compose (everything)

```bash
cp backend/.env.example backend/.env    # optional: add GROQ_API_KEY
docker compose up --build
```

- Frontend: http://localhost:3000. Click **Try the demo**.
- API docs: http://localhost:8000/docs
- The API container runs `alembic upgrade head` on start and seeds the demo template.

### Native (hot reload)

You need Python 3.11, Node 20.9+ and PostgreSQL 16. Redis is optional.

```bash
# backend
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                    # set DATABASE_URL
alembic upgrade head
python -m app.seed                      # demo template (also done automatically on startup)
uvicorn app.main:app --reload           # http://localhost:8000

# frontend (second terminal)
cd frontend
cp .env.example .env.local              # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                             # http://localhost:3000
```

A sample CV to try the upload flow is in [`docs/sample-cv.pdf`](docs/sample-cv.pdf).

## Configuration

### Backend (`backend/.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local Postgres | Any `postgres://`, `postgresql://` or `postgresql+asyncpg://` URL. Neon query params are handled. |
| `JWT_SECRET` | dev value | **Required in production**, at least 32 random characters. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Comma-separated list of allowed origins (CORS and CSRF Origin check). |
| `COOKIE_SECURE` | `false` | `true` in production. |
| `COOKIE_SAMESITE` | `lax` | `lax` for proxy mode, `none` for direct cross-site mode. |
| `COOKIE_DOMAIN` | unset | Usually leave unset. |
| `GROQ_API_KEY` | unset | Enables Groq. Without it, the offline heuristic is used. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | |
| `REDIS_URL` | unset | Optional, for rate limits and the stats cache. |
| `AUTH_RATE_LIMIT` / `AUTH_RATE_WINDOW_SECONDS` | `10` / `60` | Per-IP limit on login, register and demo. Refresh gets 6× the limit. |
| `RUN_WORKER_IN_API` | `true` | Set `false` when running `python -m app.worker` separately. |
| `WORKER_CONCURRENCY`, `JOB_MAX_ATTEMPTS`, `JOB_BACKOFF_BASE_SECONDS` | `2`, `4`, `5` | Queue tuning. |
| `DEMO_ENABLED` / `DEMO_TTL_HOURS` | `true` / `24` | Demo mode. |
| `ACCESS_TOKEN_TTL_MINUTES` / `REFRESH_TOKEN_TTL_DAYS` | `15` / `14` | Token lifetimes. |
| `MAX_UPLOAD_BYTES` | `5242880` | CV size limit (5 MB). |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | Logging. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `5` | Connection pool. |

### Frontend (`frontend/.env.example`)

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | API origin for **direct mode** (e.g. `http://localhost:8000`). Leave empty for proxy mode. It is inlined at build time. |
| `API_PROXY_TARGET` | Backend origin for **proxy mode**. Next.js rewrites `/api/*` and `/health` to it. |

## Deployment: Neon → Render → Vercel

The **recommended setup is proxy mode**:

- The browser only ever talks to the Vercel domain.
- Vercel rewrites `/api/*` to Render.
- The refresh cookie is therefore **first-party** and survives Safari ITP and
  third-party-cookie blocking.

### 1. Neon (database)

1. Create a project at [neon.tech](https://neon.tech). Choose **Postgres 16** and the
   region closest to your Render region (e.g. AWS `eu-central-1` for Render Frankfurt).
2. Under **Connect**, copy the connection string. The **direct** (non-pooled) host is
   recommended. The pooled `-pooler` host also works, because the app disables
   asyncpg's statement cache for it.
3. That's it: tables, enums, indexes and the `pg_trgm` extension are created by
   `alembic upgrade head` when the API starts.

### 2. Render (API)

1. Go to **New → Blueprint**, pick this repository, and Render reads
   [`render.yaml`](render.yaml). It defines a free Docker web service with `rootDir: backend`.
   (Manual alternative: **New → Web Service → Docker**, root directory `backend`, health
   check path `/health`.)
2. Fill in the secret environment variables:
   - `DATABASE_URL`: the Neon string from step 1.
   - `FRONTEND_ORIGIN`: your Vercel URL, e.g. `https://ai-job-tracker.vercel.app` (no
     trailing slash; comma-separate several).
   - `GROQ_API_KEY`: from [console.groq.com](https://console.groq.com/keys).
   - `JWT_SECRET` is generated automatically by the blueprint.
3. Deploy, then open `https://<service>.onrender.com/health` and `/docs`.
4. Free instances sleep after ~15 minutes idle, and the first request takes ~30–60s.
   The landing page shows a "waking up the server" hint.

### 3. Vercel (frontend)

1. **Add New → Project**, import the repo, and set **Root Directory = `frontend`**
   (Next.js is auto-detected).
2. Environment variables for proxy mode:
   - `API_PROXY_TARGET` = `https://<service>.onrender.com`
   - leave `NEXT_PUBLIC_API_URL` **unset**
3. Deploy. Then make sure Render's `FRONTEND_ORIGIN` matches the production URL exactly,
   and redeploy the API if you changed it.

### Cookie and CORS settings across domains

| Mode | Frontend env | Backend env | Notes |
|---|---|---|---|
| **Proxy (recommended)** | `API_PROXY_TARGET=https://api.onrender.com` | `COOKIE_SECURE=true`, `COOKIE_SAMESITE=lax`, `FRONTEND_ORIGIN=https://app.vercel.app` | Cookie is first-party for the Vercel domain. This is the default in `render.yaml`. |
| **Direct cross-site** | `NEXT_PUBLIC_API_URL=https://api.onrender.com` | `COOKIE_SECURE=true`, **`COOKIE_SAMESITE=none`**, `FRONTEND_ORIGIN=https://app.vercel.app` | The browser sends the cookie cross-site (`SameSite=None; Secure`, CORS with credentials). Browsers that block third-party cookies (Safari, Firefox strict mode) drop it, so sessions won't survive a reload there. |

CORS only allows `FRONTEND_ORIGIN` with credentials. The refresh and logout endpoints
also reject any other `Origin` (CSRF defense).

## Testing

```bash
cd backend
# needs a Postgres database; defaults to postgres:postgres@localhost:5432/jobtracker_test
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/jobtracker_test
pytest --cov                 # 128 tests, ~98% line coverage
ruff check . && ruff format --check . && mypy   # mypy --strict on app code
```

**How the tests work.**

- They are **integration tests against real PostgreSQL**. The schema is built by running
  the real migrations (upgrade → downgrade → upgrade).
- Each test runs inside an outer transaction that is **rolled back** afterwards. The code
  under test commits to savepoints, so services behave exactly as in production.
- The concurrency tests use separate connections and clean up after themselves.
- **The network is never called.** Groq is mocked at the HTTP transport layer
  (`httpx.MockTransport`) so the real SDK request and response handling is exercised.

| Area | What's covered |
|---|---|
| Auth (21) | Register/login/validation, JWT claims, expired/forged/wrong-type tokens, refresh rotation, **reuse detection revokes the family**, logout revocation, Origin check, rate limiting (429 + `Retry-After`), secure cookie flags. |
| Isolation (4) | User B gets **404 on all 10 id-taking endpoints** for A's application, resume and analysis, with no side effects. Collections, search and stats only show own data. |
| Applications (23) | CRUD, validation, status events (no-op transitions skipped), filters, LIKE-escaping, FTS + partial match, sorting, pagination stability. |
| Stats (3) | Every metric checked against hand-computed values, the empty state, cache invalidation on writes. |
| Job queue (13) | Claim/complete, FIFO by `run_after`, backoff bounds, retry → terminal failure, dedupe, stale-lock recovery, **SKIP LOCKED with 2 and 6 concurrent connections**. |
| AI analysis (29) | 202 + polling, success path, **invalid JSON retried then succeeds**, schema violations failing after max attempts, Groq HTTP errors (429/5xx retryable, 4xx not), idempotent redelivery. |
| CV upload (11) | Versioning, activation, wrong type, extension, magic bytes, empty, corrupt, no text, too many pages, 413 too large. |
| Demo (7) | Full clone with remapped FKs, time shift, isolation between demo users and the template, expiry, cleanup cascade. |
| Maintenance (1) | Overdue follow-ups flagged in one data-modifying CTE across users, only active statuses, idempotent, with a timeline event. |
| Platform (16) | Health, error envelope, request ids, CORS, OpenAPI, logging, settings and Neon URL handling, Redis and in-memory backends, lifespan, **models-vs-migrations drift**. |

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs:

- **Backend:** ruff, mypy, and pytest with `postgres:16` and `redis:7` service
  containers and a 90% coverage gate; an Alembic upgrade/check/downgrade.
- **Docker:** a backend image build.
- **Frontend:** lint, typecheck and a production build.

## Project structure

```
backend/
  app/
    api/            routers + dependencies (session, current user, rate limit, origin check)
    core/           config, security, errors, logging, middleware, cache, rate limiter
    db/             engine/session, declarative base with naming conventions
    models/         SQLAlchemy 2.0 ORM models
    schemas/        Pydantic v2 request/response models (incl. the LLM output contract)
    repositories/   all SQL, always scoped by user
    services/       use-cases: auth, applications, resumes, analysis, stats, demo, LLM
    worker/         queue worker, handler registry, scheduler (python -m app.worker)
    seed/           demo template data (python -m app.seed)
  alembic/          migrations
  tests/            integration tests
frontend/
  src/app/          App Router pages: landing, login/register, (app)/board|applications/[id]|cv|dashboard
  src/components/   UI kit, app shell, forms, dialog, theme toggle, toasts
  src/lib/          typed API client, auth context, types, formatting
docker-compose.yml · render.yaml · .github/workflows/ci.yml
```

## Roadmap

- [ ] Postgres Row-Level Security as a second isolation layer (`SET app.user_id` per transaction)
- [ ] `LISTEN/NOTIFY` to wake workers instantly instead of polling every second
- [ ] Server-Sent Events for analysis progress instead of polling
- [ ] Keyset (cursor) pagination for very large boards
- [ ] Import from job-posting URLs (scrape + extract the JD)
- [ ] Email reminders for follow-ups (reusing the job queue)
- [ ] Frontend component tests and a Playwright E2E job in CI
- [ ] OpenTelemetry traces across API → queue → LLM

## License

[MIT](LICENSE) © Md Karimul Islam

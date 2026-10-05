"""Realistic sample data for the demo template account.

Companies are fictional. Dates are expressed as "days ago" relative to seeding time;
demo clones shift every timestamp so the data always looks current.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SAMPLE_CV = """Jordan Rahman
Backend Software Engineer — Dhaka, Bangladesh (open to remote)
jordan.rahman@example.com · github.com/jordan-demo

SUMMARY
Backend engineer with 4 years of experience designing REST APIs and data-intensive services
in Python. Comfortable owning features end to end: schema design, API, tests, CI/CD and
production monitoring.

SKILLS
Python, FastAPI, Django, SQLAlchemy, PostgreSQL, Redis, Celery, Docker, AWS (ECS, RDS, S3),
GitHub Actions, pytest, REST, JWT/OAuth, Linux, Git, TypeScript, React

EXPERIENCE
Software Engineer — Finlytics (fintech SaaS), 2022–present
- Designed and built a FastAPI service for invoice reconciliation processing 1.2M records/day.
- Cut p95 API latency from 820 ms to 190 ms by adding composite indexes and rewriting N+1
  ORM queries as SQL aggregations in PostgreSQL.
- Introduced a Postgres-backed job queue with retries and dead-lettering, replacing ad-hoc cron.
- Raised test coverage of the billing module from 41% to 88% with pytest integration tests.
- Mentored two junior engineers; led code reviews and wrote the team's API style guide.

Junior Backend Developer — ShopNest (e-commerce), 2020–2022
- Built Django REST endpoints for catalogue and checkout used by 80k monthly customers.
- Containerised services with Docker and set up GitHub Actions CI, reducing deploy time by 70%.
- Implemented JWT authentication with refresh tokens and role-based permissions.

PROJECTS
- Open-source contributor to a FastAPI pagination library (cursor pagination support).

EDUCATION
B.Sc. in Computer Science and Engineering — 2020
"""

JD_BACKEND_PYTHON = """We're hiring a Backend Engineer (Python) to build the APIs behind our
B2B analytics platform.

What you'll do
- Design and ship REST APIs with FastAPI and PostgreSQL
- Own data models, migrations and query performance
- Build reliable background processing (queues, retries, idempotency)
- Write thorough automated tests and participate in code review

Requirements
- 3+ years of professional Python experience
- Strong SQL and PostgreSQL knowledge (indexing, query plans)
- Experience with Docker and CI/CD (GitHub Actions)
- Familiarity with Redis and caching strategies
- Nice to have: Kubernetes, Terraform, observability (Prometheus, Grafana)
"""

JD_PLATFORM = """Platform Engineer — Developer Infrastructure

You will build the internal platform our 60 product engineers deploy on.
- Operate Kubernetes clusters on AWS (EKS) managed with Terraform
- Improve CI/CD pipelines and developer tooling
- Build observability: Prometheus, Grafana, OpenTelemetry
- Write automation in Go or Python

Requirements: Kubernetes in production, Terraform, AWS, Linux, one of Go/Python.
Nice to have: service mesh, Kafka.
"""

JD_FULLSTACK = """Full-Stack Engineer (TypeScript + Python)

Join a small product team shipping features weekly.
- Frontend: React, Next.js, TypeScript, Tailwind
- Backend: Python (FastAPI) services with PostgreSQL
- You care about UX, accessibility and testing (pytest, Playwright)

Requirements: 3+ years building web apps, strong TypeScript and React, solid REST API
experience, PostgreSQL. Nice to have: GraphQL, Docker.
"""

JD_DATA = """Data Engineer

Build batch and streaming pipelines that power our ML models.
- Airflow orchestration, Spark processing, Kafka streams
- Data modeling in PostgreSQL and a cloud warehouse
- Python and SQL daily

Requirements: Python, SQL, Airflow, Spark, Kafka. AWS or GCP. Nice to have: dbt, machine learning.
"""

JD_GO = """Senior Backend Engineer (Go)

Payments infrastructure team. High-throughput gRPC microservices in Go, PostgreSQL, Kafka,
Kubernetes. 5+ years backend experience, strong system design, on-call experience.
"""


@dataclass
class SeedApplication:
    company: str
    role_title: str
    location: str
    status: str
    # list of (status, days_ago) transitions after creation; first entry is the created status
    timeline: list[tuple[str, int]]
    salary: tuple[int, int, str] | None = None
    follow_up_in_days: int | None = None
    notes: str | None = None
    job_description: str | None = None
    job_url: str | None = None
    analysis: dict[str, Any] | None = field(default=None)


def _analysis(
    score: int, matched: list[str], missing: list[str], company: str, role: str
) -> dict[str, Any]:
    return {
        "match_score": score,
        "summary": (
            f"Strong backend profile for {company}'s {role} role: the CV shows production "
            f"experience with {', '.join(matched[:3])}. "
            + (f"Main gaps: {', '.join(missing[:2])}." if missing else "No major gaps found.")
        ),
        "matched_skills": matched,
        "missing_skills": missing,
        "strengths": [
            "Quantified performance work on PostgreSQL (p95 latency 820 ms → 190 ms)",
            "Has built a Postgres-backed job queue with retries — directly relevant",
            "Owns features end to end including CI/CD and testing",
        ],
        "gaps": [f"No production evidence of {m}" for m in missing[:3]],
        "cv_bullet_suggestions": [
            "Designed and shipped a FastAPI reconciliation service processing 1.2M records/day "
            "on PostgreSQL, with idempotent background jobs and automatic retries.",
            "Reduced p95 API latency by 77% (820 ms → 190 ms) by profiling query plans, adding "
            "composite indexes and replacing N+1 ORM access with SQL aggregations.",
            "Raised billing-module test coverage from 41% to 88% with pytest integration tests "
            "against a real PostgreSQL instance in GitHub Actions.",
            "Replaced ad-hoc cron scripts with a Postgres job queue (SKIP LOCKED) featuring "
            "exponential backoff and dead-lettering.",
        ],
        "cover_letter": (
            f"Dear {company} team,\n\nI'm excited to apply for the {role} position. For the past "
            "four years I've built Python backends where correctness and performance matter: at "
            "Finlytics I designed a FastAPI service that reconciles 1.2M records a day, cut p95 "
            "latency from 820 ms to 190 ms through careful PostgreSQL indexing, and replaced "
            "fragile cron jobs with a Postgres-backed queue with retries.\n\nYour focus on "
            "reliable APIs and data modelling is exactly the work I enjoy most, and I'd bring the "
            "same ownership — schema, API, tests and monitoring — to your team. I'd love to "
            "discuss how I can help.\n\nBest regards,\nJordan Rahman"
        ),
    }


APPLICATIONS: list[SeedApplication] = [
    SeedApplication(
        "Northwind Analytics",
        "Backend Engineer (Python)",
        "Remote (EU)",
        "offer",
        [("applied", 41), ("interviewing", 33), ("offer", 4)],
        salary=(70000, 85000, "EUR"),
        follow_up_in_days=2,
        notes="Offer received! Deadline to respond Friday. Negotiate remote stipend.",
        job_description=JD_BACKEND_PYTHON,
        job_url="https://jobs.example.com/northwind/backend",
        analysis=_analysis(
            88,
            ["python", "fastapi", "postgresql", "docker", "github actions", "redis"],
            ["kubernetes", "terraform"],
            "Northwind Analytics",
            "Backend Engineer",
        ),
    ),
    SeedApplication(
        "Lumen Health",
        "Software Engineer, APIs",
        "Berlin, Germany (hybrid)",
        "interviewing",
        [("applied", 22), ("interviewing", 12)],
        salary=(65000, 78000, "EUR"),
        follow_up_in_days=1,
        notes="System design round next. Review idempotency keys + rate limiting.",
        job_description=JD_BACKEND_PYTHON,
        analysis=_analysis(
            84,
            ["python", "fastapi", "postgresql", "docker", "redis"],
            ["kubernetes", "prometheus"],
            "Lumen Health",
            "Software Engineer, APIs",
        ),
    ),
    SeedApplication(
        "Quarry Logistics",
        "Platform Engineer",
        "Remote",
        "interviewing",
        [("applied", 18), ("interviewing", 9)],
        salary=(90000, 120000, "USD"),
        follow_up_in_days=-2,
        notes="Take-home: Terraform module for a VPC. Follow up with recruiter.",
        job_description=JD_PLATFORM,
        analysis=_analysis(
            56,
            ["python", "aws", "linux", "docker"],
            ["kubernetes", "terraform", "go", "prometheus", "grafana"],
            "Quarry Logistics",
            "Platform Engineer",
        ),
    ),
    SeedApplication(
        "Brightwave",
        "Full-Stack Engineer",
        "Amsterdam, Netherlands",
        "interviewing",
        [("applied", 15), ("interviewing", 5)],
        salary=(60000, 72000, "EUR"),
        follow_up_in_days=4,
        job_description=JD_FULLSTACK,
    ),
    SeedApplication(
        "Cobalt Payments",
        "Senior Backend Engineer (Go)",
        "London, UK",
        "rejected",
        [("applied", 38), ("interviewing", 30), ("rejected", 21)],
        salary=(85000, 105000, "GBP"),
        notes="Rejected after system design — they wanted more Go + Kafka depth.",
        job_description=JD_GO,
    ),
    SeedApplication(
        "Helix Robotics",
        "Python Developer",
        "Remote",
        "rejected",
        [("applied", 35), ("rejected", 27)],
        salary=(55000, 65000, "USD"),
    ),
    SeedApplication(
        "Tidepool Data",
        "Data Engineer",
        "Remote (APAC)",
        "rejected",
        [("applied", 29), ("rejected", 24)],
        job_description=JD_DATA,
        analysis=_analysis(
            48,
            ["python", "sql", "postgresql", "aws"],
            ["airflow", "spark", "kafka"],
            "Tidepool Data",
            "Data Engineer",
        ),
    ),
    SeedApplication(
        "Orbital Commerce",
        "Backend Developer",
        "Singapore",
        "applied",
        [("applied", 9)],
        salary=(7000, 9000, "SGD"),
        follow_up_in_days=-1,
        notes="Referred by Sam (ex-ShopNest).",
        job_description=JD_BACKEND_PYTHON,
    ),
    SeedApplication(
        "Kitewing",
        "Software Engineer II",
        "Toronto, Canada",
        "applied",
        [("applied", 7)],
        salary=(110000, 130000, "CAD"),
        follow_up_in_days=3,
    ),
    SeedApplication(
        "Mosaic Learning",
        "Backend Engineer",
        "Remote",
        "applied",
        [("applied", 5)],
        follow_up_in_days=6,
        job_description=JD_BACKEND_PYTHON,
    ),
    SeedApplication(
        "Verdant Energy",
        "API Engineer",
        "Copenhagen, Denmark",
        "applied",
        [("applied", 12)],
        salary=(600000, 700000, "DKK"),
        follow_up_in_days=-4,
    ),
    SeedApplication(
        "Polar Systems",
        "Backend Engineer, Integrations",
        "Remote (US time zones)",
        "applied",
        [("applied", 3)],
        salary=(100000, 125000, "USD"),
        follow_up_in_days=8,
    ),
    SeedApplication(
        "Sandbar Labs",
        "Junior Platform Engineer",
        "Dublin, Ireland",
        "applied",
        [("applied", 2)],
        follow_up_in_days=10,
        job_description=JD_PLATFORM,
    ),
    SeedApplication(
        "Fernway Travel",
        "Software Engineer (Django)",
        "Lisbon, Portugal",
        "applied",
        [("applied", 26)],
        salary=(45000, 55000, "EUR"),
        notes="No response after 3+ weeks. Probably ghosted.",
    ),
    SeedApplication(
        "Aster Insurance",
        "Backend Engineer",
        "Remote",
        "applied",
        [("applied", 45)],
        notes="Old application — consider withdrawing.",
    ),
    SeedApplication(
        "Driftwood Media",
        "Python Engineer",
        "Remote",
        "withdrawn",
        [("applied", 31), ("interviewing", 26), ("withdrawn", 17)],
        notes="Withdrew: role turned out to be mostly data scraping.",
    ),
    SeedApplication(
        "Ironclad Security",
        "Backend Engineer (Auth)",
        "Austin, TX",
        "withdrawn",
        [("applied", 20), ("withdrawn", 14)],
        notes="Required on-site 5 days/week.",
    ),
    SeedApplication(
        "Nimbus AI",
        "ML Platform Engineer",
        "Remote",
        "wishlist",
        [("wishlist", 4)],
        follow_up_in_days=5,
        notes="Apply after finishing the Kubernetes course.",
        job_description=JD_PLATFORM,
    ),
    SeedApplication(
        "Juniper Bank",
        "Senior Python Engineer",
        "Zurich, Switzerland",
        "wishlist",
        [("wishlist", 2)],
        salary=(120000, 140000, "CHF"),
        job_description=JD_BACKEND_PYTHON,
    ),
    SeedApplication(
        "Pinecrest Health",
        "Backend Engineer (FastAPI)",
        "Remote (EU)",
        "wishlist",
        [("wishlist", 1)],
        job_description=JD_BACKEND_PYTHON,
    ),
    SeedApplication(
        "Riverstone",
        "Full-Stack Developer",
        "Remote",
        "wishlist",
        [("wishlist", 6)],
        job_description=JD_FULLSTACK,
    ),
    SeedApplication(
        "Granite Cloud",
        "Site Reliability Engineer",
        "Remote",
        "rejected",
        [("applied", 52), ("interviewing", 46), ("rejected", 40)],
    ),
    SeedApplication(
        "Saffron Foods",
        "Backend Developer",
        "Dhaka, Bangladesh",
        "offer",
        [("applied", 60), ("interviewing", 50), ("offer", 38)],
        salary=(1800000, 2400000, "BDT"),
        notes="Verbal offer — on hold while finishing remote interview loops.",
    ),
    SeedApplication(
        "Wavelength",
        "Software Engineer, Backend",
        "Remote",
        "interviewing",
        [("applied", 25), ("interviewing", 16)],
        follow_up_in_days=0,
        notes="Waiting on feedback from the hiring manager round.",
    ),
]

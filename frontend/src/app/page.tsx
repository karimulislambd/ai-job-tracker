import {
  BarChart3,
  BrainCircuit,
  Database,
  FileText,
  GitBranch,
  KanbanSquare,
  ShieldCheck,
  Timer,
} from "lucide-react";
import Link from "next/link";

import { DemoButton } from "@/components/demo-button";
import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";

const FEATURES = [
  {
    icon: KanbanSquare,
    title: "Kanban pipeline",
    body: "Drag applications between stages. Every move is written to a status timeline.",
  },
  {
    icon: BrainCircuit,
    title: "AI match analysis",
    body: "Compare your CV with a job description: match score, skill gaps, tailored CV bullets and a cover-letter draft.",
  },
  {
    icon: BarChart3,
    title: "Search analytics",
    body: "Response rate, interview rate, time-to-response and weekly activity, computed in SQL.",
  },
  {
    icon: FileText,
    title: "Versioned CVs",
    body: "Upload a PDF; its text is extracted and stored as a new version you can switch between.",
  },
];

const ENGINEERING = [
  { icon: Database, text: "PostgreSQL + Alembic, normalized schema, full-text search" },
  { icon: Timer, text: "Postgres job queue with SKIP LOCKED, retries & backoff" },
  { icon: ShieldCheck, text: "JWT + rotating refresh tokens, strict per-user isolation" },
  { icon: GitBranch, text: "FastAPI · async SQLAlchemy · 98% test coverage · CI" },
];

export default function Home() {
  return (
    <div className="flex min-h-full flex-col">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-5">
        <Logo />
        <nav className="flex items-center gap-2 text-sm" aria-label="Account">
          <ThemeToggle />
          <Link href="/login" className="rounded-lg px-3 py-2 font-medium text-fg-muted hover:text-fg">
            Log in
          </Link>
          <Link
            href="/register"
            className="rounded-lg border border-border bg-surface px-3 py-2 font-medium hover:bg-surface-2"
          >
            Sign up
          </Link>
        </nav>
      </header>

      <main className="flex-1">
        <section className="mx-auto max-w-4xl px-4 pb-16 pt-12 text-center sm:pt-20">
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-fg-muted">
            <span className="size-1.5 rounded-full bg-emerald-500" aria-hidden />
            Open source · FastAPI + Next.js + Llama 3.3 70B
          </p>
          <h1 className="text-balance text-4xl font-semibold tracking-tight sm:text-6xl">
            Run your job search like a <span className="text-accent">pipeline</span>.
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-pretty text-lg text-fg-muted">
            Track every application on a Kanban board, see where your search is working, and let AI
            tell you how well your CV matches each role — and how to close the gap.
          </p>
          <div className="mt-9">
            <DemoButton />
          </div>
        </section>

        <section aria-labelledby="features" className="mx-auto max-w-6xl px-4 pb-16">
          <h2 id="features" className="sr-only">
            Features
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <div key={title} className="rounded-xl border border-border bg-surface p-5 shadow-xs">
                <Icon className="mb-3 size-5 text-accent" aria-hidden />
                <h3 className="font-semibold">{title}</h3>
                <p className="mt-1.5 text-sm text-fg-muted">{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section aria-labelledby="eng" className="border-t border-border bg-surface/60">
          <div className="mx-auto max-w-6xl px-4 py-12">
            <h2 id="eng" className="text-center text-sm font-semibold uppercase tracking-wider text-fg-subtle">
              Under the hood
            </h2>
            <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {ENGINEERING.map(({ icon: Icon, text }) => (
                <li key={text} className="flex items-start gap-3 text-sm text-fg-muted">
                  <Icon className="mt-0.5 size-4 shrink-0 text-fg" aria-hidden />
                  {text}
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>

      <footer className="border-t border-border py-6 text-center text-xs text-fg-subtle">
        Built by{" "}
        <a className="underline hover:text-fg" href="https://github.com/karimulislambd">
          Md Karimul Islam
        </a>{" "}
        ·{" "}
        <a className="underline hover:text-fg" href="https://github.com/karimulislambd/ai-job-tracker">
          Source on GitHub
        </a>
      </footer>
    </div>
  );
}

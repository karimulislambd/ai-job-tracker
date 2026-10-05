"use client";

import clsx from "clsx";
import { Check, Copy, Loader2, Sparkles, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { Analysis, Application } from "@/lib/types";

const POLL_MS = 1500;

function ScoreRing({ score }: { score: number }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const tone = score >= 75 ? "text-emerald-500" : score >= 50 ? "text-amber-500" : "text-rose-500";
  const label = score >= 75 ? "Strong match" : score >= 50 ? "Partial match" : "Weak match";
  return (
    <div className="flex items-center gap-4">
      <div className="relative size-20" role="img" aria-label={`Match score ${score} out of 100, ${label}`}>
        <svg viewBox="0 0 80 80" className="size-20 -rotate-90">
          <circle cx="40" cy="40" r={r} className="fill-none stroke-surface-2" strokeWidth="8" />
          <circle
            cx="40"
            cy="40"
            r={r}
            className={clsx("fill-none stroke-current transition-all duration-700", tone)}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={c}
            strokeDashoffset={c * (1 - score / 100)}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-xl font-semibold tabular-nums">
          {score}
        </span>
      </div>
      <div>
        <p className="font-semibold">{label}</p>
        <p className="text-sm text-fg-muted">out of 100</p>
      </div>
    </div>
  );
}

function Chips({ items, tone }: { items: string[]; tone: "good" | "bad" }) {
  if (!items.length) return <p className="text-sm text-fg-subtle">None</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((s) => (
        <li
          key={s}
          className={clsx(
            "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
            tone === "good"
              ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
              : "bg-rose-50 text-rose-800 dark:bg-rose-950 dark:text-rose-200",
          )}
        >
          {tone === "good" ? <Check className="size-3" aria-hidden /> : <span aria-hidden>–</span>}
          {s}
        </li>
      ))}
    </ul>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-surface-2 hover:text-fg"
      aria-label={`Copy ${label}`}
    >
      {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function Result({ analysis }: { analysis: Analysis }) {
  const r = analysis.result!;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <ScoreRing score={r.match_score} />
        <p className="text-xs text-fg-subtle">
          {analysis.model} · {analysis.completed_at && formatDateTime(analysis.completed_at)}
          {analysis.duration_ms != null && ` · ${(analysis.duration_ms / 1000).toFixed(1)}s`}
          {analysis.prompt_tokens != null &&
            ` · ${(analysis.prompt_tokens + (analysis.completion_tokens ?? 0)).toLocaleString()} tokens`}
        </p>
      </div>
      {r.summary && <p className="text-sm leading-relaxed text-fg-muted">{r.summary}</p>}
      <div className="grid gap-6 md:grid-cols-2">
        <section>
          <h4 className="mb-2 text-sm font-semibold">Matched skills</h4>
          <Chips items={r.matched_skills} tone="good" />
        </section>
        <section>
          <h4 className="mb-2 text-sm font-semibold">Missing skills</h4>
          <Chips items={r.missing_skills} tone="bad" />
        </section>
        <section>
          <h4 className="mb-2 text-sm font-semibold">Strengths</h4>
          <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
            {r.strengths.map((s) => <li key={s}>{s}</li>)}
          </ul>
        </section>
        <section>
          <h4 className="mb-2 text-sm font-semibold">Gaps</h4>
          {r.gaps.length ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
              {r.gaps.map((s) => <li key={s}>{s}</li>)}
            </ul>
          ) : (
            <p className="text-sm text-fg-subtle">No significant gaps found.</p>
          )}
        </section>
      </div>
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-sm font-semibold">Tailored CV bullets</h4>
          <CopyButton text={r.cv_bullet_suggestions.map((b) => `• ${b}`).join("\n")} label="CV bullets" />
        </div>
        <ul className="space-y-2">
          {r.cv_bullet_suggestions.map((b) => (
            <li key={b} className="rounded-lg border border-border bg-surface-2/50 px-3 py-2 text-sm">
              {b}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-sm font-semibold">Cover letter draft</h4>
          <CopyButton text={r.cover_letter} label="cover letter" />
        </div>
        <div className="whitespace-pre-line rounded-lg border border-border bg-surface-2/50 p-4 text-sm leading-relaxed">
          {r.cover_letter}
        </div>
      </section>
    </div>
  );
}

const STEP_LABEL: Record<string, string> = {
  queued: "Queued — waiting for a worker…",
  running: "Analysing your CV against the job description…",
};

export function AnalysisPanel({ application }: { application: Application }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  // The analysis currently being polled; the effect below owns the polling loop.
  const [pollingId, setPollingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.applications
      .analyses(application.id)
      .then((list) => {
        if (cancelled) return;
        const latest = list[0] ?? null;
        setAnalysis(latest);
        if (latest && (latest.status === "queued" || latest.status === "running")) setPollingId(latest.id);
      })
      .catch(() => !cancelled && setError("Could not load previous analyses"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [application.id]);

  useEffect(() => {
    if (!pollingId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const a = await api.analyses.get(pollingId);
        if (cancelled) return;
        setAnalysis(a);
        if (a.status === "queued" || a.status === "running") timer = setTimeout(tick, POLL_MS);
        else setPollingId(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Lost contact with the server");
        setPollingId(null);
      }
    };
    timer = setTimeout(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pollingId]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const accepted = await api.applications.analyze(application.id);
      setAnalysis((prev) => ({
        ...(prev as Analysis),
        id: accepted.analysis_id,
        status: accepted.status,
        result: null,
        error: null,
      }));
      setPollingId(accepted.analysis_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the analysis");
    } finally {
      setStarting(false);
    }
  }

  const inProgress = analysis?.status === "queued" || analysis?.status === "running";
  const hasJd = Boolean(application.job_description?.trim());

  return (
    <Card className="p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Sparkles className="size-5 text-accent" aria-hidden /> AI match analysis
          </h2>
          <p className="text-sm text-fg-muted">How well does your active CV fit this job?</p>
        </div>
        <Button onClick={start} loading={starting} disabled={inProgress || !hasJd}>
          {analysis?.status === "succeeded" ? "Re-analyze" : "Analyze match"}
        </Button>
      </div>

      {!hasJd && (
        <p className="rounded-lg bg-surface-2 px-3 py-2 text-sm text-fg-muted">
          Add a job description to this application to enable the analysis.
        </p>
      )}
      {error && (
        <p role="alert" className="mb-3 flex items-start gap-2 text-sm text-danger">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {error}
            {error.includes("CV") && (
              <>
                {" "}
                <Link href="/cv" className="font-medium underline">
                  Upload your CV
                </Link>
              </>
            )}
          </span>
        </p>
      )}

      <div aria-live="polite" aria-busy={inProgress}>
        {loading ? (
          <p className="text-sm text-fg-subtle">Loading…</p>
        ) : inProgress ? (
          <div className="flex flex-col gap-3 py-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Loader2 className="size-4 animate-spin text-accent" aria-hidden />
              {STEP_LABEL[analysis!.status]}
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
              <div
                className={clsx(
                  "h-full rounded-full bg-accent transition-all duration-1000",
                  analysis!.status === "queued" ? "w-1/4" : "w-3/4 animate-pulse",
                )}
              />
            </div>
            {analysis?.error && <p className="text-xs text-fg-subtle">{analysis.error}</p>}
          </div>
        ) : analysis?.status === "failed" ? (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/50 dark:text-red-200">
            The analysis failed after several attempts: {analysis.error}
          </p>
        ) : analysis?.status === "succeeded" && analysis.result ? (
          <Result analysis={analysis} />
        ) : (
          hasJd && <p className="text-sm text-fg-subtle">No analysis yet. Click “Analyze match” to run one.</p>
        )}
      </div>
    </Card>
  );
}

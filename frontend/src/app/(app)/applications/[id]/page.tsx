"use client";

import clsx from "clsx";
import { ArrowLeft, BellRing, CircleDot, ExternalLink, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { ApplicationForm } from "@/components/application-form";
import { useToast } from "@/components/toast";
import { Button, Card, ErrorBanner, Select, Spinner, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatDate, formatDateTime, formatSalary, STATUS_META } from "@/lib/format";
import { type Application, type ApplicationEvent, type ApplicationStatus, STATUSES } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

import { AnalysisPanel } from "./analysis-panel";

function Timeline({ events }: { events: ApplicationEvent[] }) {
  return (
    <ol className="relative ml-2 border-l border-border">
      {[...events].reverse().map((e) => {
        const Icon = e.event_type === "created" ? Plus : e.event_type === "follow_up_overdue" ? BellRing : CircleDot;
        return (
          <li key={e.id} className="mb-5 ml-5 last:mb-0">
            <span
              className={clsx(
                "absolute -left-3 flex size-6 items-center justify-center rounded-full border border-border bg-surface",
                e.event_type === "follow_up_overdue" && "text-danger",
              )}
            >
              <Icon className="size-3.5" aria-hidden />
            </span>
            <p className="text-sm">
              {e.event_type === "created" && (
                <>Created as <strong>{STATUS_META[e.to_status!].label}</strong></>
              )}
              {e.event_type === "status_changed" && (
                <>
                  {STATUS_META[e.from_status!].label} → <strong>{STATUS_META[e.to_status!].label}</strong>
                </>
              )}
              {e.event_type === "follow_up_overdue" && <strong>Follow-up overdue</strong>}
            </p>
            {e.note && <p className="text-sm text-fg-muted">{e.note}</p>}
            <time className="text-xs text-fg-subtle" dateTime={e.occurred_at}>
              {formatDateTime(e.occurred_at)}
            </time>
          </li>
        );
      })}
    </ol>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

export default function ApplicationPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const fetchApp = useCallback(async () => {
    const [app, events] = await Promise.all([api.applications.get(id), api.applications.events(id)]);
    return { app, events };
  }, [id]);
  const { data, error, reload, mutate } = useResource(fetchApp, "Failed to load the application.");
  const app = data?.app ?? null;
  const events = data?.events ?? [];
  const setApp = (a: Application) => mutate((d) => ({ app: a, events: d?.events ?? [] }));
  const setEvents = (ev: ApplicationEvent[]) => mutate((d) => (d ? { ...d, events: ev } : d));

  async function changeStatus(status: ApplicationStatus) {
    if (!app) return;
    const previous = app;
    setApp({ ...app, status });
    try {
      setApp(await api.applications.setStatus(app.id, status));
      setEvents(await api.applications.events(app.id));
      toast("success", `Moved to ${STATUS_META[status].label}`);
    } catch (e) {
      setApp(previous);
      toast("error", e instanceof ApiError ? e.message : "Could not update status");
    }
  }

  async function remove() {
    if (!app || !confirm(`Delete ${app.company} – ${app.role_title}? This cannot be undone.`)) return;
    try {
      await api.applications.remove(app.id);
      toast("success", "Application deleted");
      router.push("/board");
    } catch (e) {
      toast("error", e instanceof ApiError ? e.message : "Could not delete");
    }
  }

  if (error && !app) return <ErrorBanner message={error} onRetry={reload} />;
  if (!app) return <Spinner label="Loading application" />;

  const salary = formatSalary(app.salary_min, app.salary_max, app.currency);

  return (
    <div className="flex flex-col gap-6">
      <Link href="/board" className="inline-flex w-fit items-center gap-1 text-sm text-fg-muted hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden /> Back to board
      </Link>

      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{app.company}</h1>
            <StatusBadge status={app.status} />
          </div>
          <p className="mt-1 text-fg-muted">{app.role_title}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="status-select" className="sr-only">
            Status
          </label>
          <Select
            id="status-select"
            value={app.status}
            onChange={(e) => void changeStatus(e.target.value as ApplicationStatus)}
            className="w-40"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_META[s].label}
              </option>
            ))}
          </Select>
          <Button variant="secondary" onClick={() => setEditing((v) => !v)} aria-expanded={editing}>
            <Pencil className="size-4" aria-hidden /> {editing ? "Close editor" : "Edit"}
          </Button>
          <Button variant="danger" onClick={remove} aria-label="Delete application">
            <Trash2 className="size-4" aria-hidden />
          </Button>
        </div>
      </div>

      {editing && (
        <Card className="p-5">
          <ApplicationForm
            initial={app}
            showStatus={false}
            submitLabel="Save changes"
            onCancel={() => setEditing(false)}
            onSubmit={async (data) => {
              setApp(await api.applications.update(app.id, data));
              setEditing(false);
              toast("success", "Saved");
            }}
          />
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <AnalysisPanel application={app} />
          {app.job_description && (
            <Card className="p-5">
              <h2 className="mb-3 text-lg font-semibold">Job description</h2>
              <div className="max-h-96 overflow-y-auto whitespace-pre-line text-sm leading-relaxed text-fg-muted">
                {app.job_description}
              </div>
            </Card>
          )}
        </div>
        <div className="flex flex-col gap-6">
          <Card className="p-5">
            <h2 className="mb-4 text-lg font-semibold">Details</h2>
            <dl className="grid grid-cols-2 gap-4">
              <Detail label="Location">{app.location ?? "—"}</Detail>
              <Detail label="Salary">{salary ?? "—"}</Detail>
              <Detail label="Applied">{formatDate(app.applied_at)}</Detail>
              <Detail label="Follow up">
                <span className={clsx(app.follow_up_flagged_at && "font-medium text-danger")}>
                  {formatDate(app.follow_up_at)}
                </span>
              </Detail>
              {app.job_url && (
                <div className="col-span-2">
                  <a
                    href={app.job_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-sm text-accent hover:underline"
                  >
                    View job posting <ExternalLink className="size-3.5" aria-hidden />
                  </a>
                </div>
              )}
            </dl>
            {app.notes && (
              <div className="mt-4 border-t border-border pt-4">
                <h3 className="text-xs uppercase tracking-wide text-fg-subtle">Notes</h3>
                <p className="mt-1 whitespace-pre-line text-sm">{app.notes}</p>
              </div>
            )}
          </Card>
          <Card className="p-5">
            <h2 className="mb-4 text-lg font-semibold">Timeline</h2>
            <Timeline events={events} />
          </Card>
        </div>
      </div>
    </div>
  );
}

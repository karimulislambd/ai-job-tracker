"use client";

import clsx from "clsx";
import { BellRing } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";

import { Card, ErrorBanner, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, percent, relativeDays } from "@/lib/format";
import { useResource } from "@/lib/use-resource";

import { StatusChart, WeeklyChart } from "./charts";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-5">
      <p className="text-sm text-fg-muted">{label}</p>
      <p className="mt-1 text-3xl font-semibold tracking-tight">{value}</p>
      {hint && <p className="mt-1 text-xs text-fg-subtle">{hint}</p>}
    </Card>
  );
}

export default function DashboardPage() {
  const fetchStats = useCallback(() => api.stats.dashboard(), []);
  const { data: stats, error, reload } = useResource(fetchStats, "Failed to load stats.");

  if (error && !stats) return <ErrorBanner message={error} onRetry={reload} />;
  if (!stats) return <Spinner label="Crunching numbers" />;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-fg-muted">How your search is going, computed live from your data.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Applications" value={String(stats.total)} hint={`${stats.applied_count} sent`} />
        <Stat label="Response rate" value={percent(stats.response_rate)} hint="of sent applications got a reply" />
        <Stat label="Interview rate" value={percent(stats.interview_rate)} hint={`${percent(stats.offer_rate)} reached an offer`} />
        <Stat
          label="Avg. time to response"
          value={stats.avg_days_to_first_response != null ? `${stats.avg_days_to_first_response}d` : "—"}
          hint="from applying to first reply"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <WeeklyChart data={stats.applications_per_week} />
        <StatusChart byStatus={stats.by_status} />
      </div>

      <Card className="p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold">Upcoming follow-ups</h2>
          {stats.overdue_follow_ups > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-800 dark:bg-red-950 dark:text-red-200">
              <BellRing className="size-3" aria-hidden /> {stats.overdue_follow_ups} overdue
            </span>
          )}
        </div>
        {stats.upcoming_follow_ups.length === 0 ? (
          <p className="text-sm text-fg-subtle">Nothing due in the next two weeks.</p>
        ) : (
          <ul className="divide-y divide-border">
            {stats.upcoming_follow_ups.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <Link href={`/applications/${f.id}`} className="font-medium hover:text-accent hover:underline">
                    {f.company}
                  </Link>
                  <p className="truncate text-sm text-fg-muted">{f.role_title}</p>
                </div>
                <StatusBadge status={f.status} />
                <span className={clsx("w-32 text-right text-sm", f.overdue ? "font-medium text-danger" : "text-fg-muted")}>
                  <span className="sr-only">{f.overdue ? "Overdue: " : "Due "}</span>
                  {relativeDays(f.follow_up_at)}
                  <span className="block text-xs font-normal text-fg-subtle">{formatDate(f.follow_up_at)}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

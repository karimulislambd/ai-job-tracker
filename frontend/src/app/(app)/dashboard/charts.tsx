"use client";

import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  type TooltipContentProps,
  XAxis,
  YAxis,
} from "recharts";

import { formatShortDate, STATUS_META } from "@/lib/format";
import { type DashboardStats, STATUSES } from "@/lib/types";

const AXIS_TICK = { fill: "var(--chart-axis)", fontSize: 12 };

function ChartTooltip({ active, payload, label }: Partial<TooltipContentProps<number, string>>) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-lg">
      <p className="text-fg-muted">{String(p.payload?.label ?? label)}</p>
      <p className="mt-0.5 font-semibold text-fg tabular-nums">
        {p.value} application{p.value === 1 ? "" : "s"}
      </p>
    </div>
  );
}

/** Chart + accessible table toggle: the data is always available without the visual. */
function ChartCard({
  title,
  description,
  table,
  children,
}: {
  title: string;
  description: string;
  table: { label: string; value: number }[];
  children: React.ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <figure className="rounded-xl border border-border bg-surface p-5 shadow-xs">
      <div className="mb-4 flex items-start justify-between gap-3">
        <figcaption>
          <h2 className="font-semibold">{title}</h2>
          <p className="text-sm text-fg-muted">{description}</p>
        </figcaption>
        <button
          type="button"
          onClick={() => setShowTable((v) => !v)}
          className="shrink-0 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-surface-2 hover:text-fg"
          aria-pressed={showTable}
        >
          {showTable ? "Show chart" : "View as table"}
        </button>
      </div>
      {showTable ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-fg-subtle">
              <th className="py-1.5 font-medium">Label</th>
              <th className="py-1.5 text-right font-medium">Applications</th>
            </tr>
          </thead>
          <tbody>
            {table.map((row) => (
              <tr key={row.label} className="border-b border-border/60 last:border-0">
                <td className="py-1.5">{row.label}</td>
                <td className="py-1.5 text-right tabular-nums">{row.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="h-64" aria-hidden>
          {children}
        </div>
      )}
    </figure>
  );
}

export function WeeklyChart({ data }: { data: DashboardStats["applications_per_week"] }) {
  const rows = data.map((w) => ({ label: `Week of ${formatShortDate(w.week_start)}`, tick: formatShortDate(w.week_start), value: w.count }));
  return (
    <ChartCard title="Applications per week" description="Last 12 weeks, by date applied" table={rows}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 4, left: -24, bottom: 0 }} barCategoryGap={6}>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis dataKey="tick" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }} interval="preserveStartEnd" minTickGap={16} />
          <YAxis allowDecimals={false} tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--surface-2)" }} />
          <Bar dataKey="value" fill="var(--chart-series-1)" radius={[4, 4, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function StatusChart({ byStatus }: { byStatus: DashboardStats["by_status"] }) {
  const rows = STATUSES.map((s) => ({ label: STATUS_META[s].label, value: byStatus[s] ?? 0 }));
  return (
    <ChartCard title="Pipeline by status" description="Where every application currently sits" table={rows}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }} barCategoryGap={6}>
          <CartesianGrid horizontal={false} stroke="var(--chart-grid)" />
          <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} width={88} />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--surface-2)" }} />
          <Bar dataKey="value" fill="var(--chart-series-1)" radius={[0, 4, 4, 0]} maxBarSize={22} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

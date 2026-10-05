import type { ApplicationStatus } from "./types";

export const STATUS_META: Record<
  ApplicationStatus,
  { label: string; dot: string; badge: string }
> = {
  wishlist: {
    label: "Wishlist",
    dot: "bg-zinc-400",
    badge: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200",
  },
  applied: {
    label: "Applied",
    dot: "bg-blue-500",
    badge: "bg-blue-50 text-blue-800 dark:bg-blue-950 dark:text-blue-200",
  },
  interviewing: {
    label: "Interviewing",
    dot: "bg-violet-500",
    badge: "bg-violet-50 text-violet-800 dark:bg-violet-950 dark:text-violet-200",
  },
  offer: {
    label: "Offer",
    dot: "bg-emerald-500",
    badge: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  },
  rejected: {
    label: "Rejected",
    dot: "bg-rose-500",
    badge: "bg-rose-50 text-rose-800 dark:bg-rose-950 dark:text-rose-200",
  },
  withdrawn: {
    label: "Withdrawn",
    dot: "bg-amber-500",
    badge: "bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  },
};

const dateFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
const shortFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export const formatDate = (iso: string | null | undefined) => (iso ? dateFmt.format(new Date(iso)) : "—");
export const formatShortDate = (iso: string) => shortFmt.format(new Date(iso));
export const formatDateTime = (iso: string) => dateTimeFmt.format(new Date(iso));

export function relativeDays(iso: string, now = Date.now()): string {
  const days = Math.round((new Date(iso).getTime() - now) / 86_400_000);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  return rtf.format(days, "day");
}

export function formatSalary(min: number | null, max: number | null, currency: string | null): string | null {
  if (min === null && max === null) return null;
  const fmt = (n: number) =>
    new Intl.NumberFormat(undefined, {
      style: currency ? "currency" : "decimal",
      currency: currency ?? undefined,
      notation: n >= 100_000 ? "compact" : "standard",
      maximumFractionDigits: n >= 100_000 ? 1 : 0,
    }).format(n);
  if (min !== null && max !== null) return `${fmt(min)} – ${fmt(max)}`;
  return fmt((min ?? max) as number);
}

export const percent = (v: number) => `${Math.round(v * 100)}%`;

/** ISO string -> value for <input type="date"> (local date). */
export function toDateInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** <input type="date"> value -> ISO string at local noon (avoids off-by-one across TZs). */
export function fromDateInput(value: string): string | null {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d, 12).toISOString();
}

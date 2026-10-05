"use client";

import { Plus, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApplicationForm } from "@/components/application-form";
import { Dialog } from "@/components/dialog";
import { useToast } from "@/components/toast";
import { Button, EmptyState, ErrorBanner, Input, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { STATUS_META } from "@/lib/format";
import type { Application, ApplicationStatus } from "@/lib/types";

import { Kanban } from "./kanban";

export default function BoardPage() {
  const toast = useToast();
  const router = useRouter();
  const [items, setItems] = useState<Application[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const requestId = useRef(0);

  const load = useCallback(async (q: string) => {
    const id = ++requestId.current;
    try {
      setError(null);
      const page = await api.applications.list({ q: q || undefined, limit: 200, sort: "-updated_at" });
      if (id === requestId.current) setItems(page.items); // ignore out-of-order responses
    } catch (e) {
      if (id === requestId.current) setError(e instanceof ApiError ? e.message : "Failed to load applications");
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => void load(query), query ? 250 : 0); // debounce search
    return () => clearTimeout(t);
  }, [query, load]);

  // Optimistic status change: update the board immediately, roll back if the API fails.
  const move = useCallback(
    async (app: Application, to: ApplicationStatus) => {
      const previous = items;
      setItems((cur) =>
        cur?.map((a) => (a.id === app.id ? { ...a, status: to, updated_at: new Date().toISOString() } : a)) ?? cur,
      );
      try {
        const saved = await api.applications.setStatus(app.id, to);
        setItems((cur) => cur?.map((a) => (a.id === saved.id ? saved : a)) ?? cur);
        toast("success", `${app.company} → ${STATUS_META[to].label}`);
      } catch (e) {
        setItems(previous);
        toast("error", e instanceof ApiError ? e.message : "Could not move the application");
      }
    },
    [items, toast],
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Applications</h1>
          <p className="text-sm text-fg-muted">
            {items ? `${items.length} tracked` : " "} · drag cards between columns to update their status
          </p>
        </div>
        <div className="ml-auto flex w-full items-center gap-2 sm:w-auto">
          <div className="relative flex-1 sm:w-72">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
            <Input
              type="search"
              placeholder="Search company, role, notes…"
              aria-label="Search applications"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-9"
            />
          </div>
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" aria-hidden />
            <span className="hidden sm:inline">Add application</span>
            <span className="sm:hidden">Add</span>
          </Button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => void load(query)} />}
      {!items && !error && <Spinner label="Loading applications" />}
      {items && items.length === 0 && !query && (
        <EmptyState title="No applications yet">
          Add the first role you&apos;re interested in — paste the job description to unlock AI matching.
          <div className="mt-4">
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" aria-hidden /> Add application
            </Button>
          </div>
        </EmptyState>
      )}
      {items && (items.length > 0 || query) && <Kanban items={items} onMove={move} />}

      <Dialog open={creating} onClose={() => setCreating(false)} title="New application">
        <ApplicationForm
          submitLabel="Create"
          onCancel={() => setCreating(false)}
          onSubmit={async (data) => {
            const created = await api.applications.create(data);
            setItems((cur) => (cur ? [created, ...cur] : [created]));
            setCreating(false);
            toast("success", `Added ${created.company}`);
            router.prefetch(`/applications/${created.id}`);
          }}
        />
      </Dialog>
    </div>
  );
}

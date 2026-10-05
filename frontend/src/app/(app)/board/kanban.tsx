"use client";

import {
  type Announcements,
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import clsx from "clsx";
import { ArrowRightLeft, BellRing, GripVertical, MapPin } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { formatSalary, relativeDays, STATUS_META } from "@/lib/format";
import { type Application, type ApplicationStatus, STATUSES } from "@/lib/types";

function MoveSelect({
  app,
  onMove,
  compact = false,
  className,
}: {
  app: Application;
  onMove: KanbanProps["onMove"];
  compact?: boolean;
  className?: string;
}) {
  // Non-drag alternative for touch, keyboard and screen-reader users. In compact mode a
  // transparent native <select> sits on top of an icon, so it stays fully accessible.
  const options = (
    <>
      <option value="" disabled>
        Move to…
      </option>
      {STATUSES.filter((s) => s !== app.status).map((s) => (
        <option key={s} value={s}>
          {STATUS_META[s].label}
        </option>
      ))}
    </>
  );
  const change = (e: React.ChangeEvent<HTMLSelectElement>) =>
    e.target.value && onMove(app, e.target.value as ApplicationStatus);
  if (compact) {
    return (
      <label
        className={clsx(
          "relative flex size-6 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-surface-2 hover:text-fg focus-within:ring-2 focus-within:ring-accent",
          className,
        )}
        title="Move to another column"
      >
        <ArrowRightLeft className="size-3.5" aria-hidden />
        <span className="sr-only">Move {app.company} to another column</span>
        <select value="" onChange={change} className="absolute inset-0 cursor-pointer opacity-0">
          {options}
        </select>
      </label>
    );
  }
  return (
    <label className={className}>
      <span className="sr-only">Move {app.company} to another column</span>
      <select
        value=""
        onChange={change}
        className="h-7 w-full rounded-md border border-border bg-surface px-1.5 text-xs text-fg-muted"
      >
        {options}
      </select>
    </label>
  );
}

interface KanbanProps {
  items: Application[];
  onMove: (app: Application, to: ApplicationStatus) => void;
}

function Card({
  app,
  now,
  overlay = false,
  onMove,
}: {
  app: Application;
  now: number;
  overlay?: boolean;
  onMove?: KanbanProps["onMove"];
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: app.id, data: app });
  const salary = formatSalary(app.salary_min, app.salary_max, app.currency);
  const overdue = app.follow_up_at && new Date(app.follow_up_at).getTime() < now;
  const active = !["rejected", "withdrawn"].includes(app.status);

  return (
    <article
      ref={overlay ? undefined : setNodeRef}
      className={clsx(
        "group rounded-lg border border-border bg-surface p-3 shadow-xs transition",
        isDragging && !overlay && "opacity-40",
        overlay && "rotate-2 shadow-xl ring-2 ring-accent/40",
      )}
    >
      <div className="flex items-start gap-2">
        <div className="-ml-1 mt-0.5 flex w-6 shrink-0 flex-col items-center gap-0.5">
          <button
            type="button"
            className="cursor-grab touch-none rounded p-0.5 text-fg-subtle hover:bg-surface-2 hover:text-fg active:cursor-grabbing"
            aria-label={`Drag ${app.company} – ${app.role_title}`}
            {...(overlay ? {} : listeners)}
            {...(overlay ? {} : attributes)}
          >
            <GripVertical className="size-4" aria-hidden />
          </button>
          {onMove && !overlay && <MoveSelect app={app} onMove={onMove} compact className="hidden sm:flex" />}
        </div>
        <div className="min-w-0 flex-1">
          <Link
            href={`/applications/${app.id}`}
            className="block truncate font-medium text-fg hover:text-accent hover:underline"
          >
            {app.company}
          </Link>
          <p className="truncate text-sm text-fg-muted">{app.role_title}</p>
        </div>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 pl-7 text-xs text-fg-subtle">
        {app.location && (
          <span className="flex min-w-0 max-w-full items-center gap-1">
            <MapPin className="size-3 shrink-0" aria-hidden />
            <span className="truncate">{app.location}</span>
          </span>
        )}
        {salary && <span>{salary}</span>}
        {app.follow_up_at && active && (
          <span className={clsx("flex items-center gap-1", overdue && "font-medium text-danger")}>
            <BellRing className="size-3 shrink-0" aria-hidden />
            {overdue ? "Follow-up overdue" : `Follow up ${relativeDays(app.follow_up_at)}`}
          </span>
        )}
      </div>
      {onMove && !overlay && <MoveSelect app={app} onMove={onMove} className="mt-2 block pl-7 sm:hidden" />}
    </article>
  );
}

function Column({
  status,
  items,
  now,
  onMove,
}: {
  status: ApplicationStatus;
  items: Application[];
  now: number;
  onMove: KanbanProps["onMove"];
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  const meta = STATUS_META[status];
  return (
    <section
      ref={setNodeRef}
      aria-label={`${meta.label} column, ${items.length} applications`}
      className={clsx(
        "flex w-72 shrink-0 snap-start flex-col rounded-xl border bg-surface-2/60 transition-colors lg:w-auto lg:min-w-0",
        isOver ? "border-accent bg-accent-soft/60" : "border-transparent",
      )}
    >
      <header className="flex items-center gap-2 px-3 pb-2 pt-3">
        <span className={clsx("size-2 rounded-full", meta.dot)} aria-hidden />
        <h2 className="text-sm font-semibold">{meta.label}</h2>
        <span className="ml-auto rounded-full bg-surface px-2 text-xs tabular-nums text-fg-muted">
          {items.length}
        </span>
      </header>
      <div className="flex min-h-32 flex-1 flex-col gap-2 p-2 pt-0">
        {items.map((app) => (
          <Card key={app.id} app={app} now={now} onMove={onMove} />
        ))}
        {items.length === 0 && (
          <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-fg-subtle">
            Drop here
          </p>
        )}
      </div>
    </section>
  );
}

export function Kanban({ items, onMove }: KanbanProps) {
  const [dragging, setDragging] = useState<Application | null>(null);
  const [now] = useState(() => Date.now());
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 6 } }),
    useSensor(KeyboardSensor),
  );

  const label = (id: string | number | undefined) =>
    id && STATUSES.includes(id as ApplicationStatus) ? STATUS_META[id as ApplicationStatus].label : "no column";
  const announcements: Announcements = {
    onDragStart: ({ active }) => `Picked up ${(active.data.current as Application).company}.`,
    onDragOver: ({ active, over }) =>
      `${(active.data.current as Application).company} is over ${label(over?.id)}.`,
    onDragEnd: ({ active, over }) =>
      `${(active.data.current as Application).company} moved to ${label(over?.id)}.`,
    onDragCancel: ({ active }) => `Cancelled moving ${(active.data.current as Application).company}.`,
  };

  function handleStart(e: DragStartEvent) {
    setDragging(e.active.data.current as Application);
  }
  function handleEnd(e: DragEndEvent) {
    setDragging(null);
    const app = e.active.data.current as Application;
    const to = e.over?.id as ApplicationStatus | undefined;
    if (to && to !== app.status) onMove(app, to);
  }

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleStart}
      onDragEnd={handleEnd}
      onDragCancel={() => setDragging(null)}
      accessibility={{
        announcements,
        screenReaderInstructions: {
          draggable:
            "To move an application, press space or enter, use the arrow keys to choose a column, then press space or enter again. Press escape to cancel.",
        },
      }}
    >
      <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-4 lg:mx-0 lg:grid lg:grid-cols-6 lg:overflow-visible lg:px-0">
        {STATUSES.map((status) => (
          <Column
            key={status}
            status={status}
            items={items.filter((a) => a.status === status)}
            now={now}
            onMove={onMove}
          />
        ))}
      </div>
      <DragOverlay dropAnimation={null}>{dragging ? <Card app={dragging} now={now} overlay /> : null}</DragOverlay>
    </DndContext>
  );
}

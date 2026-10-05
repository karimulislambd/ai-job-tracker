"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";
import { fromDateInput, STATUS_META, toDateInput } from "@/lib/format";
import { type Application, type ApplicationInput, STATUSES } from "@/lib/types";

import { Button, Field, Input, Select, Textarea } from "./ui";

interface Props {
  initial?: Partial<Application>;
  submitLabel: string;
  onSubmit: (data: ApplicationInput) => Promise<void>;
  onCancel?: () => void;
  showStatus?: boolean;
}

const str = (v: FormDataEntryValue | null) => {
  const s = String(v ?? "").trim();
  return s === "" ? null : s;
};
const num = (v: FormDataEntryValue | null) => {
  const s = str(v);
  return s === null ? null : Number(s);
};

export function ApplicationForm({ initial = {}, submitLabel, onSubmit, onCancel, showStatus = true }: Props) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handle(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const data: ApplicationInput = {
      company: str(f.get("company")) ?? "",
      role_title: str(f.get("role_title")) ?? "",
      job_url: str(f.get("job_url")),
      location: str(f.get("location")),
      salary_min: num(f.get("salary_min")),
      salary_max: num(f.get("salary_max")),
      currency: str(f.get("currency"))?.toUpperCase() ?? null,
      applied_at: fromDateInput(String(f.get("applied_at") ?? "")),
      follow_up_at: fromDateInput(String(f.get("follow_up_at") ?? "")),
      notes: str(f.get("notes")),
      job_description: str(f.get("job_description")),
    };
    if (showStatus) data.status = f.get("status") as Application["status"];
    const local: Record<string, string> = {};
    if (!data.company) local.company = "Company is required";
    if (!data.role_title) local.role_title = "Role is required";
    if (data.salary_min != null && data.salary_max != null && data.salary_min > data.salary_max)
      local.salary_max = "Max must be ≥ min";
    setErrors(local);
    if (Object.keys(local).length) return;

    setSaving(true);
    setFormError(null);
    try {
      await onSubmit(data);
    } catch (err) {
      if (err instanceof ApiError && Array.isArray(err.details)) {
        const map: Record<string, string> = {};
        for (const d of err.details as { loc: (string | number)[]; msg: string }[]) {
          map[String(d.loc.at(-1))] = d.msg.replace(/^Value error, /, "");
        }
        setErrors(map);
        if (!Object.keys(map).length) setFormError(err.message);
      } else {
        setFormError(err instanceof Error ? err.message : "Could not save");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handle} className="grid gap-4 sm:grid-cols-2" noValidate>
      <Field label="Company" htmlFor="company" error={errors.company}>
        <Input id="company" name="company" defaultValue={initial.company ?? ""} required maxLength={200} />
      </Field>
      <Field label="Role" htmlFor="role_title" error={errors.role_title}>
        <Input id="role_title" name="role_title" defaultValue={initial.role_title ?? ""} required maxLength={200} />
      </Field>
      {showStatus && (
        <Field label="Status" htmlFor="status">
          <Select id="status" name="status" defaultValue={initial.status ?? "wishlist"}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_META[s].label}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Field label="Location" htmlFor="location" error={errors.location}>
        <Input id="location" name="location" defaultValue={initial.location ?? ""} placeholder="Remote, Berlin…" />
      </Field>
      <Field label="Job posting URL" htmlFor="job_url" error={errors.job_url} className="sm:col-span-2">
        <Input id="job_url" name="job_url" type="url" defaultValue={initial.job_url ?? ""} placeholder="https://…" />
      </Field>
      <div className="grid grid-cols-3 gap-3 sm:col-span-2">
        <Field label="Salary min" htmlFor="salary_min" error={errors.salary_min}>
          <Input id="salary_min" name="salary_min" type="number" min={0} inputMode="numeric" defaultValue={initial.salary_min ?? ""} />
        </Field>
        <Field label="Salary max" htmlFor="salary_max" error={errors.salary_max}>
          <Input id="salary_max" name="salary_max" type="number" min={0} inputMode="numeric" defaultValue={initial.salary_max ?? ""} />
        </Field>
        <Field label="Currency" htmlFor="currency" error={errors.currency}>
          <Input id="currency" name="currency" maxLength={3} placeholder="EUR" defaultValue={initial.currency ?? ""} className="uppercase" />
        </Field>
      </div>
      <Field label="Applied on" htmlFor="applied_at" error={errors.applied_at}>
        <Input id="applied_at" name="applied_at" type="date" defaultValue={toDateInput(initial.applied_at ?? null)} />
      </Field>
      <Field label="Follow up on" htmlFor="follow_up_at" error={errors.follow_up_at}>
        <Input id="follow_up_at" name="follow_up_at" type="date" defaultValue={toDateInput(initial.follow_up_at ?? null)} />
      </Field>
      <Field label="Notes" htmlFor="notes" error={errors.notes} className="sm:col-span-2">
        <Textarea id="notes" name="notes" rows={3} defaultValue={initial.notes ?? ""} />
      </Field>
      <Field
        label="Job description"
        htmlFor="job_description"
        error={errors.job_description}
        hint="Paste the posting to enable AI match analysis."
        className="sm:col-span-2"
      >
        <Textarea id="job_description" name="job_description" rows={6} defaultValue={initial.job_description ?? ""} />
      </Field>
      {formError && (
        <p role="alert" className="text-sm text-danger sm:col-span-2">
          {formError}
        </p>
      )}
      <div className="flex justify-end gap-2 sm:col-span-2">
        {onCancel && (
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" loading={saving}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

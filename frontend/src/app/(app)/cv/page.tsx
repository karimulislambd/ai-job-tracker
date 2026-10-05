"use client";

import clsx from "clsx";
import { CheckCircle2, FileText, UploadCloud } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { useToast } from "@/components/toast";
import { Button, Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { Resume, ResumeSummary } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const MAX_BYTES = 5 * 1024 * 1024;

export default function CvPage() {
  const toast = useToast();
  const fetchCvs = useCallback(async () => {
    const list = await api.resumes.list();
    const active = list.some((r) => r.is_active) ? await api.resumes.active() : null;
    return { list, active };
  }, []);
  const { data, error, reload, mutate } = useResource(fetchCvs, "Failed to load your CVs.");
  const versions = data?.list ?? null;
  const active = data?.active ?? null;
  const setActive = (r: Resume) => mutate((d) => ({ list: d?.list ?? [], active: r }));
  const setVersions = (list: ResumeSummary[]) => mutate((d) => ({ list, active: d?.active ?? null }));
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setUploadError(null);
    // Client-side checks for fast feedback; the server re-validates everything.
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setUploadError("Please choose a PDF file.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setUploadError("The file is larger than 5 MB.");
      return;
    }
    setUploading(true);
    try {
      const resume = await api.resumes.upload(file);
      setActive(resume);
      toast("success", `Uploaded version ${resume.version}`);
      setVersions(await api.resumes.list());
    } catch (e) {
      setUploadError(e instanceof ApiError ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function activate(id: string) {
    try {
      const r = await api.resumes.activate(id);
      setActive(r);
      setVersions(await api.resumes.list());
      toast("success", `Version ${r.version} is now active`);
    } catch (e) {
      toast("error", e instanceof ApiError ? e.message : "Could not activate");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">My CV</h1>
        <p className="text-sm text-fg-muted">
          The active version is what the AI compares against job descriptions.
        </p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const file = e.dataTransfer.files[0];
          if (file) void upload(file);
        }}
        className={clsx(
          "flex flex-col items-center gap-3 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragOver ? "border-accent bg-accent-soft" : "border-border bg-surface",
        )}
      >
        <UploadCloud className="size-8 text-fg-subtle" aria-hidden />
        <div>
          <p className="font-medium">Drop your CV here, or choose a file</p>
          <p className="text-sm text-fg-muted">PDF with selectable text · up to 5 MB</p>
        </div>
        <input
          ref={inputRef}
          id="cv-file"
          type="file"
          accept="application/pdf,.pdf"
          className="sr-only"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
          }}
        />
        <Button loading={uploading} onClick={() => inputRef.current?.click()}>
          {uploading ? "Extracting text…" : "Choose PDF"}
        </Button>
        {uploadError && (
          <p role="alert" className="text-sm text-danger">
            {uploadError}
          </p>
        )}
      </div>

      {error && <ErrorBanner message={error} onRetry={reload} />}
      {!versions && !error && <Spinner label="Loading CVs" />}
      {versions && versions.length === 0 && (
        <EmptyState icon={<FileText className="size-8" />} title="No CV uploaded yet">
          Upload your CV to unlock AI match analysis on every application.
        </EmptyState>
      )}

      {versions && versions.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="p-5 lg:col-span-1">
            <h2 className="mb-3 text-lg font-semibold">Versions</h2>
            <ul className="flex flex-col gap-2">
              {versions.map((v) => (
                <li
                  key={v.id}
                  className={clsx(
                    "flex items-center gap-3 rounded-lg border px-3 py-2",
                    v.is_active ? "border-accent/50 bg-accent-soft/50" : "border-border",
                  )}
                >
                  <FileText className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      v{v.version} · {v.filename}
                    </p>
                    <p className="text-xs text-fg-subtle">
                      {formatDateTime(v.created_at)} · {v.page_count} page{v.page_count === 1 ? "" : "s"} ·{" "}
                      {Math.round(v.size_bytes / 1024)} KB
                    </p>
                  </div>
                  {v.is_active ? (
                    <span className="flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400">
                      <CheckCircle2 className="size-3.5" aria-hidden /> Active
                    </span>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => void activate(v.id)}>
                      Use
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
          <Card className="p-5 lg:col-span-2">
            <h2 className="mb-1 text-lg font-semibold">Extracted text</h2>
            <p className="mb-3 text-xs text-fg-subtle">
              {active ? `${active.content_text.length.toLocaleString()} characters from v${active.version}` : ""}
            </p>
            <pre className="max-h-[32rem] overflow-y-auto whitespace-pre-wrap rounded-lg bg-surface-2/60 p-4 font-sans text-sm leading-relaxed">
              {active?.content_text}
            </pre>
          </Card>
        </div>
      )}
    </div>
  );
}

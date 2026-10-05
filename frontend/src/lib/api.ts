/**
 * Typed API client.
 *
 * - The access token lives in memory only (never localStorage) to limit XSS exposure.
 * - The refresh token is an httpOnly cookie the browser sends to /api/v1/auth/*.
 * - On a 401 the client transparently refreshes once (single-flight) and retries.
 *
 * NEXT_PUBLIC_API_URL: the API origin (e.g. http://localhost:8000). Leave it empty to
 * call the same origin; next.config.ts then proxies /api/* to API_PROXY_TARGET, which
 * keeps the refresh cookie first-party in production.
 */
import type {
  Analysis,
  AnalysisAccepted,
  ApiErrorBody,
  Application,
  ApplicationEvent,
  ApplicationInput,
  ApplicationStatus,
  DashboardStats,
  Page,
  Resume,
  ResumeSummary,
  TokenResponse,
  User,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
const PREFIX = `${API_URL}/api/v1`;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: unknown = null,
    public requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let accessToken: string | null = null;
let onSessionExpired: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | null = null;
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    /* non-JSON error (e.g. a proxy timeout page) */
  }
  const err = body?.error;
  return new ApiError(
    res.status,
    err?.code ?? "http_error",
    err?.message ?? (res.status >= 500 ? "The server is unavailable. Please try again." : res.statusText),
    err?.details ?? null,
    err?.request_id ?? res.headers.get("x-request-id"),
  );
}

let refreshInFlight: Promise<TokenResponse | null> | null = null;

/** Rotate the refresh cookie and get a new access token. Single-flight across callers. */
export function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${PREFIX}/auth/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (!res.ok) {
          setAccessToken(null);
          return null;
        }
        const data = (await res.json()) as TokenResponse;
        setAccessToken(data.access_token);
        return data;
      } catch {
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  form?: FormData;
  query?: Record<string, string | number | undefined | null | string[]>;
  auth?: boolean;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${PREFIX}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.append(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function request<T>(path: string, opts: RequestOptions = {}, retried = false): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.auth !== false && accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const res = await fetch(buildUrl(path, opts.query), {
    method: opts.method ?? "GET",
    headers,
    body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
    credentials: "include",
    signal: opts.signal,
  });

  if (res.status === 401 && opts.auth !== false && !retried) {
    const refreshed = await refreshSession();
    if (refreshed) return request<T>(path, opts, true);
    onSessionExpired?.();
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface ApplicationQuery {
  status?: ApplicationStatus[];
  company?: string;
  q?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  auth: {
    login: (email: string, password: string) =>
      request<TokenResponse>("/auth/login", { method: "POST", body: { email, password }, auth: false }),
    register: (email: string, password: string, full_name?: string) =>
      request<TokenResponse>("/auth/register", {
        method: "POST",
        body: { email, password, full_name: full_name || null },
        auth: false,
      }),
    demo: () => request<TokenResponse>("/auth/demo", { method: "POST", auth: false }),
    logout: () => request<void>("/auth/logout", { method: "POST", auth: false }),
    me: () => request<User>("/auth/me"),
  },
  applications: {
    list: (q: ApplicationQuery = {}) =>
      request<Page<Application>>("/applications", {
        query: { ...q, status: q.status },
      }),
    get: (id: string) => request<Application>(`/applications/${id}`),
    create: (data: ApplicationInput) =>
      request<Application>("/applications", { method: "POST", body: data }),
    update: (id: string, data: ApplicationInput) =>
      request<Application>(`/applications/${id}`, { method: "PATCH", body: data }),
    setStatus: (id: string, status: ApplicationStatus, note?: string) =>
      request<Application>(`/applications/${id}/status`, {
        method: "PATCH",
        body: { status, note: note || null },
      }),
    remove: (id: string) => request<void>(`/applications/${id}`, { method: "DELETE" }),
    events: (id: string) => request<ApplicationEvent[]>(`/applications/${id}/events`),
    analyze: (id: string) =>
      request<AnalysisAccepted>(`/applications/${id}/analyze`, { method: "POST" }),
    analyses: (id: string) => request<Analysis[]>(`/applications/${id}/analyses`),
  },
  analyses: {
    get: (id: string) => request<Analysis>(`/analyses/${id}`),
  },
  resumes: {
    list: () => request<ResumeSummary[]>("/resumes"),
    active: () => request<Resume>("/resumes/active"),
    get: (id: string) => request<Resume>(`/resumes/${id}`),
    upload: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return request<Resume>("/resumes", { method: "POST", form });
    },
    activate: (id: string) => request<Resume>(`/resumes/${id}/activate`, { method: "POST" }),
  },
  stats: {
    dashboard: () => request<DashboardStats>("/stats/dashboard"),
  },
};

/** Ping /health (used to show a "waking up the server" hint on free-tier cold starts). */
export async function pingHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`, { signal, cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

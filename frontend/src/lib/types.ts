// Mirrors the backend's Pydantic schemas (see backend/app/schemas).

export const STATUSES = [
  "wishlist",
  "applied",
  "interviewing",
  "offer",
  "rejected",
  "withdrawn",
] as const;
export type ApplicationStatus = (typeof STATUSES)[number];

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_demo: boolean;
  demo_expires_at: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: User;
}

export interface Application {
  id: string;
  company: string;
  role_title: string;
  job_url: string | null;
  location: string | null;
  salary_min: number | null;
  salary_max: number | null;
  currency: string | null;
  status: ApplicationStatus;
  applied_at: string | null;
  follow_up_at: string | null;
  follow_up_flagged_at: string | null;
  notes: string | null;
  job_description: string | null;
  created_at: string;
  updated_at: string;
}

export type ApplicationInput = Partial<
  Omit<Application, "id" | "created_at" | "updated_at" | "follow_up_flagged_at">
>;

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApplicationEvent {
  id: number;
  event_type: "created" | "status_changed" | "follow_up_overdue";
  from_status: ApplicationStatus | null;
  to_status: ApplicationStatus | null;
  note: string | null;
  occurred_at: string;
}

export interface MatchResult {
  match_score: number;
  summary: string;
  matched_skills: string[];
  missing_skills: string[];
  strengths: string[];
  gaps: string[];
  cv_bullet_suggestions: string[];
  cover_letter: string;
}

export type AnalysisStatus = "queued" | "running" | "succeeded" | "failed";

export interface Analysis {
  id: string;
  application_id: string;
  resume_id: string | null;
  status: AnalysisStatus;
  result: MatchResult | null;
  error: string | null;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  duration_ms: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface AnalysisAccepted {
  analysis_id: string;
  status: AnalysisStatus;
  poll_url: string;
}

export interface ResumeSummary {
  id: string;
  version: number;
  filename: string;
  page_count: number;
  size_bytes: number;
  is_active: boolean;
  created_at: string;
}

export interface Resume extends ResumeSummary {
  content_text: string;
}

export interface DashboardStats {
  total: number;
  by_status: Record<ApplicationStatus, number>;
  applied_count: number;
  response_rate: number;
  interview_rate: number;
  offer_rate: number;
  avg_days_to_first_response: number | null;
  applications_per_week: { week_start: string; count: number }[];
  upcoming_follow_ups: {
    id: string;
    company: string;
    role_title: string;
    status: ApplicationStatus;
    follow_up_at: string;
    overdue: boolean;
  }[];
  overdue_follow_ups: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown;
    request_id: string | null;
  };
}

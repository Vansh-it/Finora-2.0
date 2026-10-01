import type { ResearchRegion } from "./researchStages";

const API_BASE = import.meta.env.VITE_API_URL || "";

const MAX_RETRIES = 2;
const INITIAL_RETRY_DELAY = 1000;

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  retries = MAX_RETRIES
): Promise<T> {
  const url = `${API_BASE}${path}`;
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const controller = new AbortController();
      // Set a generous timeout: 180s for chat, 120s for research endpoints, 30s default
      const isChat = path.includes("/chat");
      const isResearch = path.includes("/research/");
      const timeoutMs = isChat ? 45000 : isResearch ? 120000 : 30000;
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      const res = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...options.headers,
        },
      });

      clearTimeout(timeoutId);

      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        const text = await res.text();
        throw new Error(
          text.includes("<!doctype")
            ? `Server returned HTML instead of JSON. Make sure the backend is running on port 8000.`
            : `API error (${res.status}): ${text.slice(0, 200)}`
        );
      }

      const data = await res.json();

      if (!res.ok) {
        const errorMsg = data?.error || `Request failed (${res.status})`;
        throw new Error(errorMsg);
      }

      return data as T;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));

      // Don't retry on 4xx client errors (including 429 rate limit)
      if (lastError.message.includes("(4") || lastError.message.includes("company_limit_reached")) {
        throw lastError;
      }

      // Don't retry if this was the last attempt
      if (attempt >= retries) break;

      // Retry with exponential backoff
      const delay = INITIAL_RETRY_DELAY * Math.pow(2, attempt);
      await sleep(delay);
    }
  }

  // All retries failed — provide a clear, actionable error message
  const msg = lastError?.message || "Unknown error";
  if (msg.includes("Failed to fetch") || msg.includes("NetworkError")) {
    throw new Error(
      "Could not reach the Finora backend. Make sure the server is running (npm run dev:all) and try again."
    );
  }
  if (msg.includes("abort")) {
    throw new Error(
      "The request timed out. The AI is still thinking — please try again."
    );
  }
  throw lastError || new Error("Request failed after multiple attempts.");
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface AuthUser {
  user_id: string;
  email: string;
  name: string;
}

export async function signUp(
  email: string,
  password: string,
  name: string
): Promise<{ token: string; user: AuthUser }> {
  return apiFetch("/api/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export async function signIn(
  email: string,
  password: string
): Promise<{ token: string; user: AuthUser }> {
  return apiFetch("/api/auth/signin", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function getProfile(
  token: string
): Promise<{ user: AuthUser }> {
  return apiFetch("/api/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export interface ChatResponse {
  response: string;
  model_used: string;
  status: string;
  elapsed_ms: number;
}

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export async function sendChatMessage(
  message: string,
  history: ChatHistoryMessage[] = [],
  token?: string
): Promise<ChatResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, history }),
    headers,
  });
}

export async function sendDashboardChatMessage(
  message: string,
  sessionId: string,
  history: ChatHistoryMessage[] = [],
  token?: string
): Promise<ChatResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/chat/dashboard", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId, history }),
    headers,
  });
}

// ── Intent Classification ─────────────────────────────────────────────────────

export interface IntentResult {
  intent: "chat" | "research";
  confidence: number;
  reasoning?: string;
}

export async function classifyIntent(
  prompt: string
): Promise<IntentResult> {
  return apiFetch("/api/classify-intent", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

// ── Research Pipeline ─────────────────────────────────────────────────────────

export interface GrantPermissionResponse {
  session_id: string;
  company: string;
  status: string;
  period_mode: string;
}

export async function grantPermission(
  company: string,
  periodMode: string = "latest",
  startYear?: number,
  endYear?: number,
  token?: string
): Promise<GrantPermissionResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/grant-permission", {
    method: "POST",
    body: JSON.stringify({
      company,
      period_mode: periodMode,
      start_year: startYear,
      end_year: endYear,
    }),
    headers,
  });
}

export interface FetchFilingsResponse {
  status: string;
  company: { name: string; ticker: string; cik: string; exchange: string };
  period: { mode: string; start_year: number; end_year: number; label: string };
  documents: Array<{
    document_id: string;
    form: string;
    filing_date: string;
    period_of_report: string;
    source_url: string;
    primary_document: string;
  }>;
  document_count: number;
}

export async function fetchFilings(
  sessionId: string,
  token?: string
): Promise<FetchFilingsResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/research/fetch-filings", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
    headers,
  });
}

export interface ExtractFinancialsResponse {
  status: string;
  company: { name: string; ticker: string; cik: string };
  periods: string[];
  income_statement: Record<string, unknown>;
  balance_sheet: Record<string, unknown>;
  cash_flow: Record<string, unknown>;
  additional: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export async function extractFinancials(
  sessionId: string,
  token?: string
): Promise<ExtractFinancialsResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/research/extract-financials", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
    headers,
  });
}

export interface CalculateMetricsResponse {
  status: string;
  company: { name: string; ticker: string };
  periods: string[];
  annual_metrics: Record<string, unknown>;
  growth_metrics: Record<string, unknown>;
  cagr_metrics: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export async function calculateMetrics(
  sessionId: string,
  token?: string
): Promise<CalculateMetricsResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/research/calculate-metrics", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
    headers,
  });
}

export interface DiscoverSourcesResponse {
  status: string;
  sources: Array<{
    source_id: string;
    source_type: string;
    authority: string;
    provider: string;
    url: string;
    title: string;
    period: string;
    trust_tier: number;
    status: string;
  }>;
  metadata: Record<string, unknown>;
}

export async function discoverSources(
  sessionId: string,
  token?: string
): Promise<DiscoverSourcesResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/research/discover-sources", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
    headers,
  });
}

export interface ReadVerifySourcesResponse {
  status: string;
  sources_read: number;
  metrics_verified: number;
  mismatches: number;
  verifications: Array<Record<string, unknown>>;
  commentary: Array<Record<string, unknown>>;
  summary: {
    total_compared: number;
    exact_matches: number;
    within_tolerance: number;
    mismatches: number;
    not_comparable: number;
    missing_external: number;
    missing_sec: number;
  };
}

export async function readVerifySources(
  sessionId: string,
  token?: string
): Promise<ReadVerifySourcesResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/research/read-verify-sources", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
    headers,
  });
}

export interface GenerateSummaryResponse {
  status: string;
  executive_summary: {
    executive_overview: string;
    highlights: Array<{ title: string; text: string }>;
    growth_analysis: string;
    profitability_analysis: string;
    cash_flow_analysis: string;
    balance_sheet_analysis: string;
    watch_items: Array<{ tag: string; text: string }>;
    management_commentary_summary: string;
    data_quality_note: string;
  };
  warning?: string;
}

export async function generateSummary(
  sessionId: string,
  token?: string
): Promise<GenerateSummaryResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/research/generate-summary", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
    headers,
  });
}

export interface CalculateValuationResponse {
  status: string;
  market_data: {
    ticker: string;
    name: string;
    exchange: string;
    currency: string;
    price: number | null;
    price_date: string;
    previous_close: number | null;
    percent_change: number | null;
    shares_outstanding: number | null;
    market_cap: number | null;
    source: string;
    error?: string;
    fallback?: boolean;
    historical?: boolean;
  };
  valuation_metrics: Record<string, unknown>;
  period_alignment: Record<string, unknown>;
  is_financial_institution: boolean;
}

export async function calculateValuation(
  sessionId: string,
  token?: string
): Promise<CalculateValuationResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/research/calculate-valuation", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
    headers,
  });
}

// ── Dashboard Payload ─────────────────────────────────────────────────────────

export interface DashboardPayload {
  company: {
    ticker: string;
    name: string;
    exchange: string;
    sector: string;
  };
  periods: string[];
  income_statement: Record<string, unknown>;
  balance_sheet: Record<string, unknown>;
  cash_flow: Record<string, unknown>;
  annual_metrics: Record<string, unknown>;
  growth_metrics: Record<string, unknown>;
  cagr_metrics: Record<string, unknown>;
  market_data: Record<string, unknown>;
  valuation_metrics: Record<string, unknown>;
  executive_summary: Record<string, unknown>;
  verification_results: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export async function getResearchResult(
  sessionId: string,
  token?: string
): Promise<DashboardPayload> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch(`/api/research/result/${sessionId}`, {
    headers,
  });
}

// ── Session ───────────────────────────────────────────────────────────────────

export async function getSession(
  sessionId: string
): Promise<Record<string, unknown>> {
  return apiFetch(`/api/session/${sessionId}`);
}

export async function cancelSession(
  sessionId: string
): Promise<{ session_id: string; status: string }> {
  return apiFetch("/api/cancel-session", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  });
}

// ── Research Quota ────────────────────────────────────────────────────────────

export async function getResearchQuota(
  token: string
): Promise<{ allowed: boolean; used: number; limit: number; remaining: number }> {
  return apiFetch("/api/research/quota", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

// ── Single Pipeline Call ─────────────────────────────────────────────────────

export interface RunResearchResponse {
  status: string;
  session_id: string;
  dashboard?: DashboardPayload;
  error?: string;
}

/**
 * Run the US research pipeline.
 *
 * `region` is sent because the endpoint requires it: it starts the pipeline
 * without routing the user through /api/research/route first, so an unscoped call
 * is exactly the US-pipeline-by-default path that region selection exists to
 * close. `token` stays last so existing three-argument callers keep working.
 */
export async function runResearch(
  company: string,
  periodMode: string = "latest",
  region: ResearchRegion = "US",
  token?: string
): Promise<RunResearchResponse> {
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  return apiFetch("/api/research/run", {
    method: "POST",
    body: JSON.stringify({ company, period_mode: periodMode, region }),
    headers,
  });
}

// ── Research History ──────────────────────────────────────────────────────

export interface HistoryEntry {
  session_id: string;
  company: string;
  ticker: string;
  period: string;
  created_at: string;
  headline: string;
  metric_count: number;
  source_count: number;
  status: string;
}

export interface HistoryResponse {
  researches: HistoryEntry[];
  usage: {
    used: number;
    limit: number;
    remaining: number;
  };
}

export async function getResearchHistory(
  token: string
): Promise<HistoryResponse> {
  return apiFetch("/api/research/history", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

// ── Profile ────────────────────────────────────────────────────────────────

export interface ProfileData {
  user: {
    user_id: string;
    email: string;
    name: string;
    company?: string;
    research_runs_used: number;
    research_runs_limit: number;
  };
  completed_researches: number;
  usage: {
    used: number;
    limit: number;
    remaining: number;
  };
}

export async function getFullProfile(token: string): Promise<ProfileData> {
  return apiFetch("/api/auth/profile", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function updateProfile(
  token: string,
  data: { name?: string; company?: string }
): Promise<{ user: ProfileData["user"] }> {
  return apiFetch("/api/auth/update-profile", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(data),
  });
}

// ── Health Check ──────────────────────────────────────────────────────────────

export async function healthCheck(): Promise<{
  status: string;
  active_provider: string;
  providers_available: number;
}> {
  return apiFetch("/api/health");
}

// Real API layer. Talks to the deployed Finora Flask backend.
//
// The backend origin is configured with VITE_API_URL (see .env.example).
// In dev, API_BASE is empty so requests hit /api on the same origin and the
// Vite dev proxy forwards them to the deployed backend (no CORS needed).
// A production build with no VITE_API_URL targets the deployed backend.
import type { CompanySuggestion, DashboardSession, HistoryItem, Review } from './data';
import { getToken } from './auth';
import { adaptSession } from './adapter';

const RAW_BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? '').trim();
export const API_BASE = RAW_BASE.replace(/\/+$/, '') || (import.meta.env.DEV ? '' : 'https://finora-api-dio1.onrender.com');

const DEFAULT_TIMEOUT = 30_000;
const RESEARCH_TIMEOUT = 150_000;
const CHAT_TIMEOUT = 60_000;

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function toApiError(res: Response): Promise<ApiError> {
  let payload: Record<string, unknown> | null = null;
  try { payload = (await res.json()) as Record<string, unknown>; } catch { /* non-JSON */ }
  const message =
    (payload && (payload.error as string)) ||
    (payload && (payload.message as string)) ||
    `Request failed (${res.status})`;
  let code: string | undefined;
  if (res.status === 401) code = 'unauthorized';
  else if (res.status === 403) code = 'forbidden';
  else if (res.status === 404) code = 'not_found';
  else if (res.status === 429) code = payload?.quota_exhausted ? 'quota_exhausted' : 'rate_limited';
  else if (res.status === 409) code = payload?.research_in_progress ? 'research_in_progress' : 'conflict';
  else if (res.status === 202) code = 'pending';
  return new ApiError(res.status, message, code);
}

interface FetchOpts {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  retries?: number;
  auth?: boolean;
}

async function apiFetch<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const { method = 'GET', body, signal, timeoutMs = DEFAULT_TIMEOUT, retries = 2, auth = true } = opts;

  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) {
    const token = getToken();
    if (!token) throw new ApiError(401, 'Please sign in to continue.', 'unauthorized');
    headers['Authorization'] = `Bearer ${token}`;
  }

  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctrl = new AbortController();
    const onAbort = () => ctrl.abort();
    if (signal) {
      if (signal.aborted) ctrl.abort();
      else signal.addEventListener('abort', onAbort, { once: true });
    }
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
      });

      if (!res.ok || res.status === 202) {
        const err = await toApiError(res);
        if (res.status >= 500 && attempt < retries) {
          lastErr = err;
          await sleep(400 * (attempt + 1));
          continue;
        }
        throw err;
      }

      if (res.status === 204) return undefined as T;
      const ct = res.headers.get('content-type') ?? '';
      if (ct.includes('application/json')) return (await res.json()) as T;
      return (await res.text()) as unknown as T;
    } catch (e) {
      if ((e as Error).name === 'AbortError') {
        if (signal?.aborted) throw new DOMException('aborted', 'AbortError');
        lastErr = new ApiError(504, 'Finora took too long to respond. Please try again.', 'timeout');
        if (attempt < retries) { await sleep(400 * (attempt + 1)); continue; }
        throw lastErr;
      }
      if (e instanceof ApiError) throw e;
      lastErr = e;
      if (attempt < retries) { await sleep(400 * (attempt + 1)); continue; }
      throw new ApiError(0, 'Could not reach Finora. Check your connection and try again.', 'network');
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }
  }
  throw lastErr instanceof Error ? lastErr : new ApiError(0, 'Request failed.', 'network');
}

// ── Quota (server snapshot mirrored to localStorage for the /limit page) ──────
interface QuotaState { used: number; resetAt: number }
const QUOTA_KEY = 'finora_quota_v1';

export function getQuotaState(): QuotaState {
  try {
    const raw = localStorage.getItem(QUOTA_KEY);
    if (raw) {
      const q = JSON.parse(raw) as QuotaState;
      if (Date.now() < q.resetAt) return q;
    }
  } catch { /* fresh */ }
  const fresh = { used: 0, resetAt: Date.now() + 24 * 3600 * 1000 };
  try { localStorage.setItem(QUOTA_KEY, JSON.stringify(fresh)); } catch { /* ignore */ }
  return fresh;
}

function saveQuotaState(used: number, resetAt: number): void {
  try { localStorage.setItem(QUOTA_KEY, JSON.stringify({ used, resetAt })); } catch { /* ignore */ }
}

export async function getUsage(): Promise<{ used: number; limit: number; remaining: number; resetAt: number }> {
  const q = await apiFetch<{ used: number; limit: number; remaining: number; resets_at: number }>(
    '/api/research/quota',
  );
  const resetAt = q.resets_at ? q.resets_at * 1000 : Date.now() + 24 * 3600 * 1000;
  saveQuotaState(q.used, resetAt);
  return { used: q.used, limit: q.limit, remaining: Math.max(0, q.remaining), resetAt };
}

// ── Auth ──────────────────────────────────────────────────────────────────────
interface AuthResult { token: string; user: { name?: string; email: string } }

export async function signIn(email: string, password: string): Promise<{ token: string; user: { name: string; email: string } }> {
  const res = await apiFetch<AuthResult>('/api/auth/signin', {
    method: 'POST', body: { email, password }, auth: false, retries: 0,
  });
  return {
    token: res.token,
    user: { name: res.user?.name || (res.user?.email ?? email).split('@')[0], email: res.user?.email ?? email },
  };
}

export async function signUp(name: string, email: string, password: string): Promise<{ token: string; user: { name: string; email: string } }> {
  const res = await apiFetch<AuthResult>('/api/auth/signup', {
    method: 'POST', body: { name, email, password }, auth: false, retries: 0,
  });
  return {
    token: res.token,
    user: { name: res.user?.name || name, email: res.user?.email ?? email },
  };
}

export async function signOutUser(): Promise<void> {
  try { await apiFetch('/api/auth/signout', { method: 'POST', retries: 0 }); } catch { /* best effort */ }
}

// ── Company suggest ───────────────────────────────────────────────────────────
export async function suggestCompanies(q: string, signal?: AbortSignal): Promise<CompanySuggestion[]> {
  const needle = q.trim();
  if (!needle) return [];
  const res = await apiFetch<{ results?: Array<{ name?: string; ticker?: string; exchange?: string }> }>(
    `/api/company/suggest?q=${encodeURIComponent(needle)}`,
    { auth: false, signal, timeoutMs: 15_000, retries: 1 },
  );
  return (res.results ?? []).map((r) => ({
    ticker: (r.ticker ?? '').toUpperCase(),
    name: r.name ?? r.ticker ?? '',
    exchange: r.exchange ?? '',
  }));
}

// ── Research ──────────────────────────────────────────────────────────────────
export const RESEARCH_STAGES = [
  'Entity Identified', 'SEC Filings Located', 'Financial Statements',
  'Metrics Calculated', 'Sources Discovered', 'Source Verification',
  'Analysis Generated', 'Valuation Complete', 'Research File Complete',
] as const;

const SESSION_CACHE = new Map<string, DashboardSession>();

export async function runResearch(
  ticker: string,
  onStage: (idx: number) => void,
  signal?: AbortSignal,
): Promise<DashboardSession> {
  onStage(0);
  let idx = 0;
  const timer = window.setInterval(() => {
    if (idx < RESEARCH_STAGES.length - 1) {
      idx += 1;
      onStage(idx);
    }
  }, 1100);

  try {
    const res = await apiFetch<{ status?: string; session_id?: string; dashboard?: unknown; error?: string }>(
      '/api/research/run',
      {
        method: 'POST',
        body: { company: ticker.trim(), period_mode: 'latest' },
        signal,
        timeoutMs: RESEARCH_TIMEOUT,
        retries: 0,
      },
    );
    if (!res.dashboard || !res.session_id) {
      throw new ApiError(500, res.error || 'Research failed unexpectedly.', 'error');
    }
    const session = adaptSession(res.dashboard, res.session_id);
    SESSION_CACHE.set(session.sessionId, session);
    onStage(RESEARCH_STAGES.length);
    return session;
  } finally {
    window.clearInterval(timer);
  }
}

export async function getSession(sessionId: string): Promise<DashboardSession> {
  const cached = SESSION_CACHE.get(sessionId);
  if (cached) return cached;
  const payload = await apiFetch<unknown>(`/api/research/result/${encodeURIComponent(sessionId)}`, {
    timeoutMs: 60_000,
  });
  const session = adaptSession(payload, sessionId);
  SESSION_CACHE.set(sessionId, session);
  return session;
}

// ── History ───────────────────────────────────────────────────────────────────
export async function getHistory(): Promise<HistoryItem[]> {
  const res = await apiFetch<{ researches?: Array<Record<string, unknown>> }>('/api/research/history');
  return (res.researches ?? []).map((r) => ({
    sessionId: String(r.session_id ?? ''),
    ticker: String(r.ticker ?? ''),
    company: String(r.company ?? ''),
    period: String(r.period ?? ''),
    date: String(r.created_at ?? ''),
    headline: String(r.headline ?? ''),
    metrics: Number(r.metric_count ?? 0),
    sources: Number(r.source_count ?? 0),
  }));
}

export async function getRecentTickers(): Promise<string[]> {
  const hist = await getHistory();
  const seen = new Set<string>();
  const out: string[] = [];
  for (const h of hist) {
    if (h.ticker && !seen.has(h.ticker)) {
      seen.add(h.ticker);
      out.push(h.ticker);
    }
    if (out.length >= 3) break;
  }
  return out;
}

// ── Chat ──────────────────────────────────────────────────────────────────────
export interface ChatMsg { role: 'user' | 'assistant'; text: string; ms?: number }

const FOLLOW_UPS = ['Why did margins expand?', 'Is the dividend safe?', 'What could go wrong?', 'Explain ROIC simply'];

export function followUps(): string[] { return FOLLOW_UPS; }

function chatBody(messages: ChatMsg[], sessionId?: string): Record<string, unknown> {
  const lastUser = [...messages].reverse().find((m) => m.role === 'user');
  const history = messages
    .slice(0, Math.max(0, messages.length - 1))
    .map((m) => ({ role: m.role, content: m.text }));
  // Phone screen: keep replies short — only what was asked, no filler.
  const message = `${lastUser?.text ?? ''}\n\n(Reply for a phone: at most 4 short sentences, plain words, no headings, no tables, no preamble. Answer only the question.)`;
  const body: Record<string, unknown> = { message, history };
  if (sessionId) body.session_id = sessionId;
  return body;
}

export async function sendChat(
  messages: ChatMsg[],
  _sessionTicker?: string,
  sessionId?: string,
): Promise<{ text: string; ms: number }> {
  const t0 = performance.now();
  const path = sessionId ? '/api/chat/dashboard' : '/api/chat';
  const res = await apiFetch<{ response?: string; elapsed_ms?: number; error?: string }>(path, {
    method: 'POST',
    body: chatBody(messages, sessionId),
    timeoutMs: CHAT_TIMEOUT,
    retries: 1,
  });
  if (!res.response) throw new ApiError(502, res.error || 'Finora could not answer right now.', 'error');
  const ms = typeof res.elapsed_ms === 'number' ? res.elapsed_ms : Math.round(performance.now() - t0);
  return { text: res.response, ms };
}

export async function* streamChat(messages: ChatMsg[], sessionId?: string): AsyncGenerator<string, void, void> {
  const token = getToken();
  if (!token) throw new ApiError(401, 'Please sign in to continue.', 'unauthorized');

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), CHAT_TIMEOUT);
  try {
    const res = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(chatBody(messages, sessionId)),
      signal: ctrl.signal,
    });
    if (!res.ok) throw await toApiError(res);
    if (!res.body) throw new ApiError(502, 'Streaming is unavailable in this browser.', 'stream');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamError: string | null = null;
    let finished = false;

    while (!finished) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const dataLine = frame.split('\n').find((l) => l.startsWith('data:'));
        if (!dataLine) continue;
        let evt: { event?: string; response?: string; error?: string };
        try { evt = JSON.parse(dataLine.slice(5).trim()); } catch { continue; }
        if (evt.event === 'error') {
          streamError = evt.error || 'Finora is temporarily unable to respond.';
          finished = true;
          break;
        }
        if (evt.event === 'answer') {
          if (typeof evt.response === 'string' && evt.response) yield evt.response;
          finished = true;
          break;
        }
      }
    }
    if (streamError) throw new ApiError(502, streamError, 'error');
  } catch (e) {
    if ((e as Error).name === 'AbortError') {
      throw new ApiError(504, 'Finora took too long to respond. Please try again.', 'timeout');
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// ── Reviews ───────────────────────────────────────────────────────────────────
export async function getReviews(): Promise<Review[]> {
  const res = await apiFetch<{ reviews?: Array<Record<string, unknown>> }>('/api/reviews', {
    auth: false, timeoutMs: 15_000, retries: 1,
  });
  return (res.reviews ?? []).map((r, i) => ({
    id: String(r.id ?? r.timestamp ?? `rev-${i}`),
    name: String(r.name ?? 'Anonymous'),
    company: r.company ? String(r.company) : undefined,
    stars: Number(r.rating ?? 5),
    text: String(r.review ?? ''),
    date: String(r.timestamp ?? '').slice(0, 10) || new Date().toISOString().slice(0, 10),
  }));
}

export async function postReview(input: { name: string; company?: string; stars: number; text: string }): Promise<Review> {
  const res = await apiFetch<{ status?: string; review?: Record<string, unknown>; error?: string }>('/api/reviews', {
    method: 'POST',
    body: { name: input.name, company: input.company ?? '', rating: input.stars, review: input.text, website: '' },
    auth: false,
    timeoutMs: 20_000,
    retries: 0,
  });
  if (res.status && res.status !== 'success') {
    throw new ApiError(400, res.error || 'Could not post review.', 'validation');
  }
  const r = res.review ?? {};
  return {
    id: String(r.id ?? r.timestamp ?? Date.now()),
    name: String(r.name ?? input.name),
    company: (r.company ? String(r.company) : input.company) || undefined,
    stars: Number(r.rating ?? input.stars),
    text: String(r.review ?? input.text),
    date: String(r.timestamp ?? '').slice(0, 10) || new Date().toISOString().slice(0, 10),
  };
}

// ── Profile ───────────────────────────────────────────────────────────────────
export async function updateProfile(name: string): Promise<{ name: string }> {
  const trimmed = name.trim();
  if (trimmed.length < 2) throw new ApiError(400, 'Name must be at least 2 characters.', 'validation');
  const res = await apiFetch<{ user?: { name?: string } }>('/api/auth/update-profile', {
    method: 'POST', body: { name: trimmed }, retries: 1,
  });
  return { name: res.user?.name ?? trimmed };
}

// ── Watchlist (device-local) ──────────────────────────────────────────────────
const WATCH_KEY = 'finora_watchlist_v1';
export function getWatchlist(): string[] {
  try { return JSON.parse(localStorage.getItem(WATCH_KEY) ?? '[]') as string[]; } catch { return []; }
}
export function toggleWatch(ticker: string): string[] {
  const t = ticker.toUpperCase();
  const list = getWatchlist();
  const next = list.includes(t) ? list.filter((x) => x !== t) : [...list, t];
  try { localStorage.setItem(WATCH_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  return next;
}

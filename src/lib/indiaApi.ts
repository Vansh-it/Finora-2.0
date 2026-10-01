/**
 * India API client — production research endpoint.
 * Replaces the demo/fixture client with the real backend IndiaAdapter flow.
 */

import type { IndiaDashboardPayload } from "../types/india";

const API_BASE = import.meta.env.VITE_API_URL || "";

export interface IndiaCompanySearchResult {
  query: string;
  status: string;
  message: string;
  entity_type: string;
  retrieved_at: string;
  usable: boolean;
  stages: Array<{
    stage: string;
    ok: boolean;
    reason?: string;
    detail?: Record<string, unknown>;
  }>;
  dashboard: IndiaDashboardPayload | null;
}

export async function researchIndia(query: string): Promise<IndiaCompanySearchResult> {
  const res = await fetch(`${API_BASE}/api/india/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error || `India research failed (${res.status})`);
  }
  return res.json();
}

// --- Demo endpoints (still live on the backend for development previews) ---

export interface IndiaDemoCompany {
  slug: string;
  ticker: string;
  name: string;
  entity_type: string;
  is_fixture: boolean;
}

export async function listIndiaDemoCompanies(): Promise<{
  companies: IndiaDemoCompany[];
  is_fixture: boolean;
}> {
  const res = await fetch(`${API_BASE}/api/india/demo/companies`);
  if (!res.ok) throw new Error(`Failed to load India demo companies (${res.status})`);
  return res.json();
}

export async function getIndiaDemoDashboard(
  slug: string,
  scope: string = "CONSOLIDATED"
): Promise<IndiaDashboardPayload> {
  const res = await fetch(
    `${API_BASE}/api/india/demo/dashboard/${encodeURIComponent(slug)}?scope=${encodeURIComponent(scope)}`
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error || `Failed to load India dashboard (${res.status})`);
  }
  return res.json();
}
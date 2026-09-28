/**
 * India demo API client — development fixture endpoints only.
 * These routes serve clearly-labeled fixture data and never touch the
 * production US research pipeline.
 */

const API_BASE = import.meta.env.VITE_API_URL || "";

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
): Promise<import("../types/india").IndiaDashboardPayload> {
  const res = await fetch(
    `${API_BASE}/api/india/demo/dashboard/${encodeURIComponent(slug)}?scope=${encodeURIComponent(scope)}`
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.error || `Failed to load India dashboard (${res.status})`);
  }
  return res.json();
}

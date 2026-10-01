/**
 * Region dispatch client.
 *
 * A research request is routed by the backend before any research starts: the
 * query is resolved against the market it is listed on, and the answer names
 * the pipeline that should run. This module only carries that verdict to the
 * UI. It does not decide anything, and it never falls back to a default region
 * — an unroutable query is reported, not guessed.
 */

import type { ResearchRegion } from "./researchStages";

const API_BASE = import.meta.env.VITE_API_URL || "";

export interface RouteIdentity {
  region: ResearchRegion | null;
  country: string;
  confidence: number;
  method: string;
  display_name: string;
  identifier: string;
  exchange: string;
  entity_type: string;
  definitive: boolean;
  ambiguous: boolean;
  candidates: Array<Record<string, unknown>>;
}

export interface RegionRoute {
  query: string;
  status: "ROUTED" | "AMBIGUOUS" | "UNRESOLVED";
  region: ResearchRegion | null;
  country: string;
  pipeline: string;
  exchanges: string[];
  message: string;
  identity: RouteIdentity | null;
}

export class RegionRoutingError extends Error {
  readonly route: RegionRoute;

  constructor(route: RegionRoute) {
    super(
      route.message ||
        "Finora could not determine which market this company is listed on."
    );
    this.name = "RegionRoutingError";
    this.route = route;
  }
}

/**
 * Ask the backend which pipeline serves `query`.
 *
 * Throws {@link RegionRoutingError} when the query cannot be placed on a single
 * exchange, so an unroutable search fails loudly instead of defaulting to the
 * US pipeline.
 */
export async function resolveRegion(query: string): Promise<RegionRoute> {
  const res = await fetch(`${API_BASE}/api/research/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });

  let route: RegionRoute | null = null;
  try {
    route = (await res.json()) as RegionRoute;
  } catch {
    throw new Error(
      `Could not reach the Finora backend (${res.status}). Make sure it is running on port 8000.`
    );
  }

  if (!res.ok || route.status !== "ROUTED" || !route.region) {
    throw new RegionRoutingError(route);
  }
  return route;
}

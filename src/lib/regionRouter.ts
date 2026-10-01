/**
 * Region dispatch client.
 *
 * A research request is routed by the backend before any research starts, against
 * the market the *user* selected. That selection is a constraint the backend
 * enforces: it searches one market, and if the company turns out to be listed in
 * the other one it says so rather than answering from there.
 *
 * This module carries that verdict to the UI. It does not decide anything, and it
 * never falls back to a different region — an unroutable query is reported, a
 * cross-market query becomes a switchable refusal, and neither defaults to the US
 * pipeline.
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

export type RouteStatus = "ROUTED" | "AMBIGUOUS" | "UNRESOLVED" | "MISMATCH";

export interface RegionRoute {
  query: string;
  status: RouteStatus;
  region: ResearchRegion | null;
  country: string;
  pipeline: string;
  exchanges: string[];
  message: string;
  /** The market the user asked for, echoed back so the UI can keep their choice. */
  selected_region: ResearchRegion | null;
  /** True when the company was found, but in the market the user did not pick. */
  mismatch: boolean;
  /** The market the company is actually listed in, when `mismatch` is true. */
  mismatch_target: ResearchRegion | null;
  identity: RouteIdentity | null;
  considered?: RouteIdentity[];
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
 * The company was found, but in the market the user did not select.
 *
 * Carries the route so the caller can name the company and offer a switch.
 * Never rendered as an error: nothing went wrong, the user is simply standing in
 * the wrong market, and one click fixes it.
 */
export class RegionMismatchError extends Error {
  readonly route: RegionRoute;
  readonly target: ResearchRegion;

  constructor(route: RegionRoute) {
    super(route.message);
    this.name = "RegionMismatchError";
    this.route = route;
    this.target = (route.mismatch_target || "US") as ResearchRegion;
  }
}

/**
 * The query matches more than one company in the selected market.
 *
 * Carries the candidates so the user picks, instead of the router picking for
 * them. Distinct from a mismatch: here the market is right and the name is not
 * specific enough.
 */
export class AmbiguousCompanyQueryError extends Error {
  readonly route: RegionRoute;
  readonly candidates: RouteIdentity[];

  constructor(route: RegionRoute) {
    super(route.message);
    this.name = "AmbiguousCompanyQueryError";
    this.route = route;
    this.candidates = route.considered ?? [];
  }
}

/**
 * Ask the backend which pipeline serves `query` in `region`.
 *
 * `region` is the market the user selected and is sent as a constraint: the
 * backend searches only that market, and answers `MISMATCH` when the company
 * lives elsewhere. This function never falls back to a different region — an
 * unroutable search fails loudly instead of defaulting to the US pipeline, and a
 * cross-market search surfaces as a switchable {@link RegionMismatchError}
 * rather than being answered from the other market.
 *
 * Throws {@link RegionMismatchError} or {@link AmbiguousCompanyQueryError} for
 * the two refusals the user can act on; {@link RegionRoutingError} for the rest.
 */
export async function resolveRegion(
  query: string,
  region: ResearchRegion
): Promise<RegionRoute> {
  const res = await fetch(`${API_BASE}/api/research/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, region }),
  });

  let route: RegionRoute | null = null;
  try {
    route = (await res.json()) as RegionRoute;
  } catch {
    throw new Error(
      `Could not reach the Finora backend (${res.status}). Make sure it is running on port 8000.`
    );
  }

  if (route.status === "MISMATCH") {
    throw new RegionMismatchError(route);
  }
  if (route.status === "AMBIGUOUS") {
    throw new AmbiguousCompanyQueryError(route);
  }
  if (!res.ok || route.status !== "ROUTED" || !route.region) {
    throw new RegionRoutingError(route);
  }
  return route;
}

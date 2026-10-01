/**
 * Region-specific progress vocabulary.
 *
 * The research progress screen narrates the pipeline that is actually running.
 * Each stage list is written in the language of the market it belongs to, so a
 * company listed on NSE is never described as a NASDAQ filer with a CIK and
 * 10-Ks, and a US company is never described in rupee terms.
 *
 * These are display strings only. Which list is used is decided by the
 * backend's region route, never by matching on the company's name.
 */

import type { RegionRoute, RouteIdentity } from "./regionRouter";

export type ResearchRegion = "US" | "INDIA";

/**
 * The markets Finora can research, in the order the selector shows them.
 *
 * This list is the UI's only notion of which market a search is for. It is
 * deliberately separate from what the backend *supports* today: India research
 * runs through its own pipeline and endpoint, so selecting it must be able to
 * say "not available yet" rather than quietly sending the search to SEC/EDGAR.
 */
export const RESEARCH_REGIONS: ResearchRegion[] = ["US", "INDIA"];

export const REGION_LABELS: Record<ResearchRegion, string> = {
  US: "US",
  INDIA: "India",
};

/** The exchange group a region's research draws from. */
export const REGION_EXCHANGES: Record<ResearchRegion, string> = {
  US: "Nasdaq / NYSE / AMEX",
  INDIA: "NSE / BSE",
};

export function isResearchRegion(value: unknown): value is ResearchRegion {
  return typeof value === "string" && (RESEARCH_REGIONS as string[]).includes(value);
}

/**
 * Read a region from a URL, falling back to the US market.
 *
 * The fallback is the *default*, not a detection: a link without a region is a
 * US search, exactly as it was before regions existed. An unrecognised value is
 * also US rather than a thrown error, because a stale bookmark should land on a
 * working page instead of a blank route.
 */
export function researchRegionFromParam(value: string | null | undefined): ResearchRegion {
  const normalized = (value || "").trim().toUpperCase();
  if (normalized === "INDIA") return "INDIA";
  return "US";
}

export interface ResearchStage {
  key: string;
  title: string;
  detail: string;
}

export const US_STAGES: ResearchStage[] = [
  { key: "company", title: "Entity Identified", detail: "Resolved company name to CIK and primary exchange listing." },
  { key: "filings", title: "SEC Filings Located", detail: "Located most recent 10-K, 10-Q and 8-K filings via EDGAR." },
  { key: "financials", title: "Financial Statements", detail: "Extracting income statement, balance sheet & cash flow from XBRL." },
  { key: "metrics", title: "Metrics Calculated", detail: "Deriving profitability, growth, efficiency and valuation metrics." },
  { key: "sources", title: "Sources Discovered", detail: "Searching for authoritative company financial sources." },
  { key: "verify", title: "Source Verification", detail: "Cross-checking figures against external sources." },
  { key: "summary", title: "Analysis Generated", detail: "Generating the executive research memo." },
  { key: "valuation", title: "Valuation Complete", detail: "Fetching market data and calculating valuation multiples." },
  { key: "complete", title: "Research File Complete", detail: "Assembling the final research record." },
];

export const INDIA_STAGES: ResearchStage[] = [
  { key: "entity", title: "Entity Identified", detail: "Matched the company to its NSE symbol, ISIN and primary listing." },
  { key: "entity_type", title: "Entity Type Classified", detail: "Determining the reporting schema — corporate, bank or NBFC." },
  { key: "disclosures", title: "Indian Disclosures Located", detail: "Locating recent financial-results filings and shareholding patterns on the exchange." },
  { key: "financials", title: "Financial Statements", detail: "Reading the income statement, balance sheet and cash flow from the filed PDF, optically where the filing is a scan." },
  { key: "validation", title: "Validation", detail: "Reconciling every published figure against the filing's own arithmetic before it is shown." },
  { key: "metrics", title: "Metrics", detail: "Deriving profitability, growth, efficiency and valuation metrics from the validated statements." },
  { key: "complete", title: "Research Complete", detail: "Assembling the final research record." },
];

export function stagesForRegion(region: ResearchRegion): ResearchStage[] {
  return region === "INDIA" ? INDIA_STAGES : US_STAGES;
}

/** The exchange label shown beside the company while research runs. */
export function exchangeLabelForRegion(route: RegionRoute): string {
  if (route.region === "INDIA") return route.exchanges[0] || "NSE";
  return route.identity?.exchange || route.exchanges[0] || "NASDAQ";
}

/** The symbol shown beside the company while research runs. */
export function identifierForRoute(route: RegionRoute): string {
  return route.identity?.identifier || route.query;
}

/** The company name shown beside the symbol while research runs. */
export function nameForRoute(route: RegionRoute, fallback: string): string {
  return route.identity?.display_name || fallback;
}

export type { RouteIdentity };

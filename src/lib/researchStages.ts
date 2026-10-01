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

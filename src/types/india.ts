/**
 * India dashboard types — mirror backend lib/india payloads.
 * Values are raw INR numbers; display strings are pre-formatted by the backend.
 */

export type MetricStatusType =
  | "REPORTED"
  | "CALCULATED"
  | "DERIVED"
  | "MARKET_DATA"
  | "UNAVAILABLE";

export interface IndiaMetricCard {
  metric_id: string;
  display_name: string;
  value: number | null;
  display_value: string;
  status: MetricStatusType;
  unit_type: string;
  formatting: string;
  period: string;
  formula?: string;
  inputs?: string[];
  source_ids?: string[];
  reason?: string;
  unavailable?: boolean;
  spark?: number[];
  change?: { value: string; direction: string };
}

export interface IndiaStatementRow {
  metric_id: string;
  label: string;
  values: Array<{
    display_value: string;
    unavailable: boolean;
    reason: string;
    raw: number | null;
  }>;
  is_total: boolean;
  formatting: string;
}

export interface IndiaStatement {
  statement_type: string;
  rows: IndiaStatementRow[];
  periods: string[];
}

export interface IndiaOwnershipRow {
  period: string;
  promoter_pct: number | null;
  promoter_change_qoq?: number | null;
  promoter_change_yoy?: number | null;
  promoter_pledge_pct: number | null;
  fii_pct: number | null;
  dii_pct: number | null;
  mutual_fund_pct: number | null;
  public_pct: number | null;
  institutional_pct: number | null;
  government_pct?: number | null;
  status?: string;
  source_ids?: string[];
  reason?: string;
}

export interface IndiaSource {
  source_id: string;
  source_name: string;
  source_type: string;
  trust_tier: string;
  document_type: string;
  document_title: string;
  period: string;
  published_date: string;
  url: string;
  retrieved_at: string;
  used_for: string;
  status: string;
  is_fixture: boolean;
}

export type DetectorStatusType =
  /** A red flag fired. */
  | "ACTIVE"
  /** The detector ran and found nothing wrong. */
  | "CLEAN"
  /** The detector could not reach a verdict from available data. */
  | "INSUFFICIENT_DATA"
  | "NOT_APPLICABLE"
  /** The detector needs a source that is not integrated yet. */
  | "PENDING_SOURCE_INTEGRATION";

export interface IndiaRedFlag {
  flag_id: string;
  title: string;
  severity: string;
  status: DetectorStatusType;
  reason: string;
  rule?: string;
  evidence: Array<{ label: string; value: string }>;
  sources: string[];
  category: string;
}

export interface IndiaForensicModel {
  model: string;
  applicable: boolean;
  status: string;
  reason: string;
  inputs?: string[];
  calculation?: string;
  result?: {
    score: number;
    max: number;
    status: string;
    signals: Array<{ label: string; value: number }>;
  } | null;
}

export interface IndiaCompleteness {
  entity_type: string;
  expected: number;
  available: number;
  coverage_pct: number | null;
  reported: number;
  calculated: number;
  derived: number;
  market_data: number;
  unavailable: number;
  not_applicable: number;
  pending_source: number;
  categories: Array<{
    category: string;
    display_name: string;
    expected: number;
    available: number;
    coverage_pct: number | null;
    missing: Array<{
      metric_id: string;
      display_name: string;
      reason: string;
      priority: string;
      derivable: boolean;
      required_inputs: string[];
      recovery_strategy: string;
    }>;
  }>;
  missing_metrics: Array<{
    metric_id: string;
    display_name: string;
    category: string;
    reason: string;
    priority: string;
    possible_sources: string[];
    derivable: boolean;
    required_inputs: string[];
    recovery_strategy: string;
  }>;
  metric_details: Record<string, string>;
}

export interface IndiaDashboardPayload {
  version: string;
  is_fixture: boolean;
  fixture_notice: string;
  entity_type: "CORPORATE" | "BANK" | "NBFC";
  header: {
    name: string;
    legal_name: string;
    nse_symbol: string;
    bse_code: string;
    isin: string;
    cin: string;
    primary_exchange: string;
    sector: string;
    industry: string;
    description: string;
    fiscal_period: string;
    scope: string;
    reporting_standard: string;
    currency: string;
    country: string;
    price: number | null;
    price_display: string;
    price_change: number | null;
    price_change_display: string;
    market_cap: number | null;
    market_cap_display: string;
    market_data_status: string;
    is_fixture: boolean;
    price_date: string;
  };
  periods: string[];
  latest_period: string;
  scope: string;
  available_scopes: string[];
  kpis: IndiaMetricCard[];
  statements: Record<string, IndiaStatement>;
  tabs: Record<
    string,
    { title: string; metrics: IndiaMetricCard[] }
  >;
  ownership: {
    rows: IndiaOwnershipRow[];
    latest: IndiaOwnershipRow | null;
    yoy_changes: Record<string, number>;
    available: boolean;
  };
  forensics: {
    red_flags: IndiaRedFlag[];
    active_flags: IndiaRedFlag[];
    models: IndiaForensicModel[];
    earnings_quality: {
      available: boolean;
      period?: string;
      signals: Array<{
        id: string;
        label: string;
        value: string;
        rule: string;
        ok_when: string;
        inputs: Record<string, number | null>;
      }>;
      methodology?: string;
    };
  };
  valuation: {
    market_data: {
      price: number | null;
      price_date: string;
      percent_change: number | null;
      market_cap: number | null;
      currency: string;
      exchange: string;
      data_status: string;
      is_fixture: boolean;
      reason: string;
    } | null;
    metrics: IndiaMetricCard[];
    fixture_warning: boolean;
  };
  macro: {
    available: boolean;
    is_fixture: boolean;
    strip: Array<{ label: string; value: string; date?: string; status?: string }>;
    attribution: string;
  };
  sources: IndiaSource[];
  completeness: IndiaCompleteness;
}

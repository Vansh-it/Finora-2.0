/**
 * Region-agnostic dashboard view contracts.
 *
 * These are deliberately *structural*: a US payload and an India payload are
 * both assignable to them without either importing the other. Nothing here
 * may mention a currency, an exchange, a fiscal-year convention, or a filing
 * regime. Formatting is computed server-side and arrives as `display_value`;
 * this layer only chooses how to lay it out.
 *
 * If a field cannot be expressed for every region, it does not belong here —
 * it belongs in the region component that wraps these.
 */

/** One cell in a statement row. `unavailable` never renders as zero. */
export interface SharedStatementCell {
  display_value: string;
  unavailable: boolean;
  reason: string;
}

/** One line item, spanning every statement period. */
export interface SharedStatementRow {
  metric_id: string;
  label: string;
  values: SharedStatementCell[];
  is_total: boolean;
}

/** A statement (income / balance sheet / cash flow) across periods. */
export interface SharedStatement {
  rows: SharedStatementRow[];
  periods: string[];
}

/**
 * A single metric value.
 *
 * `status` is open-ended by design: regions add their own provenance
 * vocabulary, so this is `string` rather than a shared enum. A component must
 * degrade gracefully when it meets a status it does not recognise.
 */
export interface SharedMetricCard {
  metric_id: string;
  display_name: string;
  display_value: string;
  status: string;
  unavailable?: boolean;
  reason?: string;
  spark?: number[];
  change?: { value: string; direction: string };
}

/** A finding from a detector run. Only `ACTIVE` findings are surfaced. */
export interface SharedRedFlag {
  flag_id: string;
  title: string;
  severity: string;
  status: string;
  reason: string;
}

/** A scorecard model (Piotroski, DuPont, …) and its applicability. */
export interface SharedForensicModel {
  model: string;
  applicable: boolean;
  status: string;
  reason: string;
  result?: {
    score: number;
    max: number;
  } | null;
}

/** One document behind the analysis, with its trust tier. */
export interface SharedSourceEntry {
  source_id: string;
  source_name: string;
  trust_tier: string;
  document_type: string;
  period: string;
  used_for: string;
  status: string;
  is_fixture: boolean;
}

/** Macro context strip. The title is caller-supplied, never hardcoded. */
export interface SharedMacroContext {
  available: boolean;
  is_fixture: boolean;
  strip: Array<{ label: string; value: string }>;
  attribution: string;
}

/**
 * A holder-category column in an ownership table.
 *
 * Holder categories are region-specific — promoter/FII/DII are Indian
 * concepts. The table stays generic and the region supplies the columns.
 */
export interface SharedOwnershipColumn<Row> {
  key: keyof Row & string;
  label: string;
}

/** Coverage rollup backing the research-quality bar. */
export interface SharedCompleteness {
  expected: number;
  available: number;
  coverage_pct: number | null;
  reported: number;
  calculated: number;
  derived: number;
  unavailable: number;
}

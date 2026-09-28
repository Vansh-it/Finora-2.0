/**
 * Region-agnostic dashboard components.
 *
 * Everything here renders a payload without knowing which market it came from.
 * Region modules (`india/`, and the US dashboard) supply the data, the labels,
 * and the region-specific wrappers. Nothing in this folder may import from
 * `types/india` or any other region's types.
 */
export { default as StatementTable } from "./StatementTable";
export { default as MetricCard, StatusChip, ReasonNote, UnavailableMetricCard } from "./MetricCard";
export { default as MetricGrid } from "./MetricGrid";
export { default as RedFlagList } from "./RedFlagList";
export { default as ForensicModelCards } from "./ForensicModelCards";
export { default as OwnershipTable } from "./OwnershipTable";
export { default as MacroContextStrip } from "./MacroContextStrip";
export { default as SourceLedger } from "./SourceLedger";
export type {
  SharedStatement,
  SharedStatementRow,
  SharedStatementCell,
  SharedMetricCard,
  SharedRedFlag,
  SharedForensicModel,
  SharedSourceEntry,
  SharedMacroContext,
  SharedOwnershipColumn,
  SharedCompleteness,
} from "./types";

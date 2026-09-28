import { Search } from "lucide-react";
import { cn } from "../../../utils/cn";
import type { SharedMetricCard } from "./types";

/**
 * Provenance chip.
 *
 * The four shared provenance states are rendered here; a region that adds more
 * gets a bare uppercase status rather than a wrong label, because a silent
 * empty chip would hide the fact that data provenance is unknown.
 */
const STATUS_LABEL: Record<string, string> = {
  REPORTED: "Reported",
  CALCULATED: "Calculated",
  DERIVED: "Derived",
  MARKET_DATA: "Market Data",
};

export function StatusChip({ status }: { status: string }) {
  const label = STATUS_LABEL[status];
  return (
    <span className="font-mono text-[9px] font-semibold tracking-[0.12em] text-ink-3 uppercase">
      {label ?? status}
    </span>
  );
}

/** Reason line for an unavailable metric, carried in the tooltip. */
export function ReasonNote({ reason }: { reason?: string }) {
  if (!reason) return null;
  return (
    <p className="mt-1 font-mono text-[9px] tracking-wide text-ink-3" title={reason}>
      {reason}
    </p>
  );
}

/**
 * Unavailable placeholder.
 *
 * Renders an em dash and the reason, never a zero: a missing input and a
 * measured zero are different facts and collapsing them is the single most
 * misleading thing a financial dashboard can do.
 */
export function UnavailableMetricCard({
  label,
  reason,
  compact,
}: {
  label: string;
  reason?: string;
  compact?: boolean;
}) {
  return (
    <div className={cn("border border-ink/15 bg-paper-2/40 p-5", compact && "p-4")}>
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-ink-3 uppercase">
          {label}
        </span>
        <span className="font-mono text-[9px] font-semibold tracking-[0.12em] text-ink-3 uppercase">
          N/A
        </span>
      </div>
      <div className="mt-3 font-mono text-lg font-bold text-ink-3">—</div>
      <ReasonNote reason={reason} />
    </div>
  );
}

/**
 * Metric card: current value, period-over-period change, sparkline, and a
 * provenance chip. Values arrive pre-formatted from the metric engine.
 */
export default function MetricCard({
  metric,
  onInspect,
  highlighted,
  showSpark,
}: {
  metric: SharedMetricCard;
  onInspect?: (metricId: string) => void;
  highlighted?: boolean;
  showSpark?: boolean;
}) {
  if (metric.unavailable || metric.status === "UNAVAILABLE") {
    return <UnavailableMetricCard label={metric.display_name} reason={metric.reason} />;
  }

  const dir = metric.change?.direction;
  const hasSpark = showSpark && (metric.spark?.length ?? 0) > 1;
  const sparkMax = hasSpark ? Math.max(...(metric.spark ?? [])) : 0;
  const sparkMin = hasSpark ? Math.min(...(metric.spark ?? [])) : 0;
  const range = sparkMax - sparkMin || 1;

  return (
    <div
      className={cn(
        "group relative border border-ink/20 bg-paper p-5 transition-colors",
        highlighted && "border-ink"
      )}
    >
      <div className="flex items-start justify-between">
        <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-ink-3 uppercase">
          {metric.display_name}
        </span>
        <div className="flex items-center gap-2">
          <StatusChip status={metric.status} />
          {onInspect && (
            <button
              onClick={() => onInspect(metric.metric_id)}
              aria-label={`How Finora calculated ${metric.display_name}`}
              title={`How Finora calculated ${metric.display_name}`}
              className="text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:text-annotate-blue"
            >
              <Search size={13} />
            </button>
          )}
        </div>
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span
          className={cn(
            "font-mono text-2xl font-bold text-ink tabular sm:text-3xl",
            highlighted && "mark-highlight"
          )}
        >
          {metric.display_value}
        </span>
        {metric.change && metric.change.value !== "—" && (
          <span
            className={cn(
              "font-mono text-xs font-semibold",
              dir === "up" && "text-annotate-green",
              dir === "down" && "text-annotate-red",
              (!dir || dir === "flat") && "text-ink-3"
            )}
          >
            {metric.change.value}
          </span>
        )}
      </div>

      {hasSpark && (
        <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="mt-2 h-6 w-full">
          <polyline
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="text-ink/60"
            points={(metric.spark ?? [])
              .map((v, i) => {
                const x = (i / ((metric.spark?.length ?? 1) - 1)) * 100;
                const y = 22 - ((v - sparkMin) / range) * 20;
                return `${x},${y}`;
              })
              .join(" ")}
          />
        </svg>
      )}
    </div>
  );
}

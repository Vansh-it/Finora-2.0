import MetricCard from "./MetricCard";
import type { SharedMetricCard } from "./types";

/** Metric grid used across every tab (growth, profitability, ratios…). */
export default function MetricGrid({
  metrics,
  onInspect,
  showSpark,
}: {
  metrics: SharedMetricCard[];
  onInspect?: (metricId: string) => void;
  showSpark?: boolean;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {metrics.map((m) => (
        <MetricCard key={m.metric_id} metric={m} onInspect={onInspect} showSpark={showSpark} />
      ))}
    </div>
  );
}

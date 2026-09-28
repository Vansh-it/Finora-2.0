import { Search } from "lucide-react";
import { cn } from "../../../utils/cn";
import type { SharedStatement } from "./types";

/**
 * Financial statement table: line items as rows, periods as columns.
 *
 * The unit label is caller-supplied because the magnitude convention
 * (crore, million, thousands) is a region concern, not a layout one.
 */
export default function StatementTable({
  title,
  statement,
  unitLabel,
  onInspect,
}: {
  title: string;
  statement: SharedStatement;
  unitLabel: string;
  onInspect?: (metricId: string) => void;
}) {
  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between">
        <h3 className="font-serif text-2xl font-semibold text-ink">{title}</h3>
        <span className="font-mono text-[10px] font-semibold tracking-widest text-ink-3 uppercase">
          {unitLabel}
        </span>
      </div>
      <div className="thin-scroll overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-sm">
          <thead>
            <tr className="border-b-2 border-ink">
              <th className="sticky left-0 bg-paper py-2 pr-4 text-left font-mono text-[10px] font-bold tracking-widest text-ink-3 uppercase">
                Line Item
              </th>
              {statement.periods.map((p) => (
                <th
                  key={p}
                  className="py-2 pl-4 text-right font-mono text-[10px] font-bold tracking-widest text-ink-3 uppercase"
                >
                  {p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {statement.rows.map((row) => (
              <tr
                key={row.metric_id}
                className={cn(
                  "group border-b border-ink/12 hover:bg-paper-2/60",
                  row.is_total && "border-b border-ink/40 font-semibold"
                )}
              >
                <td className="sticky left-0 bg-paper py-3 pr-4 text-ink-2 group-hover:bg-paper-2/60">
                  <div className="flex items-center gap-1.5">
                    {row.label}
                    {onInspect && (
                      <button
                        onClick={() => onInspect(row.metric_id)}
                        aria-label={`How Finora got ${row.label}`}
                        title={`How Finora got ${row.label}`}
                        className="text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:text-annotate-blue"
                      >
                        <Search size={11} />
                      </button>
                    )}
                  </div>
                </td>
                {row.values.map((v, i) => (
                  <td
                    key={i}
                    className={cn(
                      "py-3 pl-4 text-right font-mono tabular",
                      v.unavailable ? "text-ink-3" : "text-ink"
                    )}
                    title={v.unavailable ? v.reason : undefined}
                  >
                    {v.unavailable ? "—" : v.display_value}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

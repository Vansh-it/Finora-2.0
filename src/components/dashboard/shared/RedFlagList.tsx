import { Search } from "lucide-react";
import { cn } from "../../../utils/cn";
import type { SharedRedFlag } from "./types";

/**
 * Red-flag list.
 *
 * Only ACTIVE findings are listed. `CLEAN`, `INSUFFICIENT_DATA` and the rest
 * are *absence of evidence*, not good news, so they are not summarised here —
 * the coverage bar carries that distinction instead.
 */
export default function RedFlagList<T extends SharedRedFlag>({
  flags,
  onInspect,
}: {
  flags: T[];
  onInspect: (flag: T) => void;
}) {
  const active = flags.filter((f) => f.status === "ACTIVE");
  if (active.length === 0) {
    return (
      <p className="font-mono text-xs tracking-[0.15em] text-ink-3 uppercase">
        No active red flags in current data.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <p className="font-mono text-xs font-semibold tracking-[0.25em] text-ink-3 uppercase">
        {active.length} Item{active.length !== 1 ? "s" : ""} Deserve Attention
      </p>
      {active.map((flag, i) => (
        <div
          key={flag.flag_id}
          className={cn(
            "flex items-start justify-between border border-ink/15 border-l-4 bg-paper p-5",
            flag.severity === "HIGH" ? "border-l-annotate-red" : "border-l-annotate-blue"
          )}
        >
          <div className="flex-1">
            <div className="flex items-baseline gap-3">
              <span className="font-mono text-xs font-bold text-ink-3">
                {String(i + 1).padStart(2, "0")}
              </span>
              <h4 className="font-serif text-sm font-semibold text-ink uppercase">
                {flag.title}
              </h4>
            </div>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-2">{flag.reason}</p>
          </div>
          <button
            onClick={() => onInspect(flag)}
            className="ml-4 flex shrink-0 items-center gap-1 font-mono text-[10px] text-ink-3 underline hover:text-ink"
          >
            Evidence <Search size={11} />
          </button>
        </div>
      ))}
    </div>
  );
}

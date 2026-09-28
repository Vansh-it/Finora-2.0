import { cn } from "../utils/cn";

interface RedFlag {
  id: string;
  title: string;
  headline: string;
  reason: string;
  severity: string;
  tag: string;
  evidence?: Record<string, unknown>;
}

const SEVERITY_STYLE: Record<string, string> = {
  low: "border-l-annotate-blue",
  medium: "border-l-annotate-blue",
  high: "border-l-annotate-red",
  critical: "border-l-annotate-red",
};

export default function RedFlagList({
  flags,
  onInspect,
}: {
  flags: RedFlag[];
  onInspect?: (metric: string) => void;
}) {
  if (!flags || flags.length === 0) return null;

  return (
    <div className="space-y-4">
      <p className="font-mono text-xs font-semibold tracking-[0.25em] text-ink-3 uppercase">
        {flags.length} Item{flags.length !== 1 ? "s" : ""} Deserve Attention
      </p>

      {flags.map((flag, i) => (
        <div
          key={flag.id || i}
          className={cn(
            "border border-ink/15 border-l-4 bg-paper p-5",
            SEVERITY_STYLE[flag.severity] || "border-l-ink/30"
          )}
        >
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-xs font-bold text-ink-3">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h4 className="font-serif text-sm font-semibold text-ink uppercase">
                  {flag.headline || flag.title}
                </h4>
              </div>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-2">
                {flag.reason}
              </p>
              {flag.evidence && Object.keys(flag.evidence).length > 0 && (
                <div className="mt-2 font-mono text-[10px] text-ink-3">
                  {Object.entries(flag.evidence).slice(0, 3).map(([k, v]) => (
                    <span key={k} className="mr-3">
                      {k.replace(/_/g, " ")}: {String(v)}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {onInspect && (
              <button
                onClick={() => onInspect(flag.headline || flag.title)}
                className="ml-4 shrink-0 font-mono text-[10px] text-ink-3 underline hover:text-ink"
              >
                Evidence →
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

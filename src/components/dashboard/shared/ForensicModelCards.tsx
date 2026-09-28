import type { SharedForensicModel } from "./types";

/**
 * Forensic scorecard cards, with their applicability state shown explicitly.
 *
 * An inapplicable model is rendered, not hidden: a reader needs to know the
 * model was considered and does not apply, which is different from a model
 * that was never run.
 */
export default function ForensicModelCards<T extends SharedForensicModel>({
  models,
  onInspect,
}: {
  models: T[];
  onInspect: (model: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {models.map((m) => (
        <button
          key={m.model}
          onClick={() => onInspect(m.model)}
          className="border border-ink/20 bg-paper p-5 text-left transition-colors hover:border-ink"
        >
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-ink-3 uppercase">
              {m.model}
            </span>
            {!m.applicable && (
              <span className="font-mono text-[9px] tracking-[0.12em] text-ink-3 uppercase">
                N/A
              </span>
            )}
          </div>
          {m.result ? (
            <div className="mt-3 font-mono text-3xl font-bold text-ink tabular">
              {m.result.score}
              <span className="text-base text-ink-3">/{m.result.max}</span>
            </div>
          ) : (
            <div className="mt-3 font-mono text-sm font-semibold text-ink-3 uppercase">
              {m.status === "PENDING_SOURCE_INTEGRATION" ? "Pending Source" : m.status}
            </div>
          )}
          <p className="mt-2 line-clamp-2 font-mono text-[10px] leading-relaxed text-ink-3">
            {m.reason}
          </p>
        </button>
      ))}
    </div>
  );
}

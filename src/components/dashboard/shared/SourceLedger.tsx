import type { SharedSourceEntry } from "./types";

/**
 * Source ledger: every document behind the analysis, with its trust tier.
 *
 * Fixture sources are labelled in place rather than hidden. A reader must be
 * able to tell which rows came from a real filing and which did not.
 */
export default function SourceLedger({
  sources,
  fixtureLabel = "[DEV FIXTURE]",
}: {
  sources: SharedSourceEntry[];
  fixtureLabel?: string;
}) {
  return (
    <div className="divide-y divide-ink/12 border-y border-ink/20">
      {sources.map((s) => (
        <div
          key={s.source_id}
          className="flex flex-col gap-3 py-5 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start gap-4">
            <span className="font-mono text-sm font-bold text-ink-3">{s.source_id}</span>
            <div>
              <div className="font-serif text-lg font-semibold text-ink">
                {s.source_name}
                {s.is_fixture && (
                  <span className="ml-2 align-middle font-mono text-[9px] tracking-[0.14em] text-annotate-blue uppercase">
                    {fixtureLabel}
                  </span>
                )}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span className="border border-ink px-2 py-0.5 font-mono text-[9px] font-bold tracking-[0.12em] text-ink uppercase">
                  {s.trust_tier}
                </span>
                <span className="font-mono text-[10px] tracking-widest text-ink-3 uppercase">
                  {s.document_type} · {s.period}
                </span>
              </div>
              <p className="mt-1.5 max-w-md text-sm text-ink-2">{s.used_for}</p>
            </div>
          </div>
          <span className="font-mono text-[10px] font-bold tracking-widest text-annotate-green uppercase sm:pl-0">
            {s.status}
          </span>
        </div>
      ))}
    </div>
  );
}

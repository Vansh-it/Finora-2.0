import type { SharedMacroContext } from "./types";

/**
 * Macro context strip.
 *
 * The title is required. "India Macro Context" and "US Macro Context" are
 * region facts, so baking one in here would quietly mislabel the other.
 */
export default function MacroContextStrip({
  macro,
  title,
  fixtureLabel = "Fixture data",
}: {
  macro: SharedMacroContext;
  title: string;
  fixtureLabel?: string;
}) {
  if (!macro.available) return null;
  return (
    <div className="border border-ink/15 bg-paper p-5">
      <div className="mb-3 flex items-center justify-between">
        <p className="font-mono text-[10px] font-semibold tracking-[0.2em] text-ink-3 uppercase">
          {title}
        </p>
        {macro.is_fixture && (
          <span className="font-mono text-[9px] tracking-[0.14em] text-annotate-blue uppercase">
            {fixtureLabel}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {macro.strip.map((item) => (
          <div key={item.label}>
            <span className="font-mono text-[10px] tracking-wider text-ink-3 uppercase">
              {item.label}
            </span>
            <div className="mt-1 font-mono text-sm font-bold tabular text-ink">{item.value}</div>
          </div>
        ))}
      </div>
      <p className="mt-3 font-mono text-[9px] text-ink-3">{macro.attribution}</p>
    </div>
  );
}

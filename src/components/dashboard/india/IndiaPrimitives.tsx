import type { IndiaDashboardPayload } from "../../../types/india";
import { cn } from "../../../utils/cn";
import { MetricGrid } from "../shared";

/** Subtle development-fixture banner — required on every India demo view. */
export function FixtureBanner() {
  return (
    <div className="flex items-center gap-2 border border-dashed border-ink/30 bg-paper-2/50 px-4 py-2">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-annotate-blue" />
      <p className="font-mono text-[10px] font-semibold tracking-[0.14em] text-ink-2 uppercase">
        Development fixture data — not live company research
      </p>
    </div>
  );
}

/** Consolidated / Standalone view selector. */
export function ScopeSelector({
  scopes,
  value,
  onChange,
}: {
  scopes: string[];
  value: string;
  onChange: (s: string) => void;
}) {
  if (scopes.length < 2) return null;
  return (
    <label className="flex items-center gap-2">
      <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-ink-3 uppercase">
        Financial View
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border border-ink/30 bg-paper px-2 py-1.5 font-mono text-xs font-semibold text-ink focus:border-ink focus:outline-none"
      >
        {scopes.map((s) => (
          <option key={s} value={s}>
            {s.charAt(0) + s.slice(1).toLowerCase()}
          </option>
        ))}
      </select>
    </label>
  );
}

/**
 * India company header: NSE/BSE identity, fiscal period, scope,
 * audit status, reporting standard, price and market cap.
 * Reuses the US header's typographic language without its USD assumptions.
 */
export function IndiaCompanyHeader({
  header,
}: {
  header: IndiaDashboardPayload["header"];
}) {
  const positive = (header.price_change ?? 0) >= 0;
  return (
    <div className="border-b border-ink/15 pb-6">
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_auto_auto] lg:items-start">
        {/* Identity */}
        <div>
          <p className="font-mono text-xs font-semibold tracking-[0.25em] text-ink-3 uppercase">
            {header.sector}
            {header.industry ? ` · ${header.industry}` : ""}
          </p>
          <h1 className="mt-2 font-serif text-4xl font-semibold tracking-tight text-ink uppercase sm:text-5xl">
            {header.name}
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-xs text-ink-2">
            <span className="font-bold tracking-wider text-ink">
              NSE: {header.nse_symbol}
            </span>
            <span>BSE: {header.bse_code}</span>
            <span>ISIN: {header.isin}</span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Chip>{header.fiscal_period}</Chip>
            <Chip>{titleCase(header.scope)}</Chip>
            <Chip>Audited</Chip>
            <Chip>{header.reporting_standard}</Chip>
            <Chip>{header.currency}</Chip>
          </div>
          {header.description && (
            <p className="mt-3 max-w-xl font-sans text-sm leading-relaxed text-ink-2 line-clamp-2">
              {header.description}
            </p>
          )}
        </div>

        {/* Price */}
        <div className="flex flex-col items-start border-l border-ink/15 pl-8 lg:items-center lg:pl-8">
          <span className="font-mono text-[10px] font-semibold tracking-[0.25em] text-ink-3 uppercase">
            Share Price
          </span>
          <div className="mt-1 font-mono text-4xl font-bold text-ink tabular">
            {header.price_display}
          </div>
          <div
            className={cn(
              "mt-1 font-mono text-sm font-semibold",
              positive ? "text-annotate-green" : "text-annotate-red"
            )}
          >
            {header.price_change_display}
          </div>
          {header.market_data_status === "FIXTURE" && (
            <span className="mt-1 font-mono text-[9px] tracking-[0.14em] text-ink-3 uppercase">
              Fixture price
            </span>
          )}
        </div>

        {/* Market cap */}
        <div className="flex flex-col items-start border-l border-ink/15 pl-8 lg:items-center lg:pl-8">
          <span className="font-mono text-[10px] font-semibold tracking-[0.25em] text-ink-3 uppercase">
            Market Cap
          </span>
          <div className="mt-1 font-mono text-2xl font-bold text-ink tabular">
            {header.market_cap_display}
          </div>
        </div>
      </div>
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="border border-ink/25 px-2 py-0.5 font-mono text-[10px] font-semibold tracking-[0.12em] text-ink-2 uppercase">
      {children}
    </span>
  );
}

function titleCase(s: string): string {
  return s.charAt(0) + s.slice(1).toLowerCase();
}

/** India research quality bar — coverage, statuses, source tiers. */
export function IndiaResearchQualityBar({
  completeness,
  sourceCount,
  onOpen,
}: {
  completeness: IndiaDashboardPayload["completeness"];
  sourceCount: number;
  onOpen: () => void;
}) {
  const items = [
    { label: "Coverage", value: completeness.coverage_pct != null ? `${completeness.coverage_pct}%` : "—" },
    { label: "Available", value: `${completeness.available}/${completeness.expected}` },
    { label: "Reported", value: String(completeness.reported) },
    { label: "Calculated", value: String(completeness.calculated) },
    { label: "Derived", value: String(completeness.derived) },
    { label: "Unavailable", value: String(completeness.unavailable) },
    { label: "Sources", value: String(sourceCount) },
  ];
  return (
    <button
      onClick={onOpen}
      className="block w-full border-y border-ink/15 py-4 text-left transition-colors hover:bg-paper-2/40"
      aria-label="Open research coverage details"
    >
      <div className="flex items-stretch justify-between">
        {items.map((item) => (
          <div key={item.label} className="flex-1 text-center">
            <div className="font-mono text-xl font-bold text-ink tabular">{item.value}</div>
            <div className="mt-0.5 font-mono text-[10px] font-semibold tracking-[0.12em] text-ink-3 uppercase">
              {item.label}
            </div>
          </div>
        ))}
      </div>
    </button>
  );
}

/**
 * Metric grid used across tabs (growth, profitability, ratios…).
 *
 * Thin India binding over the shared grid — kept as a named export so region
 * call sites read as India code and can diverge without touching the page.
 */
export function IndiaMetricGrid({
  metrics,
  onInspect,
}: {
  metrics: IndiaDashboardPayload["valuation"]["metrics"];
  onInspect?: (metricId: string) => void;
}) {
  return <MetricGrid metrics={metrics} onInspect={onInspect} />;
}

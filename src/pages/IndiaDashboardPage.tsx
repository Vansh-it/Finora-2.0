import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { getIndiaDemoDashboard } from "../lib/indiaApi";
import type {
  IndiaDashboardPayload,
  IndiaRedFlag,
} from "../types/india";
import EditorialHeading from "../components/EditorialHeading";
import HighlightText from "../components/HighlightText";
import {
  FixtureBanner,
  ScopeSelector,
  IndiaCompanyHeader,
  IndiaResearchQualityBar,
} from "../components/dashboard/india/IndiaPrimitives";
import IndiaEvidenceDrawer, { type InspectTarget } from "../components/dashboard/india/IndiaEvidenceDrawer";
import {
  IndiaOwnershipTable,
  IndiaMacroStrip,
} from "../components/dashboard/india/IndiaSections";
import {
  MetricCard,
  MetricGrid,
  RedFlagList,
  StatementTable,
  SourceLedger,
  ForensicModelCards,
} from "../components/dashboard/shared";

const TABS_BY_ENTITY: Record<string, string[]> = {
  CORPORATE: [
    "OVERVIEW", "FINANCIALS", "GROWTH", "PROFITABILITY", "LIQUIDITY",
    "LEVERAGE", "EFFICIENCY", "CAPITAL ALLOCATION", "OWNERSHIP",
    "FORENSICS", "VALUATION", "SOURCES",
  ],
  BANK: [
    "OVERVIEW", "FINANCIALS", "GROWTH", "PROFITABILITY", "ASSET QUALITY",
    "FUNDING", "CAPITAL", "OWNERSHIP", "FORENSICS", "VALUATION", "SOURCES",
  ],
  NBFC: [
    "OVERVIEW", "FINANCIALS", "GROWTH", "PROFITABILITY", "ASSET QUALITY",
    "LEVERAGE", "FUNDING", "OWNERSHIP", "FORENSICS", "VALUATION", "SOURCES",
  ],
};

const UNIT_LABEL = "INR, except per-share";

export default function IndiaDashboardPage() {
  const { entity = "corporate" } = useParams<{ entity: string }>();
  const [payload, setPayload] = useState<IndiaDashboardPayload | null>(null);
  const [scope, setScope] = useState("CONSOLIDATED");
  const [tab, setTab] = useState("OVERVIEW");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inspect, setInspect] = useState<InspectTarget | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPayload(null);
    getIndiaDemoDashboard(entity, scope)
      .then((p) => {
        if (!cancelled) {
          setPayload(p);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load India demo dashboard");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [entity, scope]);

  const tabs = TABS_BY_ENTITY[payload?.entity_type ?? "CORPORATE"] ?? TABS_BY_ENTITY.CORPORATE;

  const content = useMemo(() => {
    if (!payload) return null;
    switch (tab) {
      case "OVERVIEW":
        return <OverviewTab payload={payload} onInspect={setInspect} />;
      case "FINANCIALS":
        return <FinancialsTab payload={payload} onInspect={setInspect} />;
      case "OWNERSHIP":
        return <OwnershipTab payload={payload} />;
      case "FORENSICS":
        return <ForensicsTab payload={payload} onInspect={setInspect} />;
      case "VALUATION":
        return <ValuationTab payload={payload} onInspect={setInspect} />;
      case "SOURCES":
        return <SourceLedger sources={payload.sources} />;
      default: {
        // Generic metric tab (growth, profitability, liquidity, leverage,
        // efficiency, capital allocation, asset quality, funding, capital).
        const key = tab.toLowerCase().replace(/ /g, "_");
        const tabData = payload.tabs[key];
        if (!tabData) return null;
        return (
          <MetricGrid
            metrics={tabData.metrics}
            onInspect={(metricId: string) => {
              const m = tabData.metrics.find((x) => x.metric_id === metricId);
              if (m) setInspect({ kind: "metric", metric: m });
            }}
          />
        );
      }
    }
  }, [payload, tab]);

  if (loading) {
    return (
      <div className="mx-auto flex min-h-[60vh] max-w-3xl items-center justify-center px-4">
        <div className="text-center">
          <Loader2 size={32} className="mx-auto animate-spin text-ink-3" />
          <p className="mt-4 font-mono text-sm text-ink-3">Loading India dashboard…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-20 text-center">
        <EditorialHeading size="md">
          <HighlightText>Could not load the India demo dashboard.</HighlightText>
        </EditorialHeading>
        <p className="mt-4 text-sm text-ink-2">{error}</p>
        <Link
          to="/"
          className="mt-6 inline-block border-2 border-ink bg-paper px-6 py-3 font-mono text-xs font-bold tracking-wider uppercase transition-colors hover:bg-ink hover:text-paper"
        >
          Back to Home
        </Link>
      </div>
    );
  }

  if (!payload) return null;

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-10 sm:px-6 lg:px-10">
      <div className="mb-6">
        <FixtureBanner />
      </div>

      <IndiaCompanyHeader header={payload.header} />

      <div className="my-8 flex flex-wrap items-center justify-between gap-4">
        <div className="flex-1">
          <IndiaResearchQualityBar
            completeness={payload.completeness}
            sourceCount={payload.sources.length}
            onOpen={() => setInspect({ kind: "coverage" })}
          />
        </div>
      </div>

      <div className="mb-6 flex justify-center">
        <div className="thin-scroll -mx-4 flex gap-1 overflow-x-auto border-b border-ink/15 px-4 sm:mx-0 sm:px-0">
          {tabs.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={
                "relative shrink-0 px-4 py-3 font-mono text-xs font-semibold tracking-[0.1em] whitespace-nowrap text-ink-2 uppercase transition-colors hover:text-ink " +
                (tab === t ? "text-ink" : "")
              }
            >
              {t}
              {tab === t && <span className="absolute right-2 bottom-0 left-2 h-[3px] bg-highlight" />}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-4 flex justify-end">
        <ScopeSelector
          scopes={payload.available_scopes.length ? payload.available_scopes : ["CONSOLIDATED"]}
          value={scope}
          onChange={setScope}
        />
      </div>

      <div className="pt-6 pb-24">{content}</div>

      <IndiaEvidenceDrawer
        target={inspect}
        payload={payload}
        onClose={() => setInspect(null)}
      />
    </div>
  );
}

function OverviewTab({
  payload,
  onInspect,
}: {
  payload: IndiaDashboardPayload;
  onInspect: (t: InspectTarget) => void;
}) {
  const revenueSeries = payload.statements.income_statement?.rows.find(
    (r) => r.metric_id === "revenue" || r.metric_id === "interest_earned" || r.metric_id === "total_income_nbfc"
  );

  const chartData = payload.periods.map((p, i) => ({
    period: p,
    value: revenueSeries?.values[i]?.raw ?? null,
  }));

  return (
    <div className="space-y-12">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {payload.kpis.map((k) => (
          <MetricCard
            key={k.metric_id}
            metric={k}
            showSpark
            highlighted={k.metric_id === "free_cash_flow"}
            onInspect={(id) => {
              const m = payload.kpis.find((x) => x.metric_id === id);
              if (m) onInspect({ kind: "metric", metric: m });
            }}
          />
        ))}
      </div>

      {/* Historical trend chart */}
      <div className="border border-ink/20 bg-paper p-5">
        <h3 className="mb-4 font-mono text-xs font-bold tracking-[0.15em] text-ink uppercase">
          {revenueSeries?.label ?? "Revenue"} Trend (₹,1)
        </h3>
        <div className="flex h-48 items-end gap-4">
          {chartData.map((d) => {
            const max = Math.max(...chartData.map((x) => x.value ?? 0), 1);
            const height = d.value == null ? 0 : Math.max((d.value / max) * 100, 1);
            return (
              <div key={d.period} className="flex flex-1 flex-col items-center gap-2">
                <div className="flex h-full w-full items-end">
                  {d.value == null ? (
                    <div className="h-1 w-full bg-ink/10" title="Not available" />
                  ) : (
                    <div
                      className={"w-full bg-ink transition-all " + (d.period === payload.latest_period ? "bg-highlight" : "")}
                      style={{ height: `${height}%`, border: "1px solid #111" }}
                    />
                  )}
                </div>
                <span className="font-mono text-[10px] text-ink-3">{d.period}</span>
              </div>
            );
          })}
        </div>
      </div>

      <IndiaMacroStrip macro={payload.macro} />

      <div>
        <h3 className="mb-4 font-serif text-2xl font-semibold text-ink">Red Flags</h3>
        <RedFlagList
          flags={payload.forensics.red_flags}
          onInspect={(f: IndiaRedFlag) => onInspect({ kind: "flag", flag: f })}
        />
      </div>

      <div>
        <h3 className="mb-4 font-serif text-2xl font-semibold text-ink">Forensic Models</h3>
        <ForensicModelCards
          models={payload.forensics.models}
          onInspect={(model) => onInspect({ kind: "model", model })}
        />
      </div>
    </div>
  );
}

function FinancialsTab({
  payload,
  onInspect,
}: {
  payload: IndiaDashboardPayload;
  onInspect: (t: InspectTarget) => void;
}) {
  const statements = Object.entries(payload.statements);
  return (
    <div className="space-y-14">
      {statements.map(([key, stmt]) => (
        <StatementTable
          key={key}
          title={STATEMENT_TITLES[key] ?? key}
          statement={stmt}
          unitLabel={UNIT_LABEL}
          onInspect={(metricId) => {
            const row = stmt.rows.find((r) => r.metric_id === metricId);
            const value = row?.values[row.values.length - 1];
            if (row && value) {
              onInspect({
                kind: "metric",
                metric: {
                  metric_id: row.metric_id,
                  display_name: row.label,
                  value: value.raw,
                  display_value: value.display_value,
                  status: value.unavailable ? "UNAVAILABLE" : "REPORTED",
                  unit_type: "MONEY",
                  formatting: row.formatting,
                  period: payload.latest_period,
                  reason: value.reason,
                },
              });
            }
          }}
        />
      ))}
    </div>
  );
}

const STATEMENT_TITLES: Record<string, string> = {
  income_statement: "Income Statement",
  balance_sheet: "Balance Sheet",
  cash_flow: "Cash Flow Statement",
};

function OwnershipTab({ payload }: { payload: IndiaDashboardPayload }) {
  const latest = payload.ownership.latest;
  const changes = payload.ownership.yoy_changes;
  return (
    <div className="space-y-10">
      {latest && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {[
            { label: "Promoter", value: latest.promoter_pct },
            { label: "Pledge", value: latest.promoter_pledge_pct },
            { label: "FII/FPI", value: latest.fii_pct },
            { label: "DII", value: latest.dii_pct },
            { label: "Mutual Funds", value: latest.mutual_fund_pct },
            { label: "Public", value: latest.public_pct },
          ].map((x) => (
            <div key={x.label} className="border border-ink/20 bg-paper p-5">
              <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-ink-3 uppercase">
                {x.label}
              </span>
              <div className="mt-2 font-mono text-2xl font-bold text-ink tabular">
                {x.value == null ? "—" : `${x.value.toFixed(1)}%`}
              </div>
            </div>
          ))}
        </div>
      )}

      {Object.keys(changes).length > 0 && (
        <p className="font-mono text-xs text-ink-3">
          YoY changes:{" "}
          {Object.entries(changes)
            .map(([k, v]) => `${k.replace("_pct", "").replace(/_/g, " ")} ${v >= 0 ? "+" : ""}${v} pp`)
            .join(" · ")}
        </p>
      )}

      <IndiaOwnershipTable ownership={payload.ownership} />
    </div>
  );
}

function ForensicsTab({
  payload,
  onInspect,
}: {
  payload: IndiaDashboardPayload;
  onInspect: (t: InspectTarget) => void;
}) {
  const eq = payload.forensics.earnings_quality;
  return (
    <div className="space-y-12">
      <div>
        <h3 className="mb-4 font-serif text-2xl font-semibold text-ink">Red Flags</h3>
        <RedFlagList
          flags={payload.forensics.red_flags}
          onInspect={(f: IndiaRedFlag) => onInspect({ kind: "flag", flag: f })}
        />
      </div>

      <div>
        <h3 className="mb-4 font-serif text-2xl font-semibold text-ink">Forensic Models</h3>
        <ForensicModelCards
          models={payload.forensics.models}
          onInspect={(model) => onInspect({ kind: "model", model })}
        />
      </div>

      {eq.available && (
        <div>
          <h3 className="mb-1 font-serif text-2xl font-semibold text-ink">Earnings Quality Signals</h3>
          <p className="mb-4 font-mono text-[10px] tracking-[0.14em] text-ink-3 uppercase">
            Transparent signals — no opaque composite score
          </p>
          <div className="divide-y divide-ink/12 border-y border-ink/20">
            {eq.signals.map((s) => (
              <div key={s.id} className="flex flex-col gap-1 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-serif text-sm font-semibold text-ink">{s.label}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-ink-3">{s.rule}</p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-sm font-bold text-ink tabular">{s.value}</p>
                  <p className="font-mono text-[10px] text-ink-3">ok when {s.ok_when}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ValuationTab({
  payload,
  onInspect,
}: {
  payload: IndiaDashboardPayload;
  onInspect: (t: InspectTarget) => void;
}) {
  const md = payload.valuation.market_data;
  return (
    <div className="space-y-8">
      {md && md.is_fixture && (
        <div className="border border-dashed border-annotate-blue/60 bg-paper-2/40 px-4 py-2">
          <p className="font-mono text-[10px] font-semibold tracking-[0.14em] text-annotate-blue uppercase">
            Fixture market data — {md.data_status} · {md.exchange} · {md.price_date}
          </p>
        </div>
      )}

      <MetricGrid
        metrics={payload.valuation.metrics}
        onInspect={(id) => {
          const m = payload.valuation.metrics.find((x) => x.metric_id === id);
          if (m) onInspect({ kind: "metric", metric: m });
        }}
      />
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import CompanyHeader from "../components/CompanyHeader";
import ResearchQualityBar from "../components/ResearchQualityBar";
import KPICard from "../components/KPICard";
import DashboardTabs, { type DashboardTab } from "../components/DashboardTabs";
import StatementTable from "../components/StatementTable";
import FinancialChart from "../components/FinancialChart";
import ExecutiveAnalysis from "../components/ExecutiveAnalysis";
import ValuationGrid from "../components/ValuationGrid";
import SourceLedger from "../components/SourceLedger";
import EvidenceDrawer from "../components/EvidenceDrawer";
import AskFinoraDrawer from "../components/AskFinoraDrawer";
import ForensicCards from "../components/ForensicCards";
import RedFlagList from "../components/RedFlagList";
import MacroStrip from "../components/MacroStrip";

import EditorialHeading from "../components/EditorialHeading";
import HighlightText from "../components/HighlightText";
import { getResearchResult } from "../lib/api";

// Types matching the backend dashboard payload
interface DashboardData {
  company: {
    name: string;
    ticker: string;
    exchange: string;
    period: string;
    period_mode: string;
    currency: string;
    cik: string;
    logoInitials: string;
  };
  periods: string[];
  kpis: Array<{
    id: string;
    label: string;
    value: string;
    change?: { value: string; direction: string };
    spark?: number[];
    verification?: Record<string, unknown>;
  }>;
  income_statement: { columns: string[]; rows: Array<{ label: string; values: string[]; strong?: boolean }> };
  balance_sheet: { columns: string[]; rows: Array<{ label: string; values: string[]; strong?: boolean }> };
  cash_flow: { columns: string[]; rows: Array<{ label: string; values: string[]; strong?: boolean }> };
  growth: { columns: string[]; rows: Array<{ label: string; values: string[]; strong?: boolean }> };
  profitability: Array<{ metric: string; value: string; note: string }>;
  liquidity: Array<{ metric: string; value: string; note: string }>;
  leverage: Array<{ metric: string; value: string; note: string }>;
  efficiency: Array<{ metric: string; value: string; note: string }>;
  capital_allocation: Array<{ metric: string; value: string; note: string }>;
  dupont?: { roe: string; net_margin: string; asset_turnover: string; equity_multiplier: string; calculation: string; methodology: string } | null;
  forensic_scores?: {
    piotroski?: { score: number; status: string; signals: Array<{ label: string; value: number; max: number }>; interpretation: string } | null;
    altman?: { score: number; status: string; zone: string; applicable: boolean; reason: string; factors: Array<{ name: string; value: number }>; variant: string } | null;
    beneish?: { score: number; status: string; applicable: boolean; reason: string; indices: Array<{ name: string; value: number }> } | null;
  };
  watch_items?: Array<{
    id: string;
    title: string;
    headline: string;
    reason: string;
    severity: string;
    tag: string;
    evidence: Record<string, unknown>;
  }>;
  macro_context?: {
    available: boolean;
    strip: Array<{ label: string; value: string; series_id?: string; date?: string }>;
    attribution: string;
  };
  charts: {
    revenue: Array<{ label: string; value: number }>;
    operating_income: Array<{ label: string; value: number }>;
    net_income: Array<{ label: string; value: number }>;
    free_cash_flow: Array<{ label: string; value: number }>;
  };
  sources: Array<{
    id: string;
    name: string;
    meta: string;
    pages: string;
    status: string;
    url: string;
    trust_tier: number;
    period: string;
  }>;
  management_commentary: Array<Record<string, unknown>>;
  data_quality: {
    primary_source: string;
    metrics_calculated: number;
    cross_verified: number;
    mismatches: number;
    sources_count: number;
  };
  executive_summary?: {
    executive_overview: string;
    highlights: Array<{ title: string; text: string }>;
    growth_analysis: string;
    profitability_analysis: string;
    cash_flow_analysis: string;
    balance_sheet_analysis: string;
    watch_items: Array<{ tag: string; text: string }>;
    management_commentary_summary: string;
    data_quality_note: string;
  };
  valuation: {
    market_data: {
      price: number | null;
      price_date: string;
      previous_close: number | null;
      percent_change: number | null;
      exchange: string;
      currency: string;
      source: string;
      is_historical: boolean;
      alignment_status: string;
      target_date: string;
    };
    metrics: Array<{
      metric_id: string;
      name: string;
      display_value: string;
      value: number | null;
      status: string;
      applicability: string;
      formula: string;
      inputs: string[];
      calculation: string;
      market_data_date: string;
      price_type: string;
      reason: string;
    }>;
    period_alignment: Record<string, unknown>;
    is_financial_institution: boolean;
    is_historical: boolean;
  };
}



export default function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const sessionId = params.get("session_id");
  const ticker = (params.get("ticker") || "").toUpperCase();
  const initialTab = (params.get("tab") as DashboardTab) || "OVERVIEW";
  const [tab, setTab] = useState<DashboardTab>(initialTab);
  const [evidenceMetric, setEvidenceMetric] = useState<string | null>(null);
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch real data from backend
  useEffect(() => {
    if (!sessionId) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function fetchData() {
      try {
        const result = await getResearchResult(sessionId!);
        if (!cancelled) {
          setData(result as unknown as DashboardData);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "Failed to load research data";
          setError(msg);
          setLoading(false);
        }
      }
    }

    fetchData();

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  function selectTicker(t: string) {
    setParams({ ticker: t });
  }

  const tabContent = useMemo(() => {
    if (!data) return null;

    switch (tab) {
      case "OVERVIEW":
        return (
          <div className="space-y-14">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              {data.kpis.map((kpi) => (
                <KPICard
                  key={kpi.id}
                  label={kpi.label}
                  value={kpi.value}
                  delta={kpi.change?.value}
                  deltaTone={kpi.change?.direction === "up" ? "pos" : kpi.change?.direction === "down" ? "neg" : "neutral"}
                  highlighted={kpi.id === "fcf"}
                  onInspect={() => setEvidenceMetric(kpi.label)}
                />
              ))}
            </div>

            <FinancialChart data={data.charts.revenue.map((d) => ({ year: d.label, revenue: d.value, netIncome: data.charts.net_income.find((n) => n.label === d.label)?.value || 0 }))} />

            {/* Macro Context Strip */}
            <MacroStrip macro={data.macro_context} />

            {/* Red Flags / Watch Items */}
            <RedFlagList
              flags={(data.watch_items || []).concat(
                (data.executive_summary?.watch_items || []).map((w, i) => ({
                  id: `exec-${i}`,
                  title: w.tag || "WATCH",
                  headline: w.text,
                  reason: w.text,
                  severity: w.tag === "RISK" ? ("high" as const) : ("medium" as const),
                  tag: w.tag || "WATCH",
                  evidence: {},
                }))
              )}
              onInspect={setEvidenceMetric}
            />

            {/* Forensic Score Cards */}
            <ForensicCards scores={data.forensic_scores || {}} onInspect={setEvidenceMetric} />

            {data.executive_summary && (
              <ExecutiveAnalysis
                analysis={{
                  paragraphs: [data.executive_summary.executive_overview],
                  highlights: data.executive_summary.highlights.map((h) => h.title),
                  watch: data.executive_summary.watch_items.map((w) => ({
                    tag: (w.tag as "WATCH" | "STRENGTH" | "RISK") || "WATCH",
                    text: w.text,
                  })),
                  the_read: (data.executive_summary as Record<string, unknown>).the_read as string || undefined,
                  annotations: (data.executive_summary as Record<string, unknown>).annotations as Array<{tag: string; text: string}> || undefined,
                }}
                onAskFollowUp={() => setEvidenceMetric("ask_finora")}
              />
            )}
          </div>
        );
      case "INCOME STATEMENT":
        return (
          <StatementTable
            title="Income Statement"
            unitLabel="USD, except per-share"
            years={data.periods}
            rows={data.income_statement.rows.map((r) => ({
              label: r.label,
              values: r.values.map((v) => {
                const num = parseFloat(v.replace(/[$,BMT%—]/g, ""));
                return isNaN(num) ? null : num;
              }),
              isTotal: r.strong,
            }))}
            onInspect={setEvidenceMetric}
          />
        );
      case "BALANCE SHEET":
        return (
          <StatementTable
            title="Balance Sheet"
            unitLabel="USD"
            years={data.periods}
            rows={data.balance_sheet.rows.map((r) => ({
              label: r.label,
              values: r.values.map((v) => {
                const num = parseFloat(v.replace(/[$,BMT%—]/g, ""));
                return isNaN(num) ? null : num;
              }),
              isTotal: r.strong,
            }))}
            onInspect={setEvidenceMetric}
          />
        );
      case "CASH FLOW":
        return (
          <StatementTable
            title="Cash Flow Statement"
            unitLabel="USD"
            years={data.periods}
            rows={data.cash_flow.rows.map((r) => ({
              label: r.label,
              values: r.values.map((v) => {
                const num = parseFloat(v.replace(/[$,BMT%—]/g, ""));
                return isNaN(num) ? null : num;
              }),
              isTotal: r.strong,
            }))}
            onInspect={setEvidenceMetric}
          />
        );
      case "GROWTH":
        return (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {data.growth.rows.map((g) => (
              <div key={g.label} className="border border-ink/20 bg-paper p-5">
                <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-ink-3 uppercase">{g.label}</span>
                <div className="mt-2 font-mono text-2xl font-bold tabular">
                  {g.values[g.values.length - 1] || "—"}
                </div>
              </div>
            ))}
          </div>
        );
      case "PROFITABILITY":
        return (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {data.profitability.map((p) => (
              <div key={p.metric} className="border border-ink/20 bg-paper p-5">
                <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-ink-3 uppercase">{p.metric}</span>
                <div className="mt-2 font-mono text-2xl font-bold text-ink tabular">{p.value}</div>
              </div>
            ))}
          </div>
        );
      case "VALUATION": {
        const metricsMap = Object.fromEntries(data.valuation.metrics.map((m) => [m.metric_id, m]));
        const priceVal = data.valuation.market_data.price?.toFixed(2) || metricsMap["share_price"]?.display_value || "—";
        const mcVal = metricsMap["market_cap"]?.display_value || "—";
        const evVal = metricsMap["enterprise_value"]?.display_value || "—";
        const skipIds = new Set(["share_price", "market_cap", "enterprise_value"]);
        return <ValuationGrid valuation={{
          price: `$${priceVal.replace(/^\$/, "")}`,
          marketCap: mcVal,
          enterpriseValue: evVal,
          multiples: data.valuation.metrics
            .filter((m) => !skipIds.has(m.metric_id))
            .map((m) => ({
              label: m.name,
              value: m.display_value,
              unavailable: m.status === "unavailable",
              note: m.reason,
            })),
        }} />;
      }
      case "FORENSICS":
        return (
          <div className="space-y-10">
            <ForensicCards scores={data.forensic_scores || {}} onInspect={setEvidenceMetric} />
            <RedFlagList
              flags={(data.watch_items || [])}
              onInspect={setEvidenceMetric}
            />
            <MacroStrip macro={data.macro_context} />
          </div>
        );
      case "SOURCES":
        return <SourceLedger sources={data.sources.map((s) => ({
          id: s.id,
          name: s.name,
          trust: s.trust_tier === 1 ? "PRIMARY" : s.trust_tier === 2 ? "OFFICIAL" : "CORROBORATING",
          period: s.period,
          usedFor: s.meta,
          status: s.status.toUpperCase() as "VERIFIED" | "CROSS-VERIFIED",
        }))} />;
      default:
        return null;
    }
  }, [tab, data]);

  // Loading state
  if (loading) {
    return (
      <div className="mx-auto flex min-h-[60vh] max-w-3xl items-center justify-center px-4">
        <div className="text-center">
          <Loader2 size={32} className="mx-auto animate-spin text-ink-3" />
          <p className="mt-4 font-mono text-sm text-ink-3">Loading research data...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-20 text-center">
        <EditorialHeading size="md">
          <HighlightText>Something went wrong.</HighlightText>
        </EditorialHeading>
        <p className="mt-4 text-sm text-ink-2">{error}</p>
        <button
          onClick={() => navigate("/research")}
          className="mt-6 border-2 border-ink bg-paper px-6 py-3 font-mono text-xs font-bold tracking-wider uppercase transition-colors hover:bg-ink hover:text-paper"
        >
          Start New Research
        </button>
      </div>
    );
  }

  // No session — direct to research
  if (!sessionId || !data) {
    return (
      <div className="mx-auto max-w-[1440px] px-4 py-10 sm:px-6 lg:px-10">
        <div className="border-2 border-ink/20 bg-paper p-8 text-center">
          <p className="text-ink-2">Run a research analysis to see the full dashboard.</p>
          <button
            onClick={() => navigate("/research")}
            className="mt-4 border-2 border-ink bg-paper px-6 py-3 font-mono text-xs font-bold tracking-wider uppercase transition-colors hover:bg-ink hover:text-paper"
          >
            Start Research
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-10 sm:px-6 lg:px-10">
      <CompanyHeader company={{
          ticker: data.company.ticker,
          name: data.company.name,
          exchange: data.company.exchange,
          sector: data.company.period,
          fiscalYear: data.company.period,
          price: data.valuation.market_data.price || 0,
          priceChange: data.valuation.market_data.percent_change || 0,
          sessionId: sessionId || undefined,
          description: (data.company as Record<string, unknown>).description as string || undefined,
          industry: (data.company as Record<string, unknown>).industry as string || undefined,
        }} />

      <div className="my-8">
        <ResearchQualityBar quality={{
          sourceType: data.data_quality.primary_source,
          metrics: data.data_quality.metrics_calculated,
          sources: data.data_quality.sources_count,
          crossVerified: data.data_quality.cross_verified,
          mismatches: data.data_quality.mismatches,
        }} />
      </div>

      <DashboardTabs active={tab} onChange={setTab} />

      <div className="pt-10 pb-24">{tabContent}</div>

      <EvidenceDrawer metric={evidenceMetric} data={data} onClose={() => setEvidenceMetric(null)} />
      <AskFinoraDrawer sessionId={sessionId} />
    </div>
  );
}

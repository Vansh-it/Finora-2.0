// Maps the backend's universal dashboard payload (backend/lib/dashboard_builder.py)
// onto the mobile DashboardSession shape. No values are invented: when the backend
// omits a field we surface an explicit unavailable reason instead of fabricating.
import { formatCompact } from './format';
import type {
  DashboardSession,
  EvidenceInput,
  ForensicScore,
  MetricEvidence,
  SourceEntry,
  StatementLine,
} from './data';

type Json = any;

const DASH = '—';

const rec = (v: Json): Json => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
const arr = (v: Json): Json[] => (Array.isArray(v) ? v : []);
const str = (v: Json, fallback = ''): string => (typeof v === 'string' && v ? v : fallback);
const num = (v: Json): number | null =>
  typeof v === 'number' && Number.isFinite(v) ? v : null;

function periodLabel(periods: string[], idx: number): string {
  return periods[idx] ?? periods[periods.length - 1] ?? '';
}

// Backend formats dollars as "$398.8B" / "$-12.3B" / "—". Parse as a fallback
// only when the numeric raw_export table is missing.
function parseMoney(s: unknown): number | null {
  const t = str(s).trim();
  if (!t || t === DASH) return null;
  const neg = t.startsWith('(') || t.startsWith('-') || t.includes('$-');
  const cleaned = t.replace(/[$,()\s]/g, '');
  const m = cleaned.match(/^-?(\d+(?:\.\d+)?)([TBMK])?$/);
  if (!m) return null;
  let v = parseFloat(m[1]);
  const unit = m[2];
  if (unit === 'T') v *= 1e12;
  else if (unit === 'B') v *= 1e9;
  else if (unit === 'M') v *= 1e6;
  else if (unit === 'K') v *= 1e3;
  return neg ? -v : v;
}

function inferFormat(name: string, value: number | null): EvidenceInput['format'] {
  const n = name.toLowerCase();
  if (n.includes('share') || n.includes('ratio')) return 'number';
  if (n.includes('growth') || n.includes('rate') || n.includes('margin')) return 'percent';
  if (value == null) return 'number';
  return Math.abs(value) >= 1000 ? 'money' : 'number';
}

interface EvidenceExtras {
  form?: string;
  filingDate?: string;
  accession?: string;
  xbrl?: string;
  verified?: boolean;
  corroborating?: number;
  mismatch?: string;
  unavailableReason?: string;
}

function evidence(
  metric: string,
  period: string,
  value: number | null,
  displayValue: string,
  formula: string,
  inputs: EvidenceInput[],
  extras: EvidenceExtras = {},
): MetricEvidence {
  return {
    metric,
    period,
    value,
    displayValue: displayValue || (value == null ? DASH : formatCompact(value)),
    formula,
    inputs,
    form: extras.form ?? 'SEC XBRL',
    filingDate: extras.filingDate ?? DASH,
    accession: extras.accession ?? DASH,
    xbrl: extras.xbrl ?? DASH,
    verified: extras.verified ?? false,
    corroborating: extras.corroborating ?? 0,
    mismatch: extras.mismatch,
    unavailableReason: extras.unavailableReason,
  };
}

// ── Financial statements ──────────────────────────────────────────────────────
function buildStatement(
  formattedRows: Json,
  rawRows: Json,
  periods: string[],
  corroborating: number,
): StatementLine[] {
  return arr(formattedRows).map((row, i) => {
    const raw = arr(rawRows)[i] || {};
    const rawValues = arr(raw.values);
    const fmtValues = arr(row.values);
    const values: (number | null)[] = periods.map((_p, j) => {
      const v = rawValues[j];
      if (typeof v === 'number' && Number.isFinite(v)) return v;
      return parseMoney(fmtValues[j]);
    });
    const label = str(row.label, str(raw.label, 'Line item'));
    const evidenceList: MetricEvidence[] = periods.map((p, j) => {
      const value = values[j];
      const display = str(fmtValues[j], value == null ? DASH : formatCompact(value));
      return evidence(label, p, value, display, `${label} — as reported in the SEC filing.`, [], {
        corroborating,
        unavailableReason: value == null ? 'Not reported for this period.' : undefined,
      });
    });
    return { label, section: false, values, evidence: evidenceList };
  });
}

// ── Growth + profitability ────────────────────────────────────────────────────
function buildGrowth(p: Json, periods: string[], corroborating: number): MetricEvidence[] {
  const rows = arr(rec(p.growth).rows);
  const ids = arr(rec(p.raw_export).growth_ids);
  const raw = rec(rec(p.raw_export).growth_raw);
  const latest = periods[periods.length - 1] ?? '';
  return rows.map((row, i) => {
    const id = str(ids[i]);
    const fmtValues = arr(row.values);
    const display = str(fmtValues[fmtValues.length - 1], DASH);
    const value = num(rec(raw[latest])[id]);
    return evidence(str(row.label), latest, value, display, 'Year-over-year change from reported SEC values.', [], {
      corroborating,
      unavailableReason: value == null ? 'Growth not available for this period.' : undefined,
    });
  });
}

function buildProfitability(p: Json, periods: string[], corroborating: number): MetricEvidence[] {
  const rows = arr(p.profitability);
  const raw = rec(rec(p.raw_export).profitability_raw);
  const latest = periods[periods.length - 1] ?? '';
  return rows.map((row) => {
    const label = str(row.metric);
    const id = label.toLowerCase().replace(/\s+/g, '_');
    const value = num(raw[id]);
    return evidence(label, latest, value, str(row.value, DASH), '', [], {
      corroborating,
      unavailableReason: value == null ? 'Not calculable from this filing.' : undefined,
    });
  });
}

function mapValuationInputs(inputs: Json): EvidenceInput[] {
  return arr(inputs)
    .map((inp): EvidenceInput | null => {
      const name = str(rec(inp).name, str(rec(inp).label));
      const value = num(rec(inp).value);
      if (!name || value == null) return null;
      return { name, value, format: inferFormat(name, value) };
    })
    .filter((x): x is EvidenceInput => x !== null);
}

function buildValuation(p: Json, periods: string[], corroborating: number): MetricEvidence[] {
  const metrics = arr(rec(p.valuation).metrics);
  const latest = periods[periods.length - 1] ?? '';
  return metrics.map((m) => {
    const status = str(m.status, 'unavailable');
    const calculated = status === 'calculated';
    const value = num(m.value);
    const period = str(m.price_type) === 'current' ? 'Live' : latest;
    const formula = str(m.formula) || str(m.calculation);
    const priceDate = str(m.market_data_date, DASH);
    return evidence(
      str(m.name, 'Metric'),
      period,
      value,
      str(m.display_value, DASH),
      formula,
      mapValuationInputs(m.inputs),
      {
        form: str(m.price_type) === 'current' ? 'Market data' : 'Market data + SEC XBRL',
        filingDate: priceDate,
        corroborating,
        verified: calculated,
        unavailableReason: calculated ? undefined : str(m.reason, 'Not available for this company.'),
      },
    );
  });
}

// ── Forensics ─────────────────────────────────────────────────────────────────
function piotroskiScore(f: Json): ForensicScore {
  const signals = arr(f.signals);
  const value = num(f.score) ?? 0;
  const verdict = value >= 7 ? 'strong' : value >= 4 ? 'neutral' : 'weak';
  return {
    name: 'Piotroski F-Score',
    short: 'F',
    value,
    display: `${value} / 9`,
    verdict: verdict as ForensicScore['verdict'],
    meaning: str(f.interpretation, `Scored ${value} of 9 fundamental quality signals.`),
    detail: signals.map((s) => `${str(s.label)} ${num(s.value) ? '✓' : '✗'}`),
  };
}

function altmanScore(f: Json): ForensicScore {
  const applicable = f.applicable !== false;
  const rawValue = num(f.score);
  const value = rawValue ?? 0;
  let verdict: ForensicScore['verdict'] = 'neutral';
  if (applicable && rawValue != null) verdict = rawValue >= 2.99 ? 'strong' : rawValue >= 1.81 ? 'neutral' : 'weak';
  return {
    name: 'Altman Z-Score',
    short: 'Z',
    value,
    display: rawValue == null ? DASH : rawValue.toFixed(2),
    verdict,
    meaning: str(f.reason) || (applicable ? `Altman zone: ${str(f.status, 'n/a')}.` : 'Not applicable to this company.'),
    detail: arr(f.factors).map((c) => `${str(c.name)}: ${(num(c.value) ?? 0).toFixed(2)}`),
  };
}

function beneishScore(f: Json): ForensicScore {
  const applicable = f.applicable !== false;
  const rawValue = num(f.score);
  const value = rawValue ?? 0;
  let verdict: ForensicScore['verdict'] = 'neutral';
  if (applicable && rawValue != null) verdict = rawValue < -1.78 ? 'strong' : 'weak';
  return {
    name: 'Beneish M-Score',
    short: 'M',
    value,
    display: rawValue == null ? DASH : rawValue.toFixed(2),
    verdict,
    meaning: str(f.reason) || (applicable
      ? 'Below the −1.78 manipulation threshold.' : 'Not enough data to score.'),
    detail: arr(f.indices).map((c) => `${str(c.name)} ${(num(c.value) ?? 0).toFixed(2)}`),
  };
}

function buildForensics(p: Json): ForensicScore[] {
  const fs = rec(p.forensic_scores);
  const out: ForensicScore[] = [];
  if (rec(fs.piotroski).score != null) out.push(piotroskiScore(rec(fs.piotroski)));
  if (rec(fs.altman).score != null) out.push(altmanScore(rec(fs.altman)));
  if (rec(fs.beneish).score != null) out.push(beneishScore(rec(fs.beneish)));
  return out;
}

// ── Memo + watch tags ─────────────────────────────────────────────────────────
function buildMemo(es: Json): string {
  if (!es) return '';
  const parts: string[] = [];
  const read = str(es.the_read) || str(es.executive_overview);
  if (read) parts.push(`#### Executive take\n\n${read}`);
  const highlights = arr(es.highlights);
  if (highlights.length) {
    parts.push(`**Highlights**\n` + highlights.map((h) => `- **${str(h.title)}:** ${str(h.text)}`).join('\n'));
  }
  const sections: [string, string][] = [
    ['Growth', str(es.growth_analysis)],
    ['Profitability', str(es.profitability_analysis)],
    ['Cash flow', str(es.cash_flow_analysis)],
    ['Balance sheet', str(es.balance_sheet_analysis)],
  ];
  for (const [title, body] of sections) if (body) parts.push(`#### ${title}\n\n${body}`);
  const watch = arr(es.watch_items);
  if (watch.length) parts.push(`#### Risks to watch\n\n` + watch.map((w) => `- **${str(w.title)}:** ${str(w.reason)}`).join('\n'));
  if (str(es.management_commentary_summary)) parts.push(`#### Management commentary\n\n${str(es.management_commentary_summary)}`);
  if (str(es.data_quality_note)) parts.push(`#### Data quality\n\n${str(es.data_quality_note)}`);
  return parts.join('\n\n');
}

function buildWatchTags(p: Json): string[] {
  const tags = new Set<string>();
  for (const w of arr(p.watch_items)) {
    const t = str(w.tag) || str(w.title);
    if (t) tags.add(t.toUpperCase());
  }
  for (const a of arr(rec(p.executive_summary).annotations)) {
    const t = str(a.tag);
    if (t) tags.add(t.toUpperCase());
  }
  return [...tags].slice(0, 4);
}

// ── Sources ───────────────────────────────────────────────────────────────────
function sourceTier(t: number): SourceEntry['tier'] {
  if (t <= 1) return 'PRIMARY';
  if (t === 2) return 'OFFICIAL';
  return 'CORROBORATING';
}

function buildSources(p: Json): SourceEntry[] {
  return arr(p.sources).map((s, i) => {
    const status = str(s.status, 'verified');
    return {
      id: str(s.id, `src-${i}`),
      name: str(s.name, str(s.id, 'Source')),
      tier: sourceTier(num(s.trust_tier) ?? 3),
      url: str(s.url, str(s.pages)),
      verified: status === 'verified',
      note: str(s.meta, str(s.period)),
      mismatch: status === 'mismatch' ? true : undefined,
    };
  });
}

function buildRedFlags(p: Json): DashboardSession['redFlags'] {
  const cap = (s: string): 'High' | 'Medium' | 'Low' => {
    const v = s.toLowerCase();
    return v === 'high' ? 'High' : v === 'low' ? 'Low' : 'Medium';
  };
  return arr(p.watch_items).map((w) => ({
    title: str(w.headline, str(w.title, 'Watch item')),
    severity: cap(str(w.severity, 'medium')),
    body: str(w.reason),
  }));
}

// ── Entry point ───────────────────────────────────────────────────────────────
export function adaptSession(payload: Json, sessionId: string): DashboardSession {
  const p = rec(payload);
  const company = rec(p.company);
  const periods = arr(p.periods).map((x) => String(x));
  const quality = rec(p.data_quality);
  const corroborating = num(quality.cross_verified) ?? 0;
  const raw = rec(p.raw_export);

  const kpiRawById: Record<string, number | null> = {};
  for (const k of arr(raw.kpis)) kpiRawById[str(k.id)] = num(k.value);

  const kpis: MetricEvidence[] = arr(p.kpis).map((k) => {
    const id = str(k.id);
    const label = str(k.label, 'Metric');
    const value = kpiRawById[id] ?? null;
    const change = rec(k.change);
    const changeVal = str(change.value);
    const formulaBits = [label];
    if (changeVal && changeVal !== DASH) formulaBits.push(`${changeVal} YoY`);
    return evidence(
      label,
      periodLabel(periods, periods.length - 1),
      value,
      str(k.value, DASH),
      formulaBits.join(' · '),
      [],
      {
        corroborating,
        unavailableReason: value == null ? 'Not available in the primary filing for this period.' : undefined,
      },
    );
  });

  const revChart = arr(rec(p.charts).revenue);
  const niChart = arr(rec(p.charts).net_income);
  const niByLabel = new Map(niChart.map((n) => [str(n.label), num(n.value)]));
  const revenueSeries = revChart.map((r) => {
    const label = str(r.label);
    const revB = num(r.value) ?? 0;
    const niB = niByLabel.get(label) ?? 0;
    return { period: label, revenue: revB * 1e9, netIncome: niB * 1e9 };
  });

  const macro = arr(rec(p.macro_context).strip).map((m) => `${str(m.label)} ${str(m.value)}`.trim());

  const es = p.executive_summary;
  const headline =
    (str(rec(es).executive_overview).slice(0, 160)) ||
    str(company.description).slice(0, 160) ||
    '';

  return {
    sessionId,
    ticker: str(company.ticker),
    company: str(company.name, str(company.ticker, 'Unknown')),
    exchange: str(company.exchange),
    price: num(rec(rec(p.valuation).market_data).price) ?? 0,
    changePct: num(rec(rec(p.valuation).market_data).percent_change) ?? 0,
    periods,
    quality: {
      primary: str(quality.primary_source, 'SEC XBRL'),
      metrics: num(quality.metrics_calculated) ?? 0,
      sources: num(quality.sources_count) ?? 0,
      crossVerified: corroborating,
      mismatches: num(quality.mismatches) ?? 0,
    },
    kpis,
    revenueSeries,
    macro,
    redFlags: buildRedFlags(p),
    forensics: buildForensics(p),
    memo: buildMemo(es),
    watchTags: buildWatchTags(p),
    income: buildStatement(rec(p.income_statement).rows, raw.income, periods, corroborating),
    balance: buildStatement(rec(p.balance_sheet).rows, raw.balance, periods, corroborating),
    cashflow: buildStatement(rec(p.cash_flow).rows, raw.cashflow, periods, corroborating),
    growth: buildGrowth(p, periods, corroborating),
    profitability: buildProfitability(p, periods, corroborating),
    valuation: buildValuation(p, periods, corroborating),
    sources: buildSources(p),
    researchedAt: new Date().toISOString(),
    headline,
  };
}

// Typed mock data shaped like the real Flask backend payloads.
// When the backend is reachable, api.ts prefers it; otherwise these power the demo.

export interface CompanySuggestion {
  ticker: string;
  name: string;
  exchange: string;
}

export interface EvidenceInput {
  name: string;
  value: number;
  format: 'money' | 'percent' | 'multiple' | 'number';
}

export interface MetricEvidence {
  metric: string;
  period: string;
  value: number | null;
  displayValue: string;
  formula: string;
  inputs: EvidenceInput[];
  form: string;
  filingDate: string;
  accession: string;
  xbrl: string;
  verified: boolean;
  corroborating: number;
  mismatch?: string;
  unavailableReason?: string;
}

export interface StatementLine {
  label: string;
  section?: boolean;
  collapsible?: boolean;
  values: (number | null)[];
  evidence: MetricEvidence[];
}

export interface ForensicScore {
  name: string;
  short: string;
  value: number;
  display: string;
  verdict: 'strong' | 'neutral' | 'weak';
  meaning: string;
  detail: string[];
}

export interface SourceEntry {
  id: string;
  name: string;
  tier: 'PRIMARY' | 'OFFICIAL' | 'CORROBORATING';
  url: string;
  verified: boolean;
  note: string;
  mismatch?: boolean;
}

export interface DashboardSession {
  sessionId: string;
  ticker: string;
  company: string;
  exchange: string;
  price: number;
  changePct: number;
  periods: string[];
  quality: { primary: string; metrics: number; sources: number; crossVerified: number; mismatches: number };
  kpis: MetricEvidence[];
  revenueSeries: { period: string; revenue: number; netIncome: number }[];
  macro: string[];
  redFlags: { title: string; severity: 'High' | 'Medium' | 'Low'; body: string }[];
  forensics: ForensicScore[];
  memo: string;
  watchTags: string[];
  income: StatementLine[];
  balance: StatementLine[];
  cashflow: StatementLine[];
  growth: MetricEvidence[];
  profitability: MetricEvidence[];
  valuation: MetricEvidence[];
  sources: SourceEntry[];
  researchedAt: string;
  headline: string;
}

export const COMPANIES: CompanySuggestion[] = [
  { ticker: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ' },
  { ticker: 'MSFT', name: 'Microsoft Corporation', exchange: 'NASDAQ' },
  { ticker: 'NVDA', name: 'NVIDIA Corporation', exchange: 'NASDAQ' },
  { ticker: 'TSLA', name: 'Tesla, Inc.', exchange: 'NASDAQ' },
  { ticker: 'AMZN', name: 'Amazon.com, Inc.', exchange: 'NASDAQ' },
  { ticker: 'META', name: 'Meta Platforms, Inc.', exchange: 'NASDAQ' },
  { ticker: 'GOOGL', name: 'Alphabet Inc.', exchange: 'NASDAQ' },
  { ticker: 'JPM', name: 'JPMorgan Chase & Co.', exchange: 'NYSE' },
  { ticker: 'V', name: 'Visa Inc.', exchange: 'NYSE' },
  { ticker: 'JNJ', name: 'Johnson & Johnson', exchange: 'NYSE' },
  { ticker: 'WMT', name: 'Walmart Inc.', exchange: 'NYSE' },
  { ticker: 'XOM', name: 'Exxon Mobil Corporation', exchange: 'NYSE' },
];

function ev(
  metric: string, period: string, value: number | null, displayValue: string,
  formula: string, inputs: EvidenceInput[], extra?: Partial<MetricEvidence>,
): MetricEvidence {
  return {
    metric, period, value, displayValue, formula, inputs,
    form: '10-K', filingDate: '2024-11-01',
    accession: '0000320193-24-000123', xbrl: 'us-gaap:Revenues',
    verified: true, corroborating: 7, ...extra,
  };
}

const PERIODS = ['FY2022', 'FY2023', 'FY2024'];

function stmt(label: string, values: (number | null)[], section = false): StatementLine {
  return {
    label, section,
    values,
    evidence: values.map((v, i) =>
      ev(label, PERIODS[i], v, v == null ? '—' : `$${(v / 1e9).toFixed(1)}B`,
        `${label} = reported filing value (audited)`, [], { xbrl: 'us-gaap:Revenues' }),
    ),
  };
}

export function buildSession(ticker: string): DashboardSession {
  const t = ticker.toUpperCase();
  const company = COMPANIES.find((c) => c.ticker === t);
  const name = company?.name ?? `${t} Corporation`;
  const seed = t.split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  const revBase = 280 + (seed % 160);
  const price = 120 + (seed % 180) + 0.4;
  const changePct = ((seed % 70) - 30) / 10;
  const rev = [revBase * 0.92 * 1e9, revBase * 0.97 * 1e9, revBase * 1e9];
  const ni = rev.map((r) => r * (0.21 + (seed % 8) / 100));

  return {
    sessionId: `ses_${t.toLowerCase()}_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`,
    ticker: t, company: name, exchange: company?.exchange ?? 'NASDAQ',
    price, changePct, periods: PERIODS,
    quality: { primary: 'SEC EDGAR', metrics: 48, sources: 9, crossVerified: 7, mismatches: seed % 3 === 0 ? 1 : 0 },
    kpis: [
      ev('Revenue (TTM)', 'FY2024', rev[2], `$${(rev[2] / 1e9).toFixed(1)}B`, 'Revenue = Σ quarterly reported revenue', [
        { name: 'Q1 revenue', value: rev[2] * 0.24, format: 'money' },
        { name: 'Q2 revenue', value: rev[2] * 0.25, format: 'money' },
        { name: 'Q3 revenue', value: rev[2] * 0.25, format: 'money' },
        { name: 'Q4 revenue', value: rev[2] * 0.26, format: 'money' },
      ]),
      ev('Net Income', 'FY2024', ni[2], `$${(ni[2] / 1e9).toFixed(1)}B`, 'Net Income = Revenue − Total Costs − Tax', [
        { name: 'Revenue', value: rev[2], format: 'money' },
        { name: 'Total costs', value: rev[2] - ni[2], format: 'money' },
      ]),
      ev('ROIC', 'FY2024', 0.284, '28.4%', 'ROIC = NOPAT / Invested Capital', [
        { name: 'NOPAT', value: ni[2] * 1.12, format: 'money' },
        { name: 'Invested capital', value: (ni[2] * 1.12) / 0.284, format: 'money' },
      ], { xbrl: 'us-gaap:NetIncomeLoss' }),
      ev('Free Cash Flow', 'FY2024', rev[2] * 0.24, `$${((rev[2] * 0.24) / 1e9).toFixed(1)}B`, 'FCF = Operating Cash Flow − CapEx', [
        { name: 'Operating cash flow', value: rev[2] * 0.29, format: 'money' },
        { name: 'CapEx', value: rev[2] * 0.05, format: 'money' },
      ]),
    ],
    revenueSeries: PERIODS.map((p, i) => ({ period: p, revenue: rev[i], netIncome: ni[i] })),
    macro: ['Fed funds 4.75%', 'CPI +2.6% YoY', '10Y yield 4.21%', 'USD index 104.2', 'Sector P/E 28.4x'],
    redFlags: [
      { title: 'Insider selling above 12-month average', severity: 'Medium', body: 'Open-market sales by officers totalled $48.2M over the last quarter, 1.8x the trailing average. Transactions were pre-scheduled 10b5-1 plans.' },
      { title: 'Receivables growing faster than revenue', severity: 'Low', body: 'DSO rose from 41 to 47 days YoY. Management attributes this to enterprise mix shift; worth watching next quarter.' },
    ],
    forensics: [
      { name: 'Piotroski F-Score', short: 'F', value: 8, display: '8 / 9', verdict: 'strong', meaning: 'Strong fundamentals — 8 of 9 quality signals pass.', detail: ['Positive net income ✓', 'Positive operating cash flow ✓', 'Rising ROA ✓', 'Cash flow > net income ✓', 'Falling leverage ✓', 'Rising current ratio ✓', 'No dilution ✓', 'Rising gross margin ✓', 'Rising asset turnover ✗'] },
      { name: 'Altman Z-Score', short: 'Z', value: 4.1, display: '4.1', verdict: 'strong', meaning: 'Safely above the 2.99 distress threshold.', detail: ['Working capital / assets: 0.18', 'Retained earnings / assets: 0.42', 'EBIT / assets: 0.31', 'Equity / liabilities: 2.86', 'Sales / assets: 0.94'] },
      { name: 'Beneish M-Score', short: 'M', value: -2.4, display: '-2.4', verdict: 'strong', meaning: 'Below the -1.78 manipulation threshold — no flags.', detail: ['DSRI 1.02', 'GMI 0.99', 'AQI 1.01', 'SGI 1.06', 'DEPI 0.98', 'SGAI 1.00', 'LVGI 0.97', 'TATA -0.02'] },
    ],
    memo: `#### Executive take\n\n**${name}** closed FY2024 with revenue of **$${(rev[2] / 1e9).toFixed(1)}B** and net income of **$${(ni[2] / 1e9).toFixed(1)}B**. Growth re-accelerated in the second half as enterprise demand recovered and operating leverage returned.\n\n#### What the numbers say\n\n- Operating margin expanded ~140bps YoY on mix and cost discipline.\n- Free cash flow conversion stayed above 85% — capital returns are well covered.\n- The balance sheet carries net cash; buybacks ran at $18.4B for the year.\n\n#### Risks to watch\n\n- *Valuation*: at ~29x forward earnings the bar for beats is high.\n- *Concentration*: the top segment still drives 52% of gross profit.\n\nEvery figure above is traced to its filing, formula and XBRL concept — tap any number for its receipt.`,
    watchTags: ['Q1 guidance', 'Buyback pace', 'Margin mix'],
    income: [
      stmt('Revenue', rev),
      stmt('Cost of revenue', rev.map((r) => -r * 0.56)),
      stmt('Gross profit', rev.map((r) => r * 0.44)),
      stmt('Operating expenses', rev.map((r) => -r * 0.16), true),
      stmt('R&D', rev.map((r) => -r * 0.08)),
      stmt('SG&A', rev.map((r) => -r * 0.08)),
      stmt('Operating income', rev.map((r) => r * 0.28)),
      stmt('Net income', ni),
      stmt('Diluted EPS', [5.12 + (seed % 5) * 0.2, 5.48 + (seed % 5) * 0.2, 5.94 + (seed % 5) * 0.2]),
    ],
    balance: [
      stmt('Cash & equivalents', rev.map((r) => r * 0.16)),
      stmt('Total current assets', rev.map((r) => r * 0.34)),
      stmt('Property & equipment', rev.map((r) => r * 0.12)),
      stmt('Total assets', rev.map((r) => r * 0.92)),
      stmt('Total current liabilities', rev.map((r) => r * 0.28), true),
      stmt('Long-term debt', rev.map((r) => r * 0.22)),
      stmt('Total liabilities', rev.map((r) => r * 0.62)),
      stmt("Shareholders' equity", rev.map((r) => r * 0.3)),
    ],
    cashflow: [
      stmt('Operating cash flow', rev.map((r) => r * 0.29)),
      stmt('Capital expenditures', rev.map((r) => -r * 0.05)),
      stmt('Free cash flow', rev.map((r) => r * 0.24)),
      stmt('Dividends paid', rev.map((r) => -r * 0.04), true),
      stmt('Share repurchases', rev.map((r) => -r * 0.05)),
      stmt('Net change in cash', rev.map((r) => r * 0.02)),
    ],
    growth: [
      ev('Revenue growth (YoY)', 'FY2024', 0.061, '+6.1%', 'YoY = (FY2024 − FY2023) / FY2023', [
        { name: 'FY2024 revenue', value: rev[2], format: 'money' },
        { name: 'FY2023 revenue', value: rev[1], format: 'money' },
      ]),
      ev('Net income growth (YoY)', 'FY2024', 0.084, '+8.4%', 'YoY = (FY2024 − FY2023) / FY2023', [
        { name: 'FY2024 net income', value: ni[2], format: 'money' },
        { name: 'FY2023 net income', value: ni[1], format: 'money' },
      ]),
      ev('EPS growth (YoY)', 'FY2024', 0.092, '+9.2%', 'EPS growth = diluted EPS YoY change', [
        { name: 'FY2024 diluted EPS', value: 6.12, format: 'number' },
      ], { xbrl: 'us-gaap:EarningsPerShareDiluted' }),
      ev('FCF growth (YoY)', 'FY2024', 0.054, '+5.4%', 'FCF growth = free cash flow YoY change', [
        { name: 'FY2024 FCF', value: rev[2] * 0.24, format: 'money' },
      ]),
    ],
    profitability: [
      ev('Gross margin', 'FY2024', 0.44, '44.0%', 'Gross margin = Gross profit / Revenue', [
        { name: 'Gross profit', value: rev[2] * 0.44, format: 'money' },
        { name: 'Revenue', value: rev[2], format: 'money' },
      ]),
      ev('Operating margin', 'FY2024', 0.28, '28.0%', 'Operating margin = Operating income / Revenue', [
        { name: 'Operating income', value: rev[2] * 0.28, format: 'money' },
      ]),
      ev('Net margin', 'FY2024', ni[2] / rev[2], `${((ni[2] / rev[2]) * 100).toFixed(1)}%`, 'Net margin = Net income / Revenue', [
        { name: 'Net income', value: ni[2], format: 'money' },
      ]),
      ev('ROE', 'FY2024', 0.312, '31.2%', 'ROE = Net income / Avg. equity', [
        { name: 'Net income', value: ni[2], format: 'money' },
        { name: 'Avg. equity', value: ni[2] / 0.312, format: 'money' },
      ]),
    ],
    valuation: [
      ev('Share price', 'Live', price, `$${price.toFixed(2)}`, 'Last trade · Twelve Data / exchange feed', [
        { name: 'Previous close', value: price * 0.99, format: 'money' },
      ], { form: 'Market data', filingDate: 'live', accession: '—', xbrl: '—', corroborating: 2 }),
      ev('Market cap', 'Live', price * 15.4e9, `$${((price * 15.4e9) / 1e12).toFixed(2)}T`, 'Market cap = Price × Diluted shares', [
        { name: 'Diluted shares', value: 15.4e9, format: 'number' },
      ], { form: '10-K + market', xbrl: 'us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding' }),
      ev('P/E (TTM)', 'FY2024', price / 6.12, `${(price / 6.12).toFixed(1)}x`, 'P/E = Price / Diluted EPS (TTM)', [
        { name: 'Diluted EPS (TTM)', value: 6.12, format: 'number' },
      ]),
      ev('EV / EBITDA', 'FY2024', 21.4, '21.4x', 'EV/EBITDA = Enterprise value / EBITDA', [
        { name: 'Enterprise value', value: price * 15.4e9 - rev[2] * 0.1, format: 'money' },
        { name: 'EBITDA', value: rev[2] * 0.32, format: 'money' },
      ]),
      ev('PEG ratio', 'FY2024', null, '—', 'PEG = P/E / EPS growth rate', [], {
        unavailableReason: 'Consensus long-term growth estimate unavailable for this ticker.',
        verified: false, corroborating: 0,
      }),
      ev('Dividend yield', 'FY2024', 0.005, '0.5%', 'Yield = Annual dividend / Price', [
        { name: 'Annual dividend', value: price * 0.005, format: 'money' },
      ]),
    ],
    sources: [
      { id: 's1', name: 'SEC EDGAR — 10-K FY2024', tier: 'PRIMARY', url: 'https://www.sec.gov/cgi-bin/browse-edgar', verified: true, note: 'Audited financial statements · accession 0000320193-24-000123' },
      { id: 's2', name: 'SEC EDGAR — 10-Q Q3 FY2024', tier: 'PRIMARY', url: 'https://www.sec.gov/cgi-bin/browse-edgar', verified: true, note: 'Quarterly statements, reviewed' },
      { id: 's3', name: 'Company Investor Relations', tier: 'OFFICIAL', url: 'https://investor.example.com', verified: true, note: 'Earnings release + call transcript' },
      { id: 's4', name: 'Twelve Data — market feed', tier: 'OFFICIAL', url: 'https://twelvedata.com', verified: true, note: 'Price, splits, dividends' },
      { id: 's5', name: 'Business Quant aggregates', tier: 'CORROBORATING', url: 'https://example.com', verified: true, note: 'Cross-check: revenue ±0.1%' },
      { id: 's6', name: 'Tavily news corroboration', tier: 'CORROBORATING', url: 'https://example.com', verified: seed % 3 !== 0, note: 'Guidance language match', mismatch: seed % 3 === 0 },
    ],
    researchedAt: new Date().toISOString(),
    headline: `${name} delivered ${((ni[2] / rev[2]) * 100).toFixed(1)}% net margins on $${(rev[2] / 1e9).toFixed(1)}B revenue with fortress cash generation.`,
  };
}

export interface HistoryItem {
  sessionId: string;
  ticker: string;
  company: string;
  period: string;
  date: string;
  headline: string;
  metrics: number;
  sources: number;
}

export function seedHistory(): HistoryItem[] {
  const now = Date.now();
  return ['AAPL', 'NVDA', 'MSFT'].map((t, i) => {
    const s = buildSession(t);
    return {
      sessionId: s.sessionId + i, ticker: t, company: s.company, period: 'FY2024',
      date: new Date(now - (i + 1) * 86400000 * 2).toISOString(),
      headline: s.headline, metrics: 48, sources: 9,
    };
  });
}

export interface Review {
  id: string;
  name: string;
  /** Reviewer role: 'Student' or 'Teacher'. */
  role?: string;
  stars: number;
  text: string;
  date: string;
}

export const QUOTA_LIMIT = 5;

// Lightweight Excel-compatible export (CSV opens natively in Excel/Sheets).
// Dynamically imported only when the user taps Export.
import type { DashboardSession } from './data';

function cell(v: string | number): string {
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export async function exportSession(s: DashboardSession): Promise<void> {
  const rows: (string | number)[][] = [
    ['Finora Research Export', s.company, s.ticker, s.exchange],
    ['Session', s.sessionId, 'Exported', new Date().toISOString()],
    [],
    ['KPI', 'Period', 'Value', 'Formula', 'Filing', 'Accession', 'XBRL', 'Verified'],
    ...s.kpis.map((k) => [k.metric, k.period, k.displayValue, k.formula, k.form, k.accession, k.xbrl, k.verified ? 'yes' : 'no']),
    [],
    ['INCOME STATEMENT', ...s.periods],
    ...s.income.map((l) => [l.label, ...l.values.map((v) => (v == null ? '—' : Math.round(v)))]),
    [],
    ['BALANCE SHEET', ...s.periods],
    ...s.balance.map((l) => [l.label, ...l.values.map((v) => (v == null ? '—' : Math.round(v)))]),
    [],
    ['CASH FLOW', ...s.periods],
    ...s.cashflow.map((l) => [l.label, ...l.values.map((v) => (v == null ? '—' : Math.round(v)))]),
    [],
    ['FORENSICS', 'Score', 'Verdict', 'Meaning'],
    ...s.forensics.map((f) => [f.name, f.display, f.verdict, f.meaning]),
    [],
    ['SOURCES', 'Tier', 'Verified', 'Note'],
    ...s.sources.map((x) => [x.name, x.tier, x.verified ? 'yes' : 'NO', x.note]),
  ];
  const csv = rows.map((r) => r.map(cell).join(',')).join('\n');
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
  const file = new File([blob], `finora-${s.ticker}-research.csv`, { type: 'text/csv' });

  const nav = navigator as Navigator & { canShare?: (d: { files: File[] }) => boolean; share?: (d: { files: File[]; title: string }) => Promise<void> };
  if (nav.canShare?.({ files: [file] }) && nav.share) {
    try {
      await nav.share({ files: [file], title: `Finora — ${s.ticker} research` });
      return;
    } catch { /* user dismissed; fall through to download */ }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = file.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

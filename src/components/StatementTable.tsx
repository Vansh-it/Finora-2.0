import { useRef, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, Receipt } from 'lucide-react';
import type { MetricEvidence, StatementLine } from '../lib/data';
import { formatCompact, formatFull } from '../lib/format';
import { SegmentedControl } from './ui';
import { cn } from '../lib/cn';

type View = 'Table' | 'Cards';

export function StatementTable({
  lines, periods, onCell,
}: {
  lines: StatementLine[];
  periods: string[];
  onCell: (e: MetricEvidence) => void;
}) {
  const [view, setView] = useState<View>('Table');
  const [freq, setFreq] = useState<'Annual' | 'Quarterly'>('Annual');
  const [full, setFull] = useState(false);
  const [periodIdx, setPeriodIdx] = useState(periods.length - 1);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [scrolled, setScrolled] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  const fmt = (v: number | null) => {
    if (v == null) return '—';
    if (freq === 'Quarterly') v = v / 4;
    return full ? formatFull(Math.round(v)) : formatCompact(v);
  };

  const visibleLines = lines.filter((l) => {
    if (l.section) return true;
    // collapse lines under a collapsed section header: section header is the previous section line
    return true;
  });

  const toggleSection = (label: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  // group rows under last section header for collapse
  const rows: { line: StatementLine; under: string | null }[] = [];
  let current: string | null = null;
  for (const l of visibleLines) {
    if (l.section) {
      current = l.label;
      rows.push({ line: l, under: null });
    } else {
      rows.push({ line: l, under: current });
    }
  }
  const shown = rows.filter((r) => !r.under || !collapsed.has(r.under));

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <div className="flex-1">
          <SegmentedControl options={['Annual', 'Quarterly'] as const} value={freq} onChange={setFreq} />
        </div>
        <button
          onClick={() => setFull(!full)}
          aria-pressed={full}
          className="pressable min-h-[44px] shrink-0 rounded-xl border border-white/12 bg-white/[0.05] px-3 font-mono text-[11px] font-semibold text-[#ff8a3d]"
        >
          {full ? 'FULL $' : '$B/M'}
        </button>
      </div>
      <div className="mb-3">
        <SegmentedControl options={['Table', 'Cards'] as const} value={view} onChange={setView} />
      </div>

      {view === 'Table' ? (
        <div className="relative">
          <div
            ref={scroller}
            onScroll={(e) => setScrolled((e.target as HTMLElement).scrollLeft > 12)}
            className="overflow-x-auto rounded-2xl border border-white/10 bg-[#101014]"
            style={{ scrollSnapType: 'x proximity' }}
            role="region"
            aria-label="Financial statement table, scroll horizontally for more periods"
            tabIndex={0}
          >
            <table className="w-full border-collapse text-[13px]" style={{ minWidth: 132 + periods.length * 96 }}>
              <thead>
                <tr>
                  <th scope="col" className="sticky-col sticky-head left-0 bg-[#16171c] p-3 text-left font-mono text-[11px] uppercase tracking-wider text-[#a7a29a]" style={{ minWidth: 132, width: 132 }}>
                    Line item
                  </th>
                  {periods.map((p) => (
                    <th key={p} scope="col" className="sticky-head bg-[#16171c] p-3 text-right font-mono text-[11px] uppercase tracking-wider text-[#a7a29a]" style={{ minWidth: 96 }}>
                      {p.replace('FY', 'FY\u2009')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map(({ line }) => (
                  <tr key={line.label} className={cn('border-t border-white/[0.06]', line.section && 'bg-white/[0.02]')}>
                    <th scope="row" className="sticky-col left-0 max-w-[132px] bg-[#121318] p-0 text-left">
                      {line.section ? (
                        <button
                          onClick={() => toggleSection(line.label)}
                          aria-expanded={!collapsed.has(line.label)}
                          className="flex min-h-[48px] w-full items-center justify-between gap-1 px-3 text-left text-[13px] font-bold text-white"
                        >
                          <span className="truncate">{line.label}</span>
                          <ChevronDown size={15} className={cn('shrink-0 text-[#ff8a3d] transition-transform', collapsed.has(line.label) && '-rotate-90')} />
                        </button>
                      ) : (
                        <span className="flex min-h-[48px] items-center truncate px-3 font-medium text-[#d7d3c8]" title={line.label}>
                          {line.label}
                        </span>
                      )}
                    </th>
                    {line.values.map((v, i) => (
                      <td key={i} className="p-0 text-right">
                        <button
                          onClick={() => line.evidence[i] && onCell(line.evidence[i])}
                          aria-label={`${line.label}, ${periods[i]}: ${fmt(v)}. Open evidence.`}
                          className="num min-h-[48px] w-full px-3 text-[13px] active:bg-[#ff5a1f]/10"
                          style={{ color: v == null ? '#6b675c' : v < 0 ? '#f87171' : '#f5f3ee', fontWeight: line.section ? 700 : 500 }}
                        >
                          {fmt(v)}
                        </button>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!scrolled && (
            <div aria-hidden className="pointer-events-none absolute inset-y-0 right-0 w-10 rounded-r-2xl bg-gradient-to-l from-[#ff5a1f]/25 to-transparent" />
          )}
          <p className="mt-2 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-[#6b675c]">
            <Receipt size={12} className="text-[#ff8a3d]" /> Tap any figure for its receipt
          </p>
        </div>
      ) : (
        <div>
          <div className="mb-3 flex items-center justify-between rounded-2xl border border-white/10 bg-[#101014] p-1.5">
            <button
              aria-label="Previous period"
              disabled={periodIdx === 0}
              onClick={() => setPeriodIdx((i) => Math.max(0, i - 1))}
              className="pressable flex h-11 w-11 items-center justify-center rounded-xl text-white disabled:opacity-30"
            >
              <ChevronLeft size={20} />
            </button>
            <p className="font-display text-[15px] font-semibold text-white" aria-live="polite">{periods[periodIdx]}</p>
            <button
              aria-label="Next period"
              disabled={periodIdx === periods.length - 1}
              onClick={() => setPeriodIdx((i) => Math.min(periods.length - 1, i + 1))}
              className="pressable flex h-11 w-11 items-center justify-center rounded-xl text-white disabled:opacity-30"
            >
              <ChevronRight size={20} />
            </button>
          </div>
          <div
            className="overflow-hidden rounded-2xl border border-white/10"
            onTouchStart={(e) => { (e.currentTarget as HTMLElement).dataset.x = String(e.touches[0].clientX); }}
            onTouchEnd={(e) => {
              const x0 = Number((e.currentTarget as HTMLElement).dataset.x ?? 0);
              const dx = e.changedTouches[0].clientX - x0;
              if (Math.abs(dx) > 48) setPeriodIdx((i) => Math.min(periods.length - 1, Math.max(0, i + (dx < 0 ? 1 : -1))));
            }}
          >
            {lines.filter((l) => !l.section).map((l) => {
              const v = l.values[periodIdx];
              return (
                <button
                  key={l.label}
                  onClick={() => l.evidence[periodIdx] && onCell(l.evidence[periodIdx])}
                  className="pressable flex min-h-[52px] w-full items-center justify-between gap-3 border-b border-white/[0.06] bg-[#121318] px-4 text-left last:border-0 active:bg-[#ff5a1f]/[0.07]"
                >
                  <span className="truncate text-[14px] text-[#d7d3c8]">{l.label}</span>
                  <span className="num shrink-0 text-[14px] font-semibold" style={{ color: v == null ? '#6b675c' : v < 0 ? '#f87171' : '#fff' }}>
                    {fmt(v)}
                  </span>
                </button>
              );
            })}
          </div>
          <p className="mt-2 text-center font-mono text-[10px] uppercase tracking-[0.1em] text-[#6b675c]">Swipe card sideways to change period</p>
        </div>
      )}
    </div>
  );
}

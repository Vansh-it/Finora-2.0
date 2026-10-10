import { Suspense, lazy, useMemo, useState } from 'react';
import { formatCompact } from '../lib/format';
import { Skeleton } from './ui';

// Lazy recharts so the initial bundle stays lean.
const LazyCharts = lazy(() => import('./RechartsBundle'));

export function RevenueChart({ data }: { data: { period: string; revenue: number; netIncome: number }[] }) {
  const [sel, setSel] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const current = sel != null ? data[sel] : data[data.length - 1];

  const summary = useMemo(() => {
    const first = data[0];
    const last = data[data.length - 1];
    const g = ((last.revenue - first.revenue) / first.revenue) * 100;
    return `Revenue grew ${g.toFixed(1)}% from ${first.period} to ${last.period}; net income tracked at ~${((last.netIncome / last.revenue) * 100).toFixed(0)}% margin.`;
  }, [data]);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between rounded-xl border border-white/10 bg-black/40 px-3 py-2" aria-live="polite">
        <span className="font-mono text-[11px] uppercase tracking-wider text-[#a7a29a]">{current.period} · tap bars</span>
        <span className="num text-[13px] text-white">
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#ff5a1f]" />{formatCompact(current.revenue)}
          {'  '}
          <span className="ml-2 mr-1 inline-block h-2 w-2 rounded-full bg-[#a7a29a]" />{formatCompact(current.netIncome)}
        </span>
      </div>
      <Suspense fallback={<Skeleton className="h-[220px] w-full" />}>
        <LazyCharts data={data} onSelect={setSel} selected={sel} />
      </Suspense>
      <p className="sr-only">{summary}</p>
      <button
        onClick={() => setShowTable(!showTable)}
        aria-expanded={showTable}
        className="pressable mt-2 min-h-[44px] w-full rounded-xl border border-white/10 bg-white/[0.03] text-[13px] font-medium text-[#a7a29a]"
      >
        {showTable ? 'Hide data table' : 'View data table'}
      </button>
      {showTable && (
        <table className="mt-2 w-full overflow-hidden rounded-xl border border-white/10 text-[13px]">
          <thead>
            <tr className="bg-white/[0.04] text-left font-mono text-[11px] uppercase text-[#a7a29a]">
              <th scope="col" className="p-2.5">Period</th>
              <th scope="col" className="p-2.5 text-right">Revenue</th>
              <th scope="col" className="p-2.5 text-right">Net income</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.period} className="border-t border-white/[0.06]">
                <th scope="row" className="p-2.5 text-left font-medium text-[#d7d3c8]">{d.period}</th>
                <td className="num p-2.5 text-right text-white">{formatCompact(d.revenue)}</td>
                <td className="num p-2.5 text-right text-white">{formatCompact(d.netIncome)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// Lightweight inline sparkline (no recharts needed)
export function Sparkline({ values, width = 76, height = 28, positive }: { values: number[]; width?: number; height?: number; positive?: boolean }) {
  const pts = useMemo(() => {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    return values.map((v, i) => {
      const x = (i / (values.length - 1)) * (width - 4) + 2;
      const y = height - 3 - ((v - min) / span) * (height - 6);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
  }, [values, width, height]);
  const up = positive ?? values[values.length - 1] >= values[0];
  const color = up ? '#34d399' : '#f87171';
  return (
    <svg width={width} height={height} aria-hidden className="shrink-0">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={Number(pts.split(' ').pop()!.split(',')[0])} cy={Number(pts.split(' ').pop()!.split(',')[1])} r={2.6} fill={color} />
    </svg>
  );
}

export function TrendChart({ values, labels }: { values: number[]; labels: string[] }) {
  void labels;
  const max = Math.max(...values.map(Math.abs));
  return (
    <div className="flex h-[120px] items-end gap-2" role="img" aria-label="Trend chart">
      {values.map((v, i) => (
        <div key={i} className="flex flex-1 flex-col items-center gap-1">
          <div
            className="w-full rounded-t-lg bg-gradient-to-t from-[#ff5a1f]/40 to-[#ff8a3d]"
            style={{ height: `${Math.max(8, (Math.abs(v) / max) * 96)}px`, animation: `bar-grow .5s ${i * 0.06}s ease-out both`, transformOrigin: 'bottom' }}
          />
        </div>
      ))}
    </div>
  );
}

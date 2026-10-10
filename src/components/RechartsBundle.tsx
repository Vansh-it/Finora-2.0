import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import { formatCompact } from '../lib/format';

export default function RechartsBundle({ data, onSelect, selected }: {
  data: { period: string; revenue: number; netIncome: number }[];
  onSelect: (i: number) => void;
  selected: number | null;
}) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  return (
    <div style={{ height: 220 }} role="img" aria-label="Revenue versus net income bar chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} barGap={5} onClick={(s) => { if (s?.activeTooltipIndex != null) onSelect(Number(s.activeTooltipIndex)); }}>
          <CartesianGrid stroke="rgba(255,255,255,0.07)" vertical={false} />
          <XAxis dataKey="period" tick={{ fill: '#a7a29a', fontSize: 11 }} axisLine={false} tickLine={false} interval={0} />
          <YAxis tickFormatter={(v: number) => formatCompact(v)} tick={{ fill: '#6b675c', fontSize: 10 }} axisLine={false} tickLine={false} width={52} />
          <Bar dataKey="revenue" name="Revenue" radius={[6, 6, 0, 0]} isAnimationActive={!reduced} onClick={(_, i) => onSelect(Number(i))}>
            {data.map((_, i) => (
              <Cell key={i} fill={selected == null || selected === i ? '#ff5a1f' : 'rgba(255,90,31,0.3)'} />
            ))}
          </Bar>
          <Bar dataKey="netIncome" name="Net income" radius={[6, 6, 0, 0]} isAnimationActive={!reduced} onClick={(_, i) => onSelect(Number(i))}>
            {data.map((_, i) => (
              <Cell key={i} fill={selected == null || selected === i ? '#d7d3c8' : 'rgba(215,211,200,0.3)'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

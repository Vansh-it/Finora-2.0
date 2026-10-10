import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import {
  ArrowDownRight, ArrowUpRight, BadgeCheck, ChevronDown, Copy, Download,
  ExternalLink, FileSpreadsheet, MessageSquare, Share2, Star, TriangleAlert,
} from 'lucide-react';
import { getSession } from '../lib/api';
import type { DashboardSession, MetricEvidence } from '../lib/data';
import { toggleWatch, getWatchlist } from '../lib/api';
import { formatPercent } from '../lib/format';
import { StatementTable } from '../components/StatementTable';
import { EvidenceSheet } from '../components/EvidenceSheet';
import { AskFinoraSheet } from '../components/AskFinoraSheet';
import { PullToRefresh } from '../components/PullToRefresh';
import { RevenueChart, Sparkline, TrendChart } from '../components/Charts';
import { EmptyState, ErrorState, ProgressBar, Skeleton, SourceStamp, TickerChip, TierBadge, UnavailableMetric } from '../components/ui';
import { useCachedQuery, useCountUp } from '../hooks/hooks';
import { useToast } from '../hooks/toast';
import { cn } from '../lib/cn';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'income', label: 'Income' },
  { id: 'balance', label: 'Balance' },
  { id: 'cashflow', label: 'Cash Flow' },
  { id: 'growth', label: 'Growth' },
  { id: 'profit', label: 'Profit' },
  { id: 'valuation', label: 'Valuation' },
  { id: 'forensics', label: 'Forensics' },
  { id: 'sources', label: 'Sources' },
] as const;
type TabId = (typeof TABS)[number]['id'];

// ---------------- Top actions (rendered in App shell) ----------------
export function DashboardTopActions() {
  const [params] = useSearchParams();
  const sessionId = params.get('session_id') ?? '';
  const toast = useToast();
  const [watched, setWatched] = useState(false);
  const [ticker, setTicker] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    getSession(sessionId).then(
      (s) => {
        setTicker(s.ticker);
        setWatched(getWatchlist().includes(s.ticker));
      },
      () => {},
    );
  }, [sessionId]);

  if (!sessionId) return null;

  const doExport = async () => {
    setBusy(true);
    toast('Preparing Excel export…', 'info');
    try {
      const mod = await import('../lib/excelExport');
      const s = await getSession(sessionId);
      await mod.exportSession(s);
      toast('Export ready', 'ok');
    } catch {
      toast('Export failed — try again', 'warn');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-1">
      <button
        aria-label={watched ? `Remove ${ticker} from watchlist` : `Add ${ticker} to watchlist`}
        aria-pressed={watched}
        onClick={() => {
          if (!ticker) return;
          const next = toggleWatch(ticker);
          setWatched(next.includes(ticker));
          toast(next.includes(ticker) ? `${ticker} added to watchlist` : `${ticker} removed`, 'ok');
        }}
        className="pressable flex h-11 w-11 items-center justify-center rounded-xl text-white"
      >
        <Star size={20} className={watched ? 'fill-[#ffb25c] text-[#ffb25c]' : ''} />
      </button>
      <button
        aria-label="Export to Excel"
        onClick={doExport}
        disabled={busy}
        className="pressable flex h-11 w-11 items-center justify-center rounded-xl text-white disabled:opacity-50"
      >
        <FileSpreadsheet size={20} />
      </button>
    </div>
  );
}

// ---------------- Page ----------------
export function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const sessionId = params.get('session_id') ?? '';
  const tabParam = params.get('tab') as TabId | null;
  const active: TabId = TABS.some((t) => t.id === tabParam) ? (tabParam as TabId) : 'overview';

  const query = useCachedQuery<DashboardSession>(
    `session:${sessionId}`,
    async (signal) => { void signal; return getSession(sessionId); },
    { enabled: Boolean(sessionId), ttlMs: 120_000 },
  );

  const [evidence, setEvidence] = useState<MetricEvidence | null>(null);
  const [askOpen, setAskOpen] = useState(false);
  const [compact, setCompact] = useState(false);
  const lastY = useRef(0);

  useEffect(() => {
    const main = document.querySelector('.app-main');
    if (!main) return;
    const onScroll = () => {
      const y = (main as HTMLElement).scrollTop;
      if (y > 160 && y > lastY.current) setCompact(true);
      else if (y < lastY.current - 8 || y < 60) setCompact(false);
      lastY.current = y;
    };
    main.addEventListener('scroll', onScroll, { passive: true });
    return () => main.removeEventListener('scroll', onScroll);
  }, []);

  const setTab = (t: TabId) => {
    const next = new URLSearchParams(params);
    next.set('tab', t);
    setParams(next, { replace: true });
  };

  if (!sessionId) {
    return (
      <div className="px-5 pt-10">
        <EmptyState
          title="No session open"
          body="Research a company to open its dashboard, or pick up where you left off."
          action={<Link to="/history" className="btn-primary pressable flex min-h-[52px] items-center justify-center rounded-2xl font-display text-[15px] font-semibold text-white">Open History</Link>}
        />
      </div>
    );
  }

  if (query.loading && !query.data) {
    return (
      <div className="space-y-3 px-5 pt-5" aria-label="Loading dashboard">
        <Skeleton className="h-[92px] w-full" />
        <div className="flex gap-2">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-9 w-20 shrink-0" />)}</div>
        <Skeleton className="h-11 w-full" />
        <div className="grid grid-cols-2 gap-3"><Skeleton className="h-[110px]" /><Skeleton className="h-[110px]" /></div>
        <Skeleton className="h-[240px] w-full" />
      </div>
    );
  }

  if (query.error && !query.data) {
    return (
      <div className="px-5 pt-6">
        <ErrorState message="Couldn't load this research file. It may have expired." onRetry={() => { void query.refetch(); }} />
        <Link to="/history" className="pressable mt-2 flex min-h-[52px] items-center justify-center rounded-2xl border border-white/15 bg-white/[0.06] font-display text-[15px] font-semibold text-white">Back to History</Link>
      </div>
    );
  }

  const s = query.data!;
  const mismatchFilter = params.get('filter') === 'mismatch';

  return (
    <div className="pb-28">
      <CompanyHeader session={s} compact={compact} />
      <QualityBar session={s} onMismatch={() => { setTab('sources'); }} />
      <TabStrip active={active} onChange={setTab} />

      <PullToRefresh onRefresh={() => query.refetch()}>
        <SwipeArea
          active={active}
          onChange={setTab}
          content={
            <div key={active} className="anim-fade px-5 pt-4" role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
              {active === 'overview' && <OverviewTab s={s} onEvidence={setEvidence} />}
              {active === 'income' && <StatementTable lines={s.income} periods={s.periods} onCell={setEvidence} />}
              {active === 'balance' && <StatementTable lines={s.balance} periods={s.periods} onCell={setEvidence} />}
              {active === 'cashflow' && <StatementTable lines={s.cashflow} periods={s.periods} onCell={setEvidence} />}
              {active === 'growth' && <MetricList metrics={s.growth} onEvidence={setEvidence} />}
              {active === 'profit' && <MetricList metrics={s.profitability} onEvidence={setEvidence} />}
              {active === 'valuation' && <ValuationTab s={s} onEvidence={setEvidence} />}
              {active === 'forensics' && <ForensicsTab s={s} />}
              {active === 'sources' && <SourcesTab s={s} mismatchOnly={mismatchFilter} />}
            </div>
          }
        />
      </PullToRefresh>

      <button
        onClick={() => setAskOpen(true)}
        className="btn-primary pressable fixed bottom-[92px] z-40 flex min-h-[52px] items-center gap-2 rounded-2xl px-5 font-display text-[15px] font-semibold text-white"
        style={{ right: 'max(16px, calc(50% - 215px + 16px))' }}
        aria-haspopup="dialog"
      >
        <MessageSquare size={18} /> Ask Finora
      </button>

      <EvidenceSheet evidence={evidence} onClose={() => setEvidence(null)} />
      <AskFinoraSheet open={askOpen} onClose={() => setAskOpen(false)} ticker={s.ticker} sessionId={s.sessionId} />
    </div>
  );
}

// ---------------- header ----------------
function CompanyHeader({ session: s, compact }: { session: DashboardSession; compact: boolean }) {
  const toast = useToast();
  const up = s.changePct >= 0;
  const animated = useCountUp(s.price, 800, !compact);

  if (compact) {
    return (
      <div className="anim-fade sticky top-0 z-30 flex min-h-[44px] items-center gap-2 border-b border-white/10 bg-[#0a0a0c]/95 px-5 backdrop-blur">
        <TickerChip ticker={s.ticker} />
        <span className="num text-[14px] font-semibold text-white">${s.price.toFixed(2)}</span>
        <span className={cn('num flex items-center text-[12px] font-semibold', up ? 'text-[#34d399]' : 'text-[#f87171]')}>
          {up ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}{formatPercent(s.changePct)}
        </span>
      </div>
    );
  }

  return (
    <div className="grid-glow border-b border-white/10 px-5 pb-4 pt-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <TickerChip ticker={s.ticker} />
            <span className="font-mono text-[11px] text-[#6b675c]">{s.exchange}</span>
          </div>
          <h1 className="mt-1.5 line-clamp-2 font-display text-[24px] font-bold leading-[28px] tracking-tight text-white">{s.company}</h1>
        </div>
        <SourceStamp />
      </div>
      <div className="mt-2.5 flex items-end gap-2">
        <p className="num text-[32px] font-semibold leading-none text-white">${animated.toFixed(2)}</p>
        <p className={cn('num mb-0.5 flex items-center gap-0.5 text-[14px] font-semibold', up ? 'text-[#34d399]' : 'text-[#f87171]')}>
          {up ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}{formatPercent(s.changePct)}
        </p>
      </div>
      <button
        onClick={async () => { try { await navigator.clipboard.writeText(s.sessionId); toast('Session ID copied'); } catch { toast('Copy unavailable', 'warn'); } }}
        className="pressable mt-2 flex min-h-[44px] items-center gap-1.5 font-mono text-[11px] text-[#6b675c]"
        aria-label={`Session ${s.sessionId}. Tap to copy.`}
      >
        <Copy size={12} /> {s.sessionId.slice(0, 24)}…
      </button>
    </div>
  );
}

// ---------------- quality bar ----------------
function QualityBar({ session: s, onMismatch }: { session: DashboardSession; onMismatch: () => void }) {
  const q = s.quality;
  const pills = [
    { label: q.primary, sub: 'primary', icon: BadgeCheck },
    { label: `${q.metrics}`, sub: 'metrics', icon: null },
    { label: `${q.sources}`, sub: 'sources', icon: null },
    { label: `${q.crossVerified}`, sub: 'verified', icon: null },
  ];
  return (
    <div className="snap-row border-b border-white/10 px-5 py-3" role="list" aria-label="Research quality">
      {pills.map((p) => (
        <span key={p.sub} role="listitem" className="flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-full border border-white/12 bg-white/[0.04] px-3.5">
          {p.icon && <p.icon size={14} className="text-[#34d399]" />}
          <span className="num text-[13px] font-semibold text-white">{p.label}</span>
          <span className="font-mono text-[10px] uppercase text-[#6b675c]">{p.sub}</span>
        </span>
      ))}
      <span role="listitem" className="flex shrink-0">
        {q.mismatches > 0 ? (
          <button
            onClick={onMismatch}
            aria-label={`${q.mismatches} mismatches. View sources.`}
            className="pressable flex min-h-[44px] items-center gap-1.5 rounded-full border border-[#fbbf24]/50 bg-[#fbbf24]/10 px-3.5"
          >
            <TriangleAlert size={14} className="text-[#fbbf24]" />
            <span className="num text-[13px] font-semibold text-[#fbbf24]">{q.mismatches}</span>
            <span className="font-mono text-[10px] uppercase text-[#6b675c]">mismatch</span>
          </button>
        ) : (
          <span className="flex min-h-[44px] items-center gap-1.5 rounded-full border border-white/12 bg-white/[0.04] px-3.5" aria-label="No mismatches">
            <span className="num text-[13px] font-semibold text-white">{q.mismatches}</span>
            <span className="font-mono text-[10px] uppercase text-[#6b675c]">mismatch</span>
          </span>
        )}
      </span>
    </div>
  );
}

// ---------------- tab strip ----------------
function TabStrip({ active, onChange }: { active: TabId; onChange: (t: TabId) => void }) {
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = strip.current?.querySelector<HTMLElement>(`#tab-${active}`);
    el?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
  }, [active]);

  return (
    <div ref={strip} role="tablist" aria-label="Dashboard sections"
      className="tab-strip sticky top-0 z-30 flex gap-1.5 overflow-x-auto border-b border-white/10 bg-[#0a0a0c]/95 px-4 py-2.5 backdrop-blur">
      {TABS.map((t) => {
        const sel = t.id === active;
        return (
          <button
            key={t.id} id={`tab-${t.id}`} role="tab" aria-selected={sel} aria-controls={`panel-${t.id}`}
            tabIndex={sel ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => {
              const i = TABS.findIndex((x) => x.id === active);
              if (e.key === 'ArrowRight') onChange(TABS[(i + 1) % TABS.length].id);
              if (e.key === 'ArrowLeft') onChange(TABS[(i - 1 + TABS.length) % TABS.length].id);
            }}
            className={cn(
              'pressable min-h-[44px] shrink-0 snap-start rounded-xl px-3.5 font-mono text-[12px] font-semibold uppercase tracking-wider transition-colors',
              sel ? 'bg-[#ff5a1f] text-white shadow-[0_4px_16px_rgba(255,90,31,0.4)]' : 'text-[#a7a29a] active:bg-white/5',
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

// ---------------- swipe area ----------------
function SwipeArea({ active, onChange, content }: { active: TabId; onChange: (t: TabId) => void; content: React.ReactNode }) {
  const x0 = useRef<number | null>(null);
  return (
    <div
      onTouchStart={(e) => {
        const t = e.target as HTMLElement;
        if (t.closest('table, .snap-row, [data-noswipe], a, button')) { x0.current = null; return; }
        x0.current = e.touches[0].clientX;
      }}
      onTouchEnd={(e) => {
        if (x0.current == null) return;
        const dx = e.changedTouches[0].clientX - x0.current;
        x0.current = null;
        if (Math.abs(dx) < 64) return;
        const i = TABS.findIndex((x) => x.id === active);
        const next = dx < 0 ? i + 1 : i - 1;
        if (next >= 0 && next < TABS.length) onChange(TABS[next].id);
      }}
    >
      {content}
    </div>
  );
}

// ---------------- OVERVIEW ----------------
function OverviewTab({ s, onEvidence }: { s: DashboardSession; onEvidence: (e: MetricEvidence) => void }) {
  const [flagsOpen, setFlagsOpen] = useState<number | null>(null);
  const [memoOpen, setMemoOpen] = useState(false);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {s.kpis.map((k, i) => (
          <button
            key={k.metric}
            onClick={() => onEvidence(k)}
            className="card-dark pressable p-3.5 text-left anim-rise"
            style={{ animationDelay: `${i * 0.06}s` }}
            aria-label={`${k.metric}: ${k.displayValue}. Open evidence.`}
          >
            <p className="mono-label !text-[10px] text-[#a7a29a]">{k.metric}</p>
            <p className="num mt-1 text-[20px] font-semibold text-white">{k.displayValue}</p>
            <p className="mt-1 font-mono text-[10px] text-[#34d399]">◉ receipt ↓</p>
          </button>
        ))}
      </div>

      <section className="card-dark p-4" aria-label="Revenue versus net income">
        <h2 className="font-display text-[17px] font-semibold text-white">Revenue vs Net Income</h2>
        <p className="mono-label mt-0.5 text-[#6b675c]">SEC EDGAR · audited</p>
        <div className="mt-3" data-noswipe><RevenueChart data={s.revenueSeries} /></div>
      </section>

      <section aria-label="Macro context">
        <div className="snap-row">
          {s.macro.map((m) => (
            <span key={m} className="flex min-h-[44px] shrink-0 items-center rounded-full border border-white/12 bg-white/[0.04] px-3.5 font-mono text-[11px] text-[#d7d3c8]">{m}</span>
          ))}
        </div>
      </section>

      <section className="card-dark p-4" aria-label="Red flags">
        <h2 className="font-display text-[17px] font-semibold text-white">Red Flags</h2>
        <div className="mt-2 space-y-2">
          {s.redFlags.map((f, i) => {
            const open = flagsOpen === i;
            const sev = f.severity === 'High' ? 'text-[#f87171] border-[#f87171]/40 bg-[#f87171]/10'
              : f.severity === 'Medium' ? 'text-[#fbbf24] border-[#fbbf24]/40 bg-[#fbbf24]/10'
              : 'text-[#7ab8ff] border-[#7ab8ff]/40 bg-[#7ab8ff]/10';
            return (
              <div key={f.title} className="overflow-hidden rounded-xl border border-white/10">
                <button onClick={() => setFlagsOpen(open ? null : i)} aria-expanded={open} className="flex min-h-[52px] w-full items-center gap-2.5 bg-black/30 px-3 text-left">
                  <TriangleAlert size={16} className={f.severity === 'High' ? 'text-[#f87171]' : f.severity === 'Medium' ? 'text-[#fbbf24]' : 'text-[#7ab8ff]'} />
                  <span className="flex-1 text-[14px] font-medium text-white">{f.title}</span>
                  <span className={cn('rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase', sev)}>{f.severity}</span>
                  <ChevronDown size={16} className={cn('text-[#6b675c] transition-transform', open && 'rotate-180')} />
                </button>
                {open && <p className="anim-fade bg-black/30 px-3 pb-3 text-[13px] leading-6 text-[#a7a29a]">{f.body}</p>}
              </div>
            );
          })}
        </div>
      </section>

      <section aria-label="Forensic scores">
        <div className="snap-row">
          {s.forensics.map((f) => (
            <div key={f.name} className="card-dark w-[220px] p-4">
              <div className="flex items-center justify-between">
                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#ff5a1f]/15 font-display text-[19px] font-bold text-[#ff8a3d]">{f.short}</span>
                <span className={cn('font-mono text-[10px] uppercase tracking-wider', f.verdict === 'strong' ? 'text-[#34d399]' : f.verdict === 'neutral' ? 'text-[#fbbf24]' : 'text-[#f87171]')}>
                  ● {f.verdict}
                </span>
              </div>
              <p className="mt-2.5 font-display text-[15px] font-semibold text-white">{f.name}</p>
              <p className="num text-[22px] font-semibold text-white">{f.display}</p>
              <p className="mt-1 text-[12px] leading-5 text-[#a7a29a]">{f.meaning}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="card-dark p-4" aria-label="Executive analysis">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-[17px] font-semibold text-white">Executive Analysis</h2>
          <span className="mono-label text-[#ff8a3d]">Finora AI</span>
        </div>
        <div className={cn('memo-md mt-2 overflow-hidden', !memoOpen && 'max-h-[190px] [mask-image:linear-gradient(to_bottom,black_60%,transparent)]')}>
          <ReactMarkdown>{s.memo}</ReactMarkdown>
        </div>
        <button onClick={() => setMemoOpen(!memoOpen)} aria-expanded={memoOpen} className="pressable mt-2 min-h-[44px] w-full rounded-xl border border-white/10 bg-white/[0.03] text-[13px] font-semibold text-[#ffb25c]">
          {memoOpen ? 'Show less' : 'Read full analysis'}
        </button>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {s.watchTags.map((t) => (
            <span key={t} className="rounded-full border border-[#fbbf24]/30 bg-[#fbbf24]/[0.07] px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-[#fbbf24]">◷ {t}</span>
          ))}
        </div>
      </section>
    </div>
  );
}

// ---------------- metric rows (growth / profit) ----------------
function MetricList({ metrics, onEvidence }: { metrics: MetricEvidence[]; onEvidence: (e: MetricEvidence) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="space-y-2.5">
      {metrics.map((m) => (
        <MetricRow key={m.metric} m={m} isOpen={open === m.metric}
          onToggle={() => setOpen(open === m.metric ? null : m.metric)} onEvidence={onEvidence} />
      ))}
      <p className="pt-1 text-center font-mono text-[10px] uppercase tracking-[0.1em] text-[#6b675c]">Double-tap a row for instant receipt</p>
    </div>
  );
}

function MetricRow({ m, isOpen, onToggle, onEvidence }: {
  m: MetricEvidence; isOpen: boolean; onToggle: () => void; onEvidence: (e: MetricEvidence) => void;
}) {
  const vals = useMemo(() => [0.7, 0.85, 1].map((f) => Math.abs(m.value ?? 1) * f), [m.value]);
  return (
    <div className="card-dark overflow-hidden">
            <button
              onClick={onToggle}
              onDoubleClick={() => onEvidence(m)}
              aria-expanded={isOpen}
              className="pressable flex min-h-[64px] w-full items-center gap-3 p-3.5 text-left"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-white">{m.metric}</span>
                <span className="num mt-0.5 block text-[17px] font-semibold text-white">{m.displayValue}</span>
              </span>
              <Sparkline values={vals} />
              <ChevronDown size={17} className={cn('shrink-0 text-[#6b675c] transition-transform', isOpen && 'rotate-180')} />
            </button>
            {isOpen && (
              <div className="anim-fade border-t border-white/[0.07] p-3.5 pt-3">
                <p className="num text-[12px] text-[#ffb25c]">{m.formula}</p>
                <div className="mt-2" data-noswipe><TrendChart values={vals} labels={['', '', '']} /></div>
                <button onClick={() => onEvidence(m)} className="pressable mt-2.5 flex min-h-[48px] w-full items-center justify-center gap-1.5 rounded-xl border border-[#ff5a1f]/40 bg-[#ff5a1f]/10 text-[13px] font-semibold text-[#ff8a3d]">
                  <BadgeCheck size={15} /> Open full evidence receipt
                </button>
              </div>
            )}
          </div>
  );
}

// ---------------- valuation ----------------
function ValuationTab({ s, onEvidence }: { s: DashboardSession; onEvidence: (e: MetricEvidence) => void }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {s.valuation.map((v) => (
        <div key={v.metric} className="card-dark p-3.5">
          <p className="mono-label !text-[10px] text-[#a7a29a]">{v.metric}</p>
          {v.value == null && v.unavailableReason ? (
            <div className="mt-1.5"><UnavailableMetric reason={v.unavailableReason} /></div>
          ) : (
            <button onClick={() => onEvidence(v)} className="pressable block w-full text-left" aria-label={`${v.metric}: ${v.displayValue}. Open evidence.`}>
              <p className="num mt-1 text-[19px] font-semibold text-white">{v.displayValue}</p>
              <p className="num mt-1 line-clamp-2 text-[11px] leading-4 text-[#ffb25c]">{v.formula}</p>
              <p className="mt-1.5 font-mono text-[10px] text-[#34d399]">◉ receipt ↓</p>
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------- forensics ----------------
function ForensicsTab({ s }: { s: DashboardSession }) {
  return (
    <div className="space-y-3">
      {s.forensics.map((f, idx) => (
        <article key={f.name} className="card-dark p-4 anim-rise" style={{ animationDelay: `${idx * 0.07}s` }}>
          <div className="flex items-center gap-3">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#ff5a1f]/15 font-display text-[21px] font-bold text-[#ff8a3d]">{f.short}</span>
            <div>
              <h2 className="font-display text-[16px] font-semibold text-white">{f.name}</h2>
              <p className={cn('font-mono text-[11px] uppercase tracking-wider', f.verdict === 'strong' ? 'text-[#34d399]' : f.verdict === 'neutral' ? 'text-[#fbbf24]' : 'text-[#f87171]')}>
                ● {f.verdict} · {f.display}
              </p>
            </div>
          </div>
          <p className="mt-2.5 text-[14px] leading-6 text-[#d7d3c8]">{f.meaning}</p>

          {f.short === 'Z' && (
            <div className="mt-3" role="img" aria-label={`Altman Z ${f.display}: safe zone above 2.99`}>
              <div className="relative h-2.5 overflow-hidden rounded-full bg-gradient-to-r from-[#f87171] via-[#fbbf24] to-[#34d399]">
                <span className="absolute top-[-2px] h-[14px] w-[3px] rounded bg-white shadow" style={{ left: `${Math.min(96, (f.value / 5) * 100)}%` }} />
              </div>
              <div className="mt-1 flex justify-between font-mono text-[10px] text-[#6b675c]"><span>distress &lt;1.8</span><span>grey</span><span>safe &gt;2.99</span></div>
            </div>
          )}
          {f.short === 'M' && (
            <div className="mt-3 rounded-xl border border-white/10 bg-black/30 p-3">
              <div className="flex justify-between font-mono text-[11px]"><span className="text-[#6b675c]">threshold −1.78</span><span className="num text-[#34d399]">{f.display} · below = clean</span></div>
              <ProgressBar value={Math.min(100, Math.abs(f.value) * 30)} className="mt-2" />
            </div>
          )}

          <ul className="mt-3 space-y-1.5">
            {f.detail.map((d) => (
              <li key={d} className="flex items-center gap-2 rounded-lg bg-black/30 px-2.5 py-2 font-mono text-[11.5px] text-[#d7d3c8]">
                <span className={d.includes('✗') ? 'text-[#f87171]' : 'text-[#34d399]'}>{d.includes('✗') ? '✗' : '✓'}</span>
                {d.replace(' ✓', '').replace(' ✗', '')}
              </li>
            ))}
          </ul>
        </article>
      ))}
    </div>
  );
}

// ---------------- sources ----------------
function SourcesTab({ s, mismatchOnly }: { s: DashboardSession; mismatchOnly: boolean }) {
  const [filter, setFilter] = useState<'ALL' | 'PRIMARY' | 'OFFICIAL' | 'CORROBORATING'>(mismatchOnly ? 'ALL' : 'ALL');
  const list = s.sources.filter((x) => (filter === 'ALL' || x.tier === filter) && (!mismatchOnly || x.mismatch));
  return (
    <div>
      <div className="snap-row mb-3" role="group" aria-label="Filter sources by tier">
        {(['ALL', 'PRIMARY', 'OFFICIAL', 'CORROBORATING'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            aria-pressed={filter === f}
            className={cn(
              'pressable min-h-[44px] shrink-0 rounded-full border px-4 font-mono text-[11px] font-semibold tracking-wider',
              filter === f ? 'border-[#ff5a1f] bg-[#ff5a1f] text-white' : 'border-white/12 bg-white/[0.04] text-[#a7a29a]',
            )}
          >
            {f}
          </button>
        ))}
      </div>
      {mismatchOnly && <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-[#fbbf24]">Showing mismatches only</p>}
      <div className="space-y-2.5">
        {list.length === 0 && <p className="py-8 text-center text-sm text-[#a7a29a]">No sources match this filter.</p>}
        {list.map((src) => (
          <article key={src.id} className="card-dark p-3.5" style={src.mismatch ? { borderColor: 'rgba(251,191,36,0.45)' } : undefined}>
            <div className="flex items-center justify-between gap-2">
              <TierBadge tier={src.tier} />
              <span className={cn('flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider', src.verified ? 'text-[#34d399]' : 'text-[#fbbf24]')}>
                {src.verified ? <BadgeCheck size={13} /> : <TriangleAlert size={13} />}
                {src.verified ? 'verified' : 'mismatch'}
              </span>
            </div>
            <h3 className="mt-2 font-display text-[15px] font-semibold text-white">{src.name}</h3>
            <p className="mt-0.5 text-[13px] leading-5 text-[#a7a29a]">{src.note}</p>
            <div className="mt-2.5 flex items-center gap-2">
              <span className="num min-w-0 flex-1 truncate rounded-lg bg-black/40 px-2.5 py-2 text-[11px] text-[#6b675c]">{src.url}</span>
              <a href={src.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${src.name} in a new tab`}
                className="pressable flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/12 bg-white/[0.05] text-white">
                <ExternalLink size={16} />
              </a>
              <button aria-label="Share source"
                onClick={async () => {
                  try {
                    if (navigator.share) await navigator.share({ title: src.name, url: src.url });
                    else { await navigator.clipboard.writeText(src.url); }
                  } catch { /* dismissed */ }
                }}
                className="pressable flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/12 bg-white/[0.05] text-white">
                <Share2 size={16} />
              </button>
            </div>
          </article>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-center gap-2 pb-2">
        <Download size={13} className="text-[#6b675c]" />
        <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-[#6b675c]">Ledger: {s.sources.length} sources · {s.quality.crossVerified} cross-verified</p>
      </div>
    </div>
  );
}

// keep tree-shaken lazy import referenced for future tab splitting
void Suspense;
void lazy;

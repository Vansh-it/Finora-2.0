import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { AlertTriangle, Check, ChevronDown, ChevronRight, Clock3, History, Home, Loader2, MailOpen, Sparkles, X } from 'lucide-react';
import { RESEARCH_STAGES, ApiError, getRecentTickers, getUsage, runResearch } from '../lib/api';
import { ResearchInput } from '../components/ResearchInput';
import { ConfirmSheet } from '../components/BottomSheet';
import { ProgressBar, TickerChip } from '../components/ui';
import { formatClock } from '../lib/format';
import { useCachedQuery } from '../hooks/hooks';
import { cn } from '../lib/cn';

// ---------------- Research landing ----------------
export function ResearchPage() {
  const [params] = useSearchParams();
  const ticker = params.get('ticker');
  if (ticker) return <ProcessingPage ticker={ticker} />;
  return <ResearchLanding />;
}

const SUGGESTED = [
  { ticker: 'AAPL', name: 'Apple', thesis: 'How durable is the iPhone cash machine?' },
  { ticker: 'NVDA', name: 'NVIDIA', thesis: 'Is the AI trade priced for perfection?' },
  { ticker: 'MSFT', name: 'Microsoft', thesis: 'Azure growth vs. record capex intensity' },
  { ticker: 'TSLA', name: 'Tesla', thesis: 'Margin pressure vs. robotaxi optionality' },
  { ticker: 'KO', name: 'Coca-Cola', thesis: 'Is the dividend still safe to hold?' },
];

const HOW_STEPS = [
  'Finora identifies the exact SEC registrant behind the ticker.',
  'It parses 10-K / 10-Q filings — statements, footnotes and MD&A.',
  'Every line item is normalized to standard XBRL concepts.',
  'Python computes 48+ metrics deterministically — auditable formulas.',
  'Each key figure is cross-checked across up to 9 sources.',
  'Finora AI writes the memo over verified values; you get the 9-tab dashboard.',
];

const TIPS = [
  'Every number has a receipt — double-tap any metric to open its evidence.',
  'Red flags live in their own tab: check them before you trust the story.',
  'Ask Finora AI to explain one forensic score in plain words.',
  'Export any research to Excel and keep it in your own notes.',
  'Mismatches are shown, never hidden — always read the Sources tab.',
];

function ResearchLanding() {
  const usage = useCachedQuery('usage', async () => getUsage(), { ttlMs: 30_000 });
  const recent = useCachedQuery('recent', async (s) => { void s; return getRecentTickers(); }, { ttlMs: 60_000 });
  const exhausted = (usage.data?.remaining ?? 1) <= 0;
  const [howOpen, setHowOpen] = useState(false);
  const [tip, setTip] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setTip((i) => (i + 1) % TIPS.length), 6000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="grid-glow relative flex min-h-full flex-col px-5 pb-6 pt-6">
      <div className="research-particles" aria-hidden />

      <div className="relative z-10">
        <p className="mono-label anim-rise text-[#ff8a3d]">New investigation</p>
        <h1 className="anim-rise mt-1 font-display text-[26px] font-bold leading-[30px] tracking-tight text-white">
          What company should Finora investigate?
        </h1>

        <div className="anim-rise stagger-1 relative z-20 mt-5">
          {exhausted && usage.data ? (
            <div className="card-dark anim-pop p-5" style={{ borderColor: 'rgba(251,191,36,0.4)' }}>
              <p className="flex items-center gap-2 font-display text-[18px] font-semibold text-[#fbbf24]">
                <AlertTriangle size={19} /> Research limit reached
              </p>
              <p className="mt-1.5 text-[14px] leading-6 text-[#d7d3c8]">
                You&apos;ve used all 5 free researches. Your quota resets in:
              </p>
              <ResetCountdown resetAt={usage.data.resetAt} big />
              <div className="mt-4 space-y-2">
                <Link to="/limit" className="pressable flex min-h-[52px] items-center justify-center gap-2 rounded-2xl btn-primary font-display text-[15px] font-semibold text-white">
                  <MailOpen size={17} /> Read the developer&apos;s letter
                </Link>
                <div className="flex gap-2">
                  <Link to="/history" className="pressable flex min-h-[48px] flex-1 items-center justify-center gap-1.5 rounded-2xl border border-white/15 bg-white/[0.06] text-sm font-semibold text-white"><History size={16} /> History</Link>
                  <Link to="/" className="pressable flex min-h-[48px] flex-1 items-center justify-center gap-1.5 rounded-2xl border border-white/15 bg-white/[0.06] text-sm font-semibold text-white"><Home size={16} /> Home</Link>
                </div>
              </div>
            </div>
          ) : (
            <ResearchInput large />
          )}
        </div>

        <div className="anim-rise stagger-2 mt-4">
          {usage.loading ? (
            <div className="card-dark p-4"><div className="skeleton h-4 w-2/3" /></div>
          ) : usage.data ? (
            <div className="card-dark p-4">
              <div className="flex items-center justify-between">
                <p className="text-[14px] font-medium text-white">{usage.data.remaining} of {usage.data.limit} researches left</p>
                <p className="num font-mono text-[11px] text-[#6b675c]">resets <ResetCountdown resetAt={usage.data.resetAt} /></p>
              </div>
              <ProgressBar value={usage.data.used} max={usage.data.limit} className="mt-2.5" />
            </div>
          ) : null}
        </div>

        {/* Suggested investigations — horizontal pills */}
        <section className="anim-rise stagger-3 mt-6" aria-label="Suggested investigations">
          <div className="mb-2.5 flex items-center gap-1.5">
            <Sparkles size={13} className="text-[#ff8a3d]" />
            <p className="mono-label text-[#ff8a3d]">Suggested investigations</p>
          </div>
          <div className="snap-row -mx-5 px-5" role="list">
            {SUGGESTED.map((s) => (
              <Link
                key={s.ticker}
                to={`/research?ticker=${s.ticker}`}
                role="listitem"
                className="pressable flex w-[248px] shrink-0 flex-col rounded-2xl border border-white/12 bg-gradient-to-b from-white/[0.06] to-white/[0.02] p-3.5"
                aria-label={`Investigate ${s.name} (${s.ticker})`}
              >
                <span className="flex items-center gap-2">
                  <TickerChip ticker={s.ticker} />
                  <span className="truncate text-[13px] font-semibold text-white">{s.name}</span>
                  <ChevronRight size={15} className="ml-auto shrink-0 text-[#6b675c]" />
                </span>
                <span className="mt-2 line-clamp-2 text-[12.5px] leading-5 text-[#a7a29a]">{s.thesis}</span>
              </Link>
            ))}
          </div>
        </section>

        {recent.data && recent.data.length > 0 && (
          <div className="anim-rise stagger-4 mt-5">
            <p className="mono-label mb-2 text-[#6b675c]">Recent · quick start</p>
            <div className="flex flex-wrap gap-2">
              {recent.data.map((t) => (
                <Link key={t} to={`/research?ticker=${t}`} className="pressable flex min-h-[48px] items-center gap-2 rounded-2xl border border-white/12 bg-white/[0.04] px-4">
                  <TickerChip ticker={t} /> <ChevronRight size={15} className="text-[#6b675c]" />
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* How Finora works — expandable */}
        <div className="anim-rise stagger-4 mt-6 overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02]">
          <button
            onClick={() => setHowOpen((v) => !v)}
            aria-expanded={howOpen}
            className="flex min-h-[60px] w-full items-center gap-3 px-4 text-left"
          >
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#ff5a1f]/15">
              <Sparkles size={16} className="text-[#ff8a3d]" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-display text-[15px] font-semibold text-white">How Finora works</span>
              <span className="mono-label mt-0.5 block text-[#6b675c]">6 steps · SEC-first</span>
            </span>
            <ChevronDown size={18} className={cn('shrink-0 text-[#ff8a3d] transition-transform', howOpen && 'rotate-180')} />
          </button>
          <div className={cn('grid transition-all duration-300', howOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
            <div className="overflow-hidden">
              <ol className="space-y-2 px-4 pb-4 text-[14px] text-[#d7d3c8]">
                {HOW_STEPS.map((s, i) => (
                  <li key={s} className="flex gap-2.5">
                    <span className="num shrink-0 text-[#ff8a3d]">{String(i + 1).padStart(2, '0')}</span>
                    <span className="leading-6">{s}</span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </div>
      </div>

      {/* thin footer */}
      <footer className="relative z-10 mt-auto pt-8 text-center">
        {/* Reserved two-line block: the tip length changes as it rotates, but the
            receipt line below never moves and the gap between them stays constant. */}
        <div className="mx-auto flex min-h-[32px] max-w-[340px] items-center justify-center px-5">
          <p className="rotating-tip font-mono text-[11px] leading-4 text-[#a7a29a]" key={tip}>
            <span className="text-[#ff8a3d]">TIP · </span>{TIPS[tip]}
          </p>
        </div>
        <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.14em] text-[#6b675c]">
          Finora <span className="text-[#ff5a1f]">•</span> Every number has a receipt
        </p>
      </footer>
    </div>
  );
}

export function ResetCountdown({ resetAt, big }: { resetAt: number; big?: boolean }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const remain = Math.max(0, Math.floor((resetAt - now) / 1000));
  return <span className={cn('num', big ? 'mt-2 block text-[30px] font-semibold text-white' : 'text-[#ffb25c]')}>{formatClock(remain)}</span>;
}

// ---------------- Processing ----------------
function ProcessingPage({ ticker }: { ticker: string }) {
  const nav = useNavigate();
  const [stage, setStage] = useState(-1);
  const [elapsed, setElapsed] = useState(0);
  const [failed, setFailed] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const started = useRef(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    const t0 = Date.now();
    const clock = setInterval(() => setElapsed(Date.now() - t0), 500);
    return () => clearInterval(clock);
  }, []);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    setFailed(null);
    setConflict(false);
    setStage(-1);
    const c = new AbortController();
    abort.current = c;
    // wake lock
    const lockRequest = async () => {
      try {
        const nav2 = navigator as Navigator & { wakeLock?: { request: (k: string) => Promise<unknown> } };
        await nav2.wakeLock?.request('screen');
      } catch { /* ignore */ }
    };
    void lockRequest();

    runResearch(ticker, (i) => {
      if (!c.signal.aborted) {
        setStage(i);
        navigator.vibrate?.(10);
      }
    }, c.signal).then(
      (s) => { if (!c.signal.aborted) nav(`/dashboard?session_id=${s.sessionId}`, { replace: true }); },
      (e: unknown) => {
        if ((e as Error).name === 'AbortError') return;
        if (e instanceof ApiError && e.code === 'quota_exhausted') nav('/limit', { replace: true });
        else if (e instanceof ApiError && e.status === 401) nav('/auth', { replace: true, state: { ticker } });
        else if (e instanceof ApiError && e.status === 409) setConflict(true);
        else setFailed(e instanceof Error ? e.message : 'Research failed unexpectedly.');
      },
    );
    return () => {
      c.abort();
      // allow StrictMode remount / retry to start a fresh run; the aborted
      // run never reaches consumeQuota, so quota stays correct.
      started.current = false;
    };
  }, [ticker, nav, attempt]);

  const mm = String(Math.floor(elapsed / 60000)).padStart(2, '0');
  const ss = String(Math.floor((elapsed % 60000) / 1000)).padStart(2, '0');

  return (
    <div className="grid-glow flex min-h-full flex-col px-5 pb-8 pt-6">
      <div className="anim-fade flex items-center justify-between">
        <TickerChip ticker={ticker.toUpperCase()} className="text-[13px]" />
        <p className="num flex items-center gap-1.5 font-mono text-[13px] text-[#a7a29a]" aria-live="off">
          <Clock3 size={14} /> {mm}:{ss}
        </p>
      </div>

      <h1 className="anim-rise mt-4 text-center font-display text-[22px] font-bold tracking-tight text-white">
        Investigating {ticker.toUpperCase()}
      </h1>
      <p className="mt-1 text-center text-[14px] text-[#a7a29a]" role="status" aria-live="polite">
        {stage >= RESEARCH_STAGES.length ? 'Research file complete' : stage >= 0 ? RESEARCH_STAGES[Math.min(stage, RESEARCH_STAGES.length - 1)] + '…' : 'Starting…'}
      </p>

      <ol className="relative mx-auto mt-6 w-full max-w-[320px] space-y-[7px]" aria-label="Research progress">
        {RESEARCH_STAGES.map((s, i) => {
          const done = i < stage || stage >= RESEARCH_STAGES.length;
          const active = i === stage;
          return (
            <li
              key={s}
              className={cn(
                'flex min-h-[46px] items-center gap-3 rounded-2xl border px-3.5 transition-all duration-300',
                done ? 'border-[#34d399]/35 bg-[#34d399]/[0.07]'
                  : active ? 'border-[#ff5a1f]/60 bg-[#ff5a1f]/[0.1] shadow-[0_0_24px_rgba(255,90,31,0.25)]'
                  : 'border-white/[0.07] bg-white/[0.02] opacity-60',
              )}
            >
              <span className={cn(
                'flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2',
                done ? 'border-[#34d399] bg-[#34d399] text-black' : active ? 'border-[#ff5a1f] text-[#ff8a3d]' : 'border-white/20 text-transparent',
              )}>
                {done ? <Check size={15} strokeWidth={3} /> : active ? <Loader2 size={14} className="animate-spin" /> : <span className="h-1.5 w-1.5 rounded-full bg-white/30" />}
              </span>
              <span className={cn('text-[14px] font-medium', done ? 'text-white' : active ? 'text-white' : 'text-[#6b675c]')}>{s}</span>
              {done && <span className="stamp ml-auto !border-[#34d399]/60 !py-0.5 !text-[9px]" style={{ animation: 'stage-stamp .3s ease-out both' }}>done</span>}
            </li>
          );
        })}
      </ol>

      {elapsed > 150_000 && stage < RESEARCH_STAGES.length && (
        <p className="anim-fade mt-4 rounded-2xl border border-[#fbbf24]/40 bg-[#fbbf24]/[0.07] p-3 text-center text-[13px] text-[#fbbf24]">
          Taking longer than usual — SEC EDGAR can be slow. Hang tight.
        </p>
      )}

      {failed && (
        <div role="alert" className="anim-pop mt-4 rounded-2xl border border-[#f87171]/40 bg-[#f87171]/[0.07] p-4 text-center">
          <p className="text-[14px] font-semibold text-[#f87171]">Research hit a snag</p>
          <p className="mt-1 text-[13px] text-[#d7d3c8]">{failed}</p>
          <div className="mt-3 flex gap-2">
            <button onClick={() => setAttempt((a) => a + 1)} className="pressable min-h-[48px] flex-1 rounded-2xl border border-white/15 bg-white/[0.06] text-sm font-semibold text-white">Retry</button>
            <button onClick={() => nav('/history')} className="pressable min-h-[48px] flex-1 rounded-2xl btn-primary text-sm font-semibold text-white">History</button>
          </div>
        </div>
      )}

      {conflict && (
        <div role="alert" className="anim-pop mt-4 rounded-2xl border border-[#fbbf24]/40 bg-[#fbbf24]/[0.07] p-4 text-center">
          <p className="text-[14px] font-semibold text-[#fbbf24]">Research already in progress</p>
          <p className="mt-1 text-[13px] text-[#d7d3c8]">This ticker is being researched right now.</p>
          <button onClick={() => nav('/history')} className="pressable mt-3 min-h-[48px] w-full rounded-2xl btn-primary text-sm font-semibold text-white">Go to History</button>
        </div>
      )}

      <div className="mt-auto pt-6">
        <button
          onClick={() => setConfirmCancel(true)}
          className="pressable flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl border border-white/15 bg-white/[0.04] font-display text-[15px] font-semibold text-[#a7a29a]"
        >
          <X size={17} /> Cancel research
        </button>
      </div>

      <ConfirmSheet
        open={confirmCancel} onClose={() => setConfirmCancel(false)}
        title="Cancel research?" body="This investigation will stop and won't use any of your quota." confirmLabel="Yes, cancel"
        onConfirm={() => { abort.current?.abort(); nav('/research', { replace: true }); }}
      />
    </div>
  );
}

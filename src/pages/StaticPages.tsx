import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowDown, BadgeCheck, Bell, ChevronDown, ChevronRight, Download,
  FileText, History, Home, PenLine, ShieldCheck, Sigma, Star, Zap,
} from 'lucide-react';
import { ApiError, getReviews, postReview } from '../lib/api';
import type { Review } from '../lib/data';
import { BottomSheet } from '../components/BottomSheet';
import { PullToRefresh } from '../components/PullToRefresh';
import { Button, EditorialHeading, ErrorState, HighlightText, Skeleton, SourceStamp, Stars, TickerChip } from '../components/ui';
import { formatClock, formatDate } from '../lib/format';
import { getQuotaState } from '../lib/api';
import { isAuthed } from '../lib/auth';
import { useCachedQuery } from '../hooks/hooks';
import { useToast } from '../hooks/toast';
import { cn } from '../lib/cn';

// ---------------- Methodology ----------------
const PRINCIPLES = [
  { t: 'Sources', d: 'SEC EDGAR is the factual authority. Company IR and licensed market feeds are official. Everything else only corroborates — never overrules.' },
  { t: 'Statements', d: 'Every line item is normalized to standard XBRL concepts so periods stay comparable even when labels change.' },
  { t: 'Calculations', d: 'Python computes all 48+ metrics deterministically. Same filing in, same numbers out — every time.' },
  { t: 'Verification', d: 'Each key figure is cross-checked across up to 9 sources. Mismatches are surfaced, never hidden.' },
  { t: 'AI', d: 'Finora AI writes interpretation over verified values. It explains; it never fabricates.' },
];

export function MethodologyPage() {
  const [open, setOpen] = useState(0);
  return (
    <div className="grid-glow px-5 pb-10 pt-6">
      <p className="mono-label anim-rise text-[#ff8a3d]">Methodology</p>
      <h1 className="anim-rise mt-1 font-display text-[26px] font-bold leading-[30px] text-white">How Finora earns<br />your trust</h1>

      <div className="anim-rise stagger-1 mt-5 grid grid-cols-3 gap-2">
        {[
          { icon: BadgeCheck, t: 'SEC = factual authority' },
          { icon: Sigma, t: 'Python = calculation engine' },
          { icon: Zap, t: 'AI = interpretation' },
        ].map((c) => (
          <div key={c.t} className="card-dark flex flex-col items-center p-3 text-center">
            <c.icon size={19} className="text-[#ff8a3d]" />
            <p className="mt-1.5 font-mono text-[10px] uppercase leading-4 tracking-wider text-white">{c.t}</p>
          </div>
        ))}
      </div>

      <div className="mt-5 space-y-2">
        {PRINCIPLES.map((p, i) => {
          const isOpen = open === i;
          return (
            <div key={p.t} className="anim-rise overflow-hidden rounded-2xl border border-white/10 bg-[#14151a]" style={{ animationDelay: `${i * 0.05}s` }}>
              <button onClick={() => setOpen(isOpen ? -1 : i)} aria-expanded={isOpen} className="flex min-h-[56px] w-full items-center gap-3 px-4 text-left">
                <span className="num flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#ff5a1f]/15 font-mono text-[13px] font-semibold text-[#ff8a3d]">{i + 1}</span>
                <span className="flex-1 font-display text-[16px] font-semibold text-white">{p.t}</span>
                <ChevronDown size={18} className={cn('text-[#ff8a3d] transition-transform', isOpen && 'rotate-180')} />
              </button>
              <div className={cn('grid transition-all', isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
                <p className="overflow-hidden px-4 text-[14px] leading-6 text-[#a7a29a]">{isOpen ? p.d : ''}<span className={isOpen ? 'block h-4' : ''} /></p>
              </div>
            </div>
          );
        })}
      </div>

      <div className="anim-rise mt-6">
        <EditorialHeading kicker="Pipeline" title="Source → Interpretation" />
        <ol className="mt-3 space-y-0" aria-label="Verification pipeline">
          {['Source', 'Fact', 'Calculation', 'Verification', 'Interpretation'].map((s, i, arr) => (
            <li key={s}>
              <div className="card-dark flex items-center gap-3 p-3.5">
                <span className="num font-mono text-[12px] text-[#ff8a3d]">{String(i + 1).padStart(2, '0')}</span>
                <span className="font-display text-[15px] font-semibold text-white">{s}</span>
              </div>
              {i < arr.length - 1 && <div className="flex justify-center py-1" aria-hidden><ArrowDown size={15} className="text-[#ff5a1f]" /></div>}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

// ---------------- About ----------------
const ABOUT_SECTIONS = [
  { id: 'what', t: 'What Finora Is', d: 'Finora is an AI financial research and intelligence app. Search a company; Finora identifies it, reads SEC filings, normalizes statements, calculates metrics in Python, verifies against external sources, and delivers an evidence-traced dashboard.' },
  { id: 'hierarchy', t: 'Source Hierarchy', d: 'PRIMARY: SEC EDGAR filings. OFFICIAL: company investor relations and licensed market data. CORROBORATING: independent aggregates and news. Higher tiers always win conflicts.' },
  { id: 'sec', t: 'SEC-First Methodology', d: 'Every research starts at EDGAR — 10-K and 10-Q forms, accession numbers recorded. No filing, no claim: unavailable metrics show their reason instead of a guess.' },
  { id: 'python', t: 'Python Calculations', d: 'Growth, profitability, valuation and forensic scores are computed by deterministic Python code — auditable formulas you can inspect per metric.' },
  { id: 'ai', t: 'AI Interpretation', d: 'A large language model writes the executive memo and answers questions, grounded strictly on computed values. It cites; it does not invent.' },
  { id: 'transparency', t: 'Source Transparency', d: 'The Sources tab ledgers every input with trust tiers and verification status. Open any of them in one tap.' },
  { id: 'limits', t: 'Limitations', d: 'Finora covers US-listed companies via SEC EDGAR. Market data may lag. This is research tooling — not investment advice.' },
];
const DATA_SOURCES = [
  { n: 'SEC EDGAR', tier: 'PRIMARY', d: 'Audited 10-K / 10-Q filings' },
  { n: 'Business Quant', tier: 'OFFICIAL', d: 'Structured fundamentals' },
  { n: 'Twelve Data', tier: 'OFFICIAL', d: 'Live prices, splits, dividends' },
  { n: 'Tavily', tier: 'CORROBORATING', d: 'News + guidance language' },
  { n: 'Jina', tier: 'CORROBORATING', d: 'Document extraction' },
  { n: 'Nemotron', tier: 'CORROBORATING', d: 'AI reasoning checks' },
];

export function AboutPage() {
  return (
    <div className="pb-10">
      <div className="grid-glow px-5 pt-6">
        <p className="mono-label anim-rise text-[#ff8a3d]">About</p>
        <h1 className="anim-rise mt-1 font-display text-[26px] font-bold leading-[30px] text-white">Research you can<br /><HighlightText>audit.</HighlightText></h1>
      </div>
      <div className="snap-row sticky top-0 z-30 mt-4 bg-[#0a0a0c]/95 px-5 py-2 backdrop-blur" role="navigation" aria-label="Jump to section">
        {ABOUT_SECTIONS.map((s) => (
          <a key={s.id} href={`#about-${s.id}`} className="flex min-h-[44px] shrink-0 items-center rounded-full border border-white/12 bg-white/[0.04] px-4 font-mono text-[11px] text-[#d7d3c8]">{s.t}</a>
        ))}
      </div>
      <div className="space-y-3 px-5 pt-2">
        {ABOUT_SECTIONS.map((s, i) => (
          <article key={s.id} id={`about-${s.id}`} style={{ scrollMarginTop: 120 }} className="card-dark anim-rise scroll-mt-28 p-4" >
            <p className="num font-mono text-[12px] text-[#ff8a3d]">{String(i + 1).padStart(2, '0')}</p>
            <h2 className="mt-1 font-display text-[17px] font-semibold text-white">{s.t}</h2>
            <p className="mt-1.5 text-[14px] leading-6 text-[#a7a29a]">{s.d}</p>
          </article>
        ))}
        <h2 className="pt-2 font-display text-[19px] font-semibold text-white">Data sources</h2>
        {DATA_SOURCES.map((d) => (
          <div key={d.n} className="card-dark flex items-center gap-3 p-3.5">
            <FileText size={18} className="shrink-0 text-[#ff8a3d]" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[14px] font-semibold text-white">{d.n}</p>
              <p className="truncate text-[12px] text-[#6b675c]">{d.d}</p>
            </div>
            <span className={cn('shrink-0 rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold',
              d.tier === 'PRIMARY' ? 'border-[#34d399]/40 bg-[#34d399]/10 text-[#34d399]'
              : d.tier === 'OFFICIAL' ? 'border-[#7ab8ff]/40 bg-[#7ab8ff]/10 text-[#7ab8ff]'
              : 'border-[#e3b008]/40 bg-[#e3b008]/10 text-[#e3b008]')}>{d.tier}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------- Reviews ----------------
export function ReviewsPage() {
  const toast = useToast();
  const query = useCachedQuery<Review[]>('reviews', async () => getReviews(), { ttlMs: 60_000 });
  const [visible, setVisible] = useState(10);
  const [sheet, setSheet] = useState(false);
  const [form, setForm] = useState({ name: '', company: '', stars: 5, text: '', site: '' });
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.site) return; // honeypot
    if (form.text.trim().length < 10 || form.text.length > 2000) {
      setFormErr('Review must be 10–2000 characters.');
      return;
    }
    if (!form.name.trim()) {
      setFormErr('Please add your name.');
      return;
    }
    setBusy(true);
    setFormErr(null);
    try {
      await postReview({ name: form.name.trim(), company: form.company.trim().toUpperCase() || undefined, stars: form.stars, text: form.text.trim() });
      setSheet(false);
      setForm({ name: '', company: '', stars: 5, text: '', site: '' });
      await query.refetch();
      toast('Review posted — thank you');
    } catch (err) {
      setFormErr(err instanceof ApiError ? err.message : 'Could not post review.');
    } finally {
      setBusy(false);
    }
  };

  const list = (query.data ?? []).slice(0, visible);

  return (
    <div className="pb-28">
      <div className="grid-glow px-5 pt-6">
        <p className="mono-label anim-rise text-[#ff8a3d]">Wall of love</p>
        <h1 className="anim-rise mt-1 font-display text-[26px] font-bold text-white">Reviews</h1>
      </div>
      <PullToRefresh onRefresh={() => query.refetch()}>
        <div className="space-y-3 px-5 pt-4">
          {query.loading && !query.data && [0, 1, 2].map((i) => <Skeleton key={i} className="h-[150px] w-full" />)}
          {query.error && !query.data && <ErrorState message="Couldn't load reviews." onRetry={() => { void query.refetch(); }} />}
          {query.data && query.data.length === 0 && (
            <div className="card-dark anim-rise p-6 text-center">
              <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[#ff5a1f]/15">
                <Star size={22} className="text-[#ff8a3d]" fill="#ff8a3d" />
              </span>
              <h2 className="mt-3 font-display text-[18px] font-bold text-white">Be the first to review</h2>
              <p className="mt-1.5 text-[14px] leading-6 text-[#a7a29a]">No reviews yet — and it takes no time. Rate your research and say what Finora helped you verify.</p>
              <button onClick={() => setSheet(true)} className="btn-primary pressable mt-4 flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl font-display text-[15px] font-semibold text-white">
                <PenLine size={17} /> Write a review
              </button>
            </div>
          )}
          {list.map((r, i) => (
            <figure key={r.id} className="card-dark anim-rise p-4" style={{ animationDelay: `${Math.min(i, 5) * 0.05}s` }}>
              <div className="flex items-center justify-between">
                <Stars value={r.stars} />
                <span className="font-mono text-[11px] text-[#6b675c]">{formatDate(r.date)}</span>
              </div>
              <blockquote className="mt-2 text-[14px] leading-6 text-[#d7d3c8]">“{r.text}”</blockquote>
              <figcaption className="mt-2.5 flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#ff5a1f]/15 font-display text-[13px] font-semibold text-[#ff8a3d]">{r.name[0]?.toUpperCase()}</span>
                <span className="text-[13px] font-medium text-white">{r.name}</span>
                {r.company && <TickerChip ticker={r.company} />}
              </figcaption>
            </figure>
          ))}
          {query.data && visible < query.data.length && (
            <button onClick={() => setVisible((v) => v + 10)} className="pressable min-h-[52px] w-full rounded-2xl border border-white/15 bg-white/[0.05] text-sm font-semibold text-white">
              Load more ({query.data.length - visible} left)
            </button>
          )}
        </div>
      </PullToRefresh>

      {!(query.data && query.data.length === 0) && (
        <button
          onClick={() => setSheet(true)}
          className="btn-primary pressable fixed bottom-[92px] z-40 flex min-h-[52px] items-center gap-2 rounded-2xl px-5 font-display text-[15px] font-semibold text-white"
          style={{ right: 'max(16px, calc(50% - 215px + 16px))' }}
          aria-haspopup="dialog"
        >
          <PenLine size={17} /> Write a review
        </button>
      )}

      <BottomSheet open={sheet} onClose={() => setSheet(false)} title="Write a review" snap={95}>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label htmlFor="rv-name" className="mono-label mb-1.5 block text-[#a7a29a]">Name</label>
            <input id="rv-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="min-h-[52px] w-full rounded-2xl border border-white/12 bg-black/40 px-4 text-white outline-none placeholder:text-[#6b675c]" placeholder="Your name" autoComplete="name" />
          </div>
          <div>
            <label htmlFor="rv-co" className="mono-label mb-1.5 block text-[#a7a29a]">Company (optional)</label>
            <input id="rv-co" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })}
              className="min-h-[52px] w-full rounded-2xl border border-white/12 bg-black/40 px-4 uppercase text-white outline-none placeholder:text-[#6b675c]" placeholder="AAPL" autoComplete="off" maxLength={6} />
          </div>
          <div>
            <span id="rv-stars-label" className="mono-label mb-1.5 block text-[#a7a29a]">Rating</span>
            <div role="radiogroup" aria-labelledby="rv-stars-label" className="flex gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" role="radio" aria-checked={form.stars === n} aria-label={`${n} star${n > 1 ? 's' : ''}`}
                  onClick={() => setForm({ ...form, stars: n })}
                  className="pressable flex h-11 w-11 items-center justify-center rounded-xl">
                  <Star size={26} className={n <= form.stars ? 'fill-[#ff5a1f] text-[#ff5a1f]' : 'text-[#6b675c]'} />
                </button>
              ))}
            </div>
          </div>
          <div>
            <label htmlFor="rv-text" className="mono-label mb-1.5 block text-[#a7a29a]">Review</label>
            <textarea id="rv-text" value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })}
              rows={4} maxLength={2000} placeholder="What did Finora help you verify? (10–2000 chars)"
              className="min-h-[110px] w-full resize-none rounded-2xl border border-white/12 bg-black/40 px-4 py-3 text-white outline-none placeholder:text-[#6b675c]" />
            <p className="num mt-1 text-right font-mono text-[11px] text-[#6b675c]" aria-live="polite">{form.text.length}/2000</p>
          </div>
          {/* honeypot */}
          <input aria-hidden tabIndex={-1} autoComplete="off" value={form.site} onChange={(e) => setForm({ ...form, site: e.target.value })}
            className="absolute h-0 w-0 opacity-0" name="website" />
          {formErr && <p role="alert" className="rounded-xl border border-[#f87171]/40 bg-[#f87171]/10 p-3 text-[13px] text-[#f87171]">{formErr}</p>}
          <Button type="submit" size="lg" loading={busy}>Post review</Button>
        </form>
      </BottomSheet>
    </div>
  );
}

// ---------------- Letter (quota) ----------------
const TIPS = [
  'Re-read your last dashboard — check the red flags tab',
  'Ask Finora AI to explain one forensic score',
  'Compare two past researches side by side',
  'Export a session to Excel for your notes',
];

export function LetterPage() {
  const resetAt = getQuotaState().resetAt;
  const [now, setNow] = useState(Date.now());
  const [done, setDone] = useState<boolean[]>(TIPS.map(() => false));
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="px-5 pb-10 pt-6">
      <div className="anim-rise overflow-hidden rounded-[20px] border border-white/12 bg-gradient-to-b from-[#1b1a17] to-[#141311] p-6 shadow-[0_20px_50px_rgba(0,0,0,0.5)]">
        <p className="mono-label text-[#ff8a3d]">A letter from the developer</p>
        <h1 className="mt-2 font-display text-[24px] font-bold leading-[30px] text-[#f5f3ee]">You hit today&apos;s<br />research limit.</h1>
        <div className="mt-4 space-y-3 text-[15px] leading-[24px] text-[#d7d3c8]">
          <p>Hey — <span className="font-semibold text-white">vansh chaurasia</span> here. I built Finora.</p>
          <p>Each research reads real SEC filings, runs Python calculations and verifies across 9 sources. That costs real compute — so the free tier resets to <span className="font-semibold text-white">5 fresh researches every 24 hours</span>.</p>
          <p>Your quota refreshes in:</p>
        </div>
        <p className="num mt-1 text-center text-[38px] font-semibold tracking-tight text-white" role="timer" aria-label="Quota reset countdown">
          {formatClock(Math.max(0, (resetAt - now) / 1000))}
        </p>
        <div className="mt-4 border-t border-white/10 pt-4">
          <p className="mono-label mb-2 text-[#6b675c]">While you wait</p>
          <ul className="space-y-2">
            {TIPS.map((tip, i) => (
              <li key={tip}>
                <button
                  onClick={() => setDone((d) => d.map((v, j) => (j === i ? !v : v)))}
                  aria-pressed={done[i]}
                  className="pressable flex min-h-[48px] w-full items-center gap-2.5 rounded-xl border border-white/10 bg-black/30 px-3 text-left"
                >
                  <span className={cn('flex h-6 w-6 shrink-0 items-center justify-center rounded-md border', done[i] ? 'border-[#34d399] bg-[#34d399] text-black' : 'border-white/25 text-transparent')}>✓</span>
                  <span className={cn('text-[13px]', done[i] ? 'text-[#6b675c] line-through' : 'text-[#d7d3c8]')}>{tip}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <p className="mt-5 font-display text-[19px] italic text-white">— vansh chaurasia</p>
      </div>
      <div className="sticky bottom-0 mt-4 flex gap-2 bg-[#0a0a0c] py-2">
        <Link to="/" className="pressable flex min-h-[52px] flex-1 items-center justify-center gap-1.5 rounded-2xl border border-white/15 bg-white/[0.06] font-display text-[15px] font-semibold text-white"><Home size={17} /> Home</Link>
        <Link to="/history" className="pressable flex min-h-[52px] flex-1 items-center justify-center gap-1.5 rounded-2xl btn-primary font-display text-[15px] font-semibold text-white"><History size={17} /> History</Link>
      </div>
    </div>
  );
}

// ---------------- Legal ----------------
const TERMS = [
  { t: 'Acceptance', d: 'By using Finora you agree to these terms. Finora is a research tool for informational purposes.' },
  { t: 'Not Investment Advice', d: 'Nothing in Finora is investment, legal or tax advice. Always do your own due diligence and consult a licensed professional.' },
  { t: 'Data Sources & Accuracy', d: 'Data comes from SEC EDGAR, licensed feeds and public sources. We verify rigorously but cannot guarantee completeness or timeliness.' },
  { t: 'Accounts & Usage', d: 'Free accounts receive 5 researches per 24 hours. You are responsible for keeping your credentials safe.' },
  { t: 'Changes', d: 'We may update these terms; continued use constitutes acceptance. Last updated October 2026.' },
];
const PRIVACY = [
  { t: 'Overview', d: 'Finora collects the minimum needed to run your account: name, email, research history and usage counters.' },
  { t: 'Information Collected', d: 'Account details you provide, researches you run, chats with Finora AI, and basic device diagnostics.' },
  { t: 'Use', d: 'Your data powers your dashboard, history and quota. We never sell personal data.' },
  { t: 'Retention', d: 'Research history is kept while your account is active. You can request deletion anytime via support.' },
];

export function LegalPage({ kind }: { kind: 'terms' | 'privacy' }) {
  const articles = kind === 'terms' ? TERMS : PRIVACY;
  return (
    <div className="px-5 pb-10 pt-6">
      <p className="mono-label anim-rise text-[#ff8a3d]">Legal</p>
      <h1 className="anim-rise mt-1 font-display text-[26px] font-bold text-white">{kind === 'terms' ? 'Terms of Service' : 'Privacy Policy'}</h1>
      <p className="mt-1 font-mono text-[11px] text-[#6b675c]">Last updated · October 2026</p>
      <div className="mt-5 space-y-3">
        {articles.map((a, i) => (
          <article key={a.t} id={`art-${i + 1}`} className="card-dark anim-rise p-4" style={{ animationDelay: `${i * 0.05}s` }}>
            <p className="num font-mono text-[12px] text-[#ff8a3d]">Article {i + 1}</p>
            <h2 className="mt-0.5 font-display text-[17px] font-semibold text-white">{a.t}</h2>
            <p className="mt-1.5 text-[15px] leading-[22px] text-[#a7a29a]">{a.d}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

// ---------------- 404 ----------------
export function NotFoundPage() {
  return (
    <div className="grid-glow flex min-h-full flex-col items-center justify-center px-8 py-16 text-center">
      <p className="anim-pop font-display text-[88px] font-bold leading-none text-white">404</p>
      <div className="rays anim-fade pointer-events-none absolute h-64 w-64 rounded-full" aria-hidden />
      <p className="anim-rise mt-2 font-display text-[20px] font-semibold text-white">This page didn&apos;t file.</p>
      <p className="anim-rise mt-1 text-[14px] text-[#a7a29a]">Even the SEC loses paperwork sometimes.</p>
      <Link to="/research" className="btn-primary pressable anim-rise mt-6 flex min-h-[56px] w-full items-center justify-center rounded-2xl font-display text-[15px] font-semibold text-white">
        Back to Research
      </Link>
      <Link to="/" className="pressable mt-2 flex min-h-[48px] items-center text-sm text-[#a7a29a]">or go Home</Link>
    </div>
  );
}

// ---------------- More ----------------
export function MoreScreen() {
  const [canInstall, setCanInstall] = useState(false);
  useEffect(() => {
    const fn = (e: Event) => {
      e.preventDefault();
      setCanInstall(true);
      (window as unknown as { __finoraInstall?: Event }).__finoraInstall = e;
    };
    window.addEventListener('beforeinstallprompt', fn);
    return () => window.removeEventListener('beforeinstallprompt', fn);
  }, []);

  const rows: { label: string; sub?: string; to?: string; icon: typeof Home; action?: () => void }[] = [
    ...(isAuthed() ? [{ label: 'History', to: '/history', icon: History }] : []),
    { label: 'About', to: '/about', icon: FileText },
    { label: 'Methodology', to: '/methodology', icon: ShieldCheck },
    { label: 'Reviews', to: '/reviews', icon: Star },
    { label: 'Developer Letter', to: '/limit', icon: PenLine },
    { label: 'Terms', to: '/terms', icon: FileText },
    { label: 'Privacy', to: '/privacy', icon: ShieldCheck },
  ];

  return (
    <div className="px-5 pb-10 pt-6">
      <h1 className="anim-rise font-display text-[26px] font-bold text-white">More</h1>
      <div className="anim-rise stagger-1 mt-4 overflow-hidden rounded-2xl border border-white/10">
        {rows.map((r) => (
          <Link key={r.label} to={r.to!} className="pressable flex min-h-[56px] items-center gap-3 border-b border-white/[0.06] bg-[#14151a] px-4 last:border-0">
            <r.icon size={18} className="shrink-0 text-[#ff8a3d]" />
            <span className="flex-1 text-[15px] font-medium text-white">{r.label}</span>
            <ChevronRight size={17} className="text-[#6b675c]" />
          </Link>
        ))}
      </div>

      <div className="anim-rise stagger-2 mt-3 space-y-2">
        <button className="pressable flex min-h-[56px] w-full items-center gap-3 rounded-2xl border border-white/10 bg-[#14151a] px-4" onClick={() => { if ('Notification' in window) void Notification.requestPermission(); }}>
          <Bell size={18} className="shrink-0 text-[#ff8a3d]" />
          <span className="flex-1 text-left text-[15px] font-medium text-white">Research alerts</span>
          <span className="font-mono text-[11px] text-[#6b675c]">OFF</span>
        </button>
        {canInstall && (
          <button
            className="pressable flex min-h-[56px] w-full items-center gap-3 rounded-2xl border border-[#ff5a1f]/40 bg-[#ff5a1f]/[0.08] px-4"
            onClick={() => {
              const ev = (window as unknown as { __finoraInstall?: { prompt: () => void } }).__finoraInstall;
              ev?.prompt();
            }}
          >
            <Download size={18} className="shrink-0 text-[#ff8a3d]" />
            <span className="flex-1 text-left text-[15px] font-medium text-white">Install Finora app</span>
          </button>
        )}
      </div>

      <div className="anim-rise stagger-3 mt-6 rounded-2xl border border-white/10 bg-white/[0.02] p-4 text-center">
        <SourceStamp />
        <p className="mt-2 text-[13px] leading-5 text-[#a7a29a]">Who We Are — a small team obsessed with verifiable finance.</p>
        <p className="mt-1 font-mono text-[10px] text-[#6b675c]">Finora v2.0 · Build mobile</p>
      </div>
    </div>
  );
}

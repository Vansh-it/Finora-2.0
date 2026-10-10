import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, BadgeCheck, ChevronDown, FileText, Flame, LineChart, Play, Sigma, Star, Zap } from 'lucide-react';
import { ResearchInput } from '../components/ResearchInput';
import { EditorialHeading, HighlightText, Skeleton, SourceStamp, Stars, TickerChip } from '../components/ui';
import { useCachedQuery, useReveal } from '../hooks/hooks';
import { getReviews } from '../lib/api';
import type { Review } from '../lib/data';

const SOURCES = ['SEC EDGAR', 'Company IR', 'Twelve Data', 'Finora AI'];

const DOC_CARDS = [
  { tag: '10-K · FY2024', title: '$398.8B revenue', sub: 'Audited · XBRL us-gaap:Revenues', icon: FileText },
  { tag: 'FORMULA', title: 'ROIC = NOPAT ÷ Capital', sub: 'Computed in Python · 28.4%', icon: Sigma },
  { tag: 'AAPL · $231.40', title: '+2.4% today', sub: 'Live market feed', icon: LineChart },
  { tag: 'VERDICT', title: 'SEC Verified', sub: '9 sources · 7 cross-verified', icon: BadgeCheck },
  { tag: 'FORENSICS', title: 'F-Score 8/9', sub: 'Altman Z 4.1 · Beneish −2.4', icon: Flame },
];

const STEPS = [
  { n: '01', t: 'Identify', d: 'Resolve the company to its exact SEC registrant — no ticker mix-ups.' },
  { n: '02', t: 'Read', d: 'Parse 10-K / 10-Q filings, footnotes and MD&A end to end.' },
  { n: '03', t: 'Normalize', d: 'Map every line to standard XBRL concepts across periods.' },
  { n: '04', t: 'Calculate', d: 'Run 48+ metrics in Python — deterministic, re-runnable.' },
  { n: '05', t: 'Verify', d: 'Cross-check against 9 sources; flag every mismatch.' },
  { n: '06', t: 'Explain', d: 'Finora AI writes the memo — interpretation only, never fabrication.' },
];

const FAQS = [
  { q: 'Is Finora investment advice?', a: 'No. Finora is a research tool. It shows you what the filings say, how each number was computed, and where it was verified — decisions stay with you.' },
  { q: 'Where do the numbers come from?', a: 'SEC EDGAR is the factual authority. Market prices come from Twelve Data and company IR. Every metric links to its formula, inputs and source filing.' },
  { q: 'What does the free tier include?', a: '5 full researches every 24 hours — each with the 9-tab dashboard, evidence receipts, chat and Excel export.' },
  { q: 'How does the AI avoid hallucinating?', a: 'The AI only writes explanations over pre-computed, verified values. It cannot invent numbers — if data is missing, Finora says so with the reason.' },
];

export function HomePage() {
  const ref = useReveal<HTMLDivElement>();
  const [dots, setDots] = useState(0);
  const [metricOpen, setMetricOpen] = useState(false);
  const [faq, setFaq] = useState(0);
  const reviews = useCachedQuery<Review[]>('reviews', async () => getReviews(), { ttlMs: 60_000 });
  const hasReviews = (reviews.data?.length ?? 0) > 0;

  return (
    <div ref={ref} className="grid-glow pb-10">
      {/* corner labels like reference art */}
      <div className="flex items-start justify-between px-5 pt-4">
        <p className="mono-label text-left text-[#a7a29a]">Performance<br /><span className="font-semibold text-white">Analytics</span></p>
        <p className="mono-label text-right text-[#a7a29a]"><span className="font-semibold text-white">Evidence-traced</span><br />Reports</p>
      </div>

      {/* HERO */}
      <section className="px-5 pt-6">
        <div data-reveal>
          <span className="annotation-tag">AI financial research</span>
        </div>
        <h1 data-reveal className="mt-3 font-display text-[34px] font-bold leading-[38px] tracking-tight text-white">
          Research the company.<br /><HighlightText>Verify the numbers.</HighlightText>
        </h1>
        <p data-reveal className="mt-3 text-[15px] leading-[22px] text-[#d7d3c8]">
          Finora reads SEC filings, calculates in Python, verifies across 9 sources — and shows a receipt for every number.
        </p>
        <div data-reveal className="relative z-20 mt-5">
          <ResearchInput large />
        </div>
        <div data-reveal className="snap-row mt-4" role="list" aria-label="Data sources">
          {SOURCES.map((s) => (
            <span key={s} role="listitem" className="flex min-h-[44px] items-center rounded-full border border-white/12 bg-white/[0.04] px-4 font-mono text-[11px] tracking-wider text-[#d7d3c8]">
              <span className="mr-2 h-1.5 w-1.5 rounded-full bg-[#ff5a1f]" />{s}
            </span>
          ))}
        </div>
      </section>

      {/* DOC COLLAGE CAROUSEL */}
      <section className="mt-8" aria-label="Research desk preview">
        <div className="px-5"><EditorialHeading kicker="Live desk" title="A research file, in seconds" /></div>
        <div
          className="snap-row mt-4 px-5"
          onScroll={(e) => {
            const el = e.currentTarget;
            const i = Math.round(el.scrollLeft / (el.scrollWidth / DOC_CARDS.length));
            setDots(Math.min(DOC_CARDS.length - 1, Math.max(0, i)));
          }}
        >
          {DOC_CARDS.map((c) => (
            <div key={c.title} data-reveal className="card-dark w-[78vw] max-w-[300px] p-4">
              <div className="flex items-center justify-between">
                <span className="mono-label text-[#ff8a3d]">{c.tag}</span>
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#ff5a1f]/12"><c.icon size={17} className="text-[#ff8a3d]" /></span>
              </div>
              <p className="mt-3 font-display text-[19px] font-semibold text-white">{c.title}</p>
              <p className="mt-1 font-mono text-[11px] text-[#a7a29a]">{c.sub}</p>
            </div>
          ))}
        </div>
        <div className="mt-3 flex justify-center gap-1.5" aria-hidden>
          {DOC_CARDS.map((_, i) => (
            <span key={i} className={`h-1.5 rounded-full transition-all ${i === dots ? 'w-5 bg-[#ff5a1f]' : 'w-1.5 bg-white/20'}`} />
          ))}
        </div>
      </section>

      {/* TIMELINE */}
      <section className="mt-10 px-5" aria-label="How Finora thinks">
        <EditorialHeading kicker="Method" title="How Finora thinks" />
        <ol className="relative mt-5 space-y-1 border-l-2 border-[#ff5a1f]/30 pl-0">
          {STEPS.map((s) => (
            <li key={s.n} data-reveal className="relative flex gap-3 pb-5 pl-5">
              <span className="absolute -left-[9px] top-1 flex h-4 w-4 items-center justify-center rounded-full border-2 border-[#ff5a1f] bg-[#0a0a0c]" aria-hidden>
                <span className="h-1.5 w-1.5 rounded-full bg-[#ff5a1f]" />
              </span>
              <div className="card-dark flex-1 p-3.5">
                <p className="font-mono text-[11px] text-[#ff8a3d]">{s.n}</p>
                <h3 className="font-display text-[16px] font-semibold text-white">{s.t}</h3>
                <p className="mt-0.5 text-[13px] leading-[18px] text-[#a7a29a]">{s.d}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* ANIMATED METRIC DEMO */}
      <section className="mt-6 px-5" aria-label="Every number has a receipt">
        <EditorialHeading kicker="Promise" title={<>Every number has<br />a receipt</>} />
        <button
          data-reveal
          onClick={() => setMetricOpen(!metricOpen)}
          aria-expanded={metricOpen}
          className="card-dark pressable mt-4 w-full p-4 text-left"
          style={metricOpen ? { borderColor: 'rgba(255,90,31,0.5)', boxShadow: '0 0 0 1px rgba(255,90,31,.35), 0 12px 32px rgba(0,0,0,.45)' } : undefined}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="mono-label text-[#a7a29a]">AAPL · FY2024 · tap me</p>
              <p className="num mt-1 text-[26px] font-semibold text-white">$398.8B <span className="text-[14px] font-normal text-[#a7a29a]">revenue</span></p>
            </div>
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-[#ff5a1f] text-white" style={{ animation: 'pulse-glow 2s infinite' }}>
              <Play size={17} fill="currentColor" />
            </span>
          </div>
          <div className={`grid transition-all duration-300 ${metricOpen ? 'mt-3 grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}>
            <div className="overflow-hidden">
              <div className="space-y-2 rounded-xl border border-white/10 bg-black/40 p-3">
                <p className="num text-[12px] text-[#ffb25c]">Revenue = Σ quarterly reported revenue</p>
                <p className="font-mono text-[11px] text-[#a7a29a]">Q1 $97.2B · Q2 $99.8B · Q3 $98.1B · Q4 $103.7B</p>
                <p className="font-mono text-[11px] text-[#7ab8ff]">us-gaap:Revenues · 10-K filed 2024-11-01</p>
                <SourceStamp text="Cross-verified · 7" />
              </div>
            </div>
          </div>
        </button>
        <Link to="/research" data-reveal className="btn-primary pressable mt-3 flex min-h-[52px] items-center justify-center gap-2 rounded-2xl font-display text-[15px] font-semibold text-white">
          See a live dashboard <ArrowRight size={17} />
        </Link>
      </section>

      {/* REVIEWS */}
      <section className="mt-10" aria-label="Reviews">
        <div className="px-5">
          <EditorialHeading kicker={hasReviews ? 'Loved by analysts' : 'Your turn'} title="Reviews" right={<Link to="/reviews" className="flex min-h-[44px] items-center font-mono text-[11px] tracking-wider text-[#ff8a3d]">VIEW ALL</Link>} />
        </div>
        {reviews.loading && !reviews.data ? (
          <div className="snap-row mt-4 px-5">
            {[0, 1].map((i) => <Skeleton key={i} className="h-[140px] w-[78vw] max-w-[300px]" />)}
          </div>
        ) : hasReviews ? (
          <div className="snap-row mt-4 px-5">
            {reviews.data!.map((r) => (
              <figure key={r.id} data-reveal className="card-dark w-[78vw] max-w-[300px] p-4">
                <Stars value={r.stars} />
                <blockquote className="mt-2 line-clamp-3 text-[14px] leading-6 text-[#d7d3c8]">“{r.text}”</blockquote>
                <figcaption className="mt-2 flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#ff5a1f]/15 font-display text-[13px] font-semibold text-[#ff8a3d]">{r.name[0]?.toUpperCase()}</span>
                  <span className="text-[13px] font-medium text-white">{r.name}</span>
                  {r.company && <TickerChip ticker={r.company} />}
                </figcaption>
              </figure>
            ))}
          </div>
        ) : (
          <div className="px-5 pt-4">
            <div data-reveal className="card-dark p-5 text-center">
              <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[#ff5a1f]/15">
                <Star size={22} className="text-[#ff8a3d]" fill="#ff8a3d" />
              </span>
              <h3 className="mt-3 font-display text-[17px] font-bold text-white">Be the first to review Finora</h3>
              <p className="mt-1.5 text-[14px] leading-6 text-[#a7a29a]">Reviews help the next analyst find us — and it takes no time. Rate your research and say what you verified.</p>
              <Link to="/reviews" className="btn-primary pressable mt-4 flex min-h-[52px] items-center justify-center gap-2 rounded-2xl font-display text-[15px] font-semibold text-white">
                <Star size={17} /> Write a review
              </Link>
            </div>
          </div>
        )}
      </section>

      {/* FAQ */}
      <section className="mt-10 px-5" aria-label="FAQ">
        <EditorialHeading kicker="Questions" title="Finora, explained" />
        <div className="mt-4 space-y-2">
          {FAQS.map((f, i) => {
            const open = faq === i;
            return (
              <div key={f.q} data-reveal className="overflow-hidden rounded-2xl border border-white/10 bg-[#14151a]">
                <button
                  onClick={() => setFaq(open ? -1 : i)}
                  aria-expanded={open}
                  className="flex min-h-[52px] w-full items-center justify-between gap-3 px-4 text-left text-[15px] font-medium text-white"
                >
                  {f.q}
                  <ChevronDown size={18} className={`shrink-0 text-[#ff8a3d] transition-transform ${open ? 'rotate-180' : ''}`} />
                </button>
                <div className={`grid transition-all duration-250 ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
                  <p className="overflow-hidden px-4 text-[14px] leading-6 text-[#a7a29a]">{open ? f.a : ''}<span className={open ? 'block h-4' : ''} /></p>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* PRINCIPLES STRIP */}
      <section className="mt-8 px-5" aria-label="Principles">
        <div data-reveal className="grid grid-cols-3 gap-2">
          {[
            { icon: BadgeCheck, t: 'SEC = authority', d: 'Facts' },
            { icon: Sigma, t: 'Python = engine', d: 'Math' },
            { icon: Zap, t: 'AI = insight', d: 'Words' },
          ].map((p) => (
            <div key={p.t} className="card-dark flex flex-col items-center p-3 text-center">
              <p.icon size={18} className="text-[#ff8a3d]" />
              <p className="mt-1.5 font-mono text-[10px] uppercase tracking-wider text-white">{p.t}</p>
              <p className="font-mono text-[10px] text-[#6b675c]">{p.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* MINI FOOTER */}
      <footer className="mt-10 border-t border-white/10 px-5 pb-4 pt-6">
        <p className="font-display text-[17px] font-bold text-white">Finora<span className="text-[#ff5a1f]">.</span></p>
        <p className="mt-1 text-[13px] leading-5 text-[#a7a29a]">AI financial research with a receipt for every number.</p>
        <nav className="mt-3 flex flex-wrap gap-x-4 gap-y-2" aria-label="Footer">
          {[
            ['Privacy', '/privacy'], ['Terms', '/terms'], ['About', '/about'],
            ['Methodology', '/methodology'], ['Reviews', '/reviews'], ['Who We Are', '/more'],
          ].map(([label, to]) => (
            <Link key={to + label} to={to} className="flex min-h-[44px] items-center text-[13px] text-[#d7d3c8] underline-offset-4 active:underline">{label}</Link>
          ))}
        </nav>
        <p className="mt-2 font-mono text-[10px] text-[#6b675c]">© 2026 Finora · Not investment advice</p>
      </footer>
    </div>
  );
}

import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Building2, Search, X, Loader2 } from 'lucide-react';
import { suggestCompanies } from '../lib/api';
import { COMPANIES } from '../lib/data';
import type { CompanySuggestion } from '../lib/data';
import { isAuthed, setPendingTicker } from '../lib/auth';
import { TickerChip } from './ui';
import { cn } from '../lib/cn';

export function ResearchInput({ large, autoTicker }: { large?: boolean; autoTicker?: string }) {
  const nav = useNavigate();
  const [q, setQ] = useState(autoTicker ?? '');
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<CompanySuggestion[]>([]);
  const [active, setActive] = useState(-1);
  const ctrl = useRef<AbortController | null>(null);
  const timer = useRef<number>(0);
  const boxId = useRef(`ri-${Math.random().toString(36).slice(2)}`).current;

  useEffect(() => {
    window.clearTimeout(timer.current);
    ctrl.current?.abort();
    if (!q.trim()) {
      setResults([]);
      setOpen(false);
      setLoading(false);
      return;
    }
    // instant local fallback
    const needle = q.trim().toLowerCase();
    setResults(COMPANIES.filter((c) => c.ticker.toLowerCase().includes(needle) || c.name.toLowerCase().includes(needle)).slice(0, 6));
    setOpen(true);
    setLoading(true);
    timer.current = window.setTimeout(async () => {
      const c = new AbortController();
      ctrl.current = c;
      try {
        const r = await suggestCompanies(q, c.signal);
        if (!c.signal.aborted) {
          setResults(r);
          setOpen(true);
        }
      } catch { /* keep local */ } finally {
        if (!c.signal.aborted) setLoading(false);
      }
    }, 250);
    return () => {
      window.clearTimeout(timer.current);
      ctrl.current?.abort();
    };
  }, [q]);

  const submit = (ticker: string) => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setOpen(false);
    if (!isAuthed()) {
      setPendingTicker(t);
      nav('/auth', { state: { ticker: t } });
    } else {
      nav(`/research?ticker=${encodeURIComponent(t)}`);
    }
  };

  return (
    <div className="relative z-30">
      <div
        className={cn(
          'flex items-center gap-2 rounded-2xl border border-white/15 bg-black/50 pl-4 pr-2 backdrop-blur transition-shadow focus-within:border-[#ff5a1f]/70 focus-within:shadow-[0_0_0_1px_rgba(255,90,31,0.4),0_8px_32px_rgba(255,90,31,0.2)]',
          large ? 'min-h-[60px]' : 'min-h-[56px]',
        )}
      >
        <Search size={20} className="shrink-0 text-[#ff8a3d]" />
        <input
          role="combobox"
          aria-expanded={open}
          aria-controls={`${boxId}-list`}
          aria-activedescendant={active >= 0 ? `${boxId}-opt-${active}` : undefined}
          aria-label="Search a company or ticker"
          value={q}
          onChange={(e) => { setQ(e.target.value); setActive(-1); }}
          onFocus={() => q.trim() && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(results.length - 1, a + 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(-1, a - 1)); }
            else if (e.key === 'Enter') { e.preventDefault(); submit(active >= 0 ? results[active].ticker : q); }
            else if (e.key === 'Escape') setOpen(false);
          }}
          placeholder="Try AAPL, Tesla, NVIDIA…"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="search"
          className="h-full min-h-[52px] w-full bg-transparent text-[16px] text-white outline-none placeholder:text-[#6b675c]"
        />
        {loading ? <Loader2 size={18} className="mr-2 shrink-0 animate-spin text-[#ff8a3d]" /> : q ? (
          <button aria-label="Clear search" onClick={() => setQ('')} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-[#a7a29a]">
            <X size={18} />
          </button>
        ) : null}
        <button
          onClick={() => submit(q)}
          aria-label="Research this company"
          className="btn-primary pressable hidden min-h-[44px] shrink-0 items-center rounded-xl px-4 font-display text-sm font-semibold text-white min-[360px]:flex"
        >
          Go
        </button>
      </div>

      {open && (
        <div className="anim-fade absolute inset-x-0 top-[calc(100%+8px)] z-50 overflow-hidden rounded-2xl border border-white/12 bg-[#14151a] shadow-[0_20px_50px_rgba(0,0,0,0.65)]">
          <ul role="listbox" id={`${boxId}-list`} aria-label="Company suggestions">
            {results.length === 0 && (
              <li className="px-4 py-4 text-sm text-[#a7a29a]">No matches — try the ticker symbol (e.g. AAPL).</li>
            )}
            {results.map((r, i) => (
              <li key={r.ticker} role="option" id={`${boxId}-opt-${i}`} aria-selected={i === active}>
                <button
                  onClick={() => submit(r.ticker)}
                  onMouseEnter={() => setActive(i)}
                  className={cn(
                    'flex min-h-[56px] w-full items-center gap-3 px-4 text-left transition-colors',
                    i === active ? 'bg-[#ff5a1f]/12' : 'active:bg-white/5',
                  )}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05]">
                    <Building2 size={16} className="text-[#ff8a3d]" />
                  </span>
                  <TickerChip ticker={r.ticker} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-medium text-white">{r.name}</span>
                    <span className="block font-mono text-[11px] text-[#6b675c]">{r.exchange}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

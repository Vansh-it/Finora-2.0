import { useState, useEffect, useRef, useCallback, type FormEvent } from "react";
import { ArrowRight, AlertCircle, Building2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import TickerChip from "./TickerChip";
import {
  RESEARCH_REGIONS,
  REGION_LABELS,
  REGION_EXCHANGES,
  researchRegionFromParam,
  type ResearchRegion,
} from "../lib/researchStages";

/**
 * Quick-pick companies per market.
 *
 * These are only offered when they can actually route. A US ticker list shown
 * while the user is in the India tab would send every one of those clicks into
 * the mismatch path, which is a worse experience than offering nothing.
 */
const QUICK_TICKERS: Record<ResearchRegion, string[]> = {
  US: ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
  INDIA: ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"],
};

interface Suggestion {
  ticker: string;
  name: string;
  exchange?: string;
  cik?: string;
  region?: ResearchRegion;
}

export default function ResearchInput({ region: regionProp }: { region?: ResearchRegion }) {
  const [region, setRegion] = useState<ResearchRegion>(regionProp ?? "US");
  const [value, setValue] = useState("");
  const [showError, setShowError] = useState(false);
  const [shaking, setShaking] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [isLoading, setIsLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const navigate = useNavigate();

  // Read inside the debounced fetch without making it a dependency, so changing
  // region does not rebuild the callback while a request is already in flight.
  const regionRef = useRef<ResearchRegion>(region);
  regionRef.current = region;

  // The parent owns the region when it is given one, so a region change higher up
  // (a query parameter, a route) is reflected here without a second source of
  // truth. Left uncontrolled, the selector drives it locally.
  useEffect(() => {
    if (regionProp) setRegion(regionProp);
  }, [regionProp]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const fetchSuggestions = useCallback(
    async (query: string, forRegion: ResearchRegion) => {
      if (query.length < 2) {
        setSuggestions([]);
        setShowSuggestions(false);
        return;
      }
      setIsLoading(true);
      try {
        // The region is sent as a search scope, not a label: the backend decides
        // which exchange universe to search, so an India tab never lists Nasdaq
        // tickers. Stale responses are dropped by region, so switching tabs mid
        // request cannot leave the previous market's suggestions on screen.
        const res = await fetch(
          `/api/company/suggest?q=${encodeURIComponent(query)}&region=${forRegion}&limit=8`
        );
        if (!res.ok) return;
        const data = await res.json();
        const items: Suggestion[] = Array.isArray(data) ? data : data.results || [];
        if (forRegion !== regionRef.current) return;
        setSuggestions(items);
        setShowSuggestions(items.length > 0);
        setSelectedIndex(-1);
      } catch {
        // Silently ignore autocomplete errors
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  function triggerError() {
    if (timerRef.current) clearTimeout(timerRef.current);
    setShowError(true);
    setShaking(true);
    setTimeout(() => setShaking(false), 500);
    timerRef.current = setTimeout(() => setShowError(false), 4000);
    inputRef.current?.focus();
  }

  function handleSubmit(e: FormEvent, tickerOverride?: string) {
    e.preventDefault();
    const query = tickerOverride || value.trim();
    if (!query) {
      triggerError();
      return;
    }
    // Region travels in the URL so it survives a refresh, a shared link, and the
    // hop to the processing page. Without it the selection would reset to the
    // default and a deliberately India-scoped search would be answered as a US one.
    navigate(`/research?ticker=${encodeURIComponent(query)}&region=${region}`);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!showSuggestions || suggestions.length === 0) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev < suggestions.length - 1 ? prev + 1 : 0
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev > 0 ? prev - 1 : suggestions.length - 1
        );
        break;
      case "Enter":
        if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
          e.preventDefault();
          const s = suggestions[selectedIndex];
          setValue(s.ticker || s.name);
          setShowSuggestions(false);
          handleSubmit(e, s.ticker || s.name);
        }
        break;
      case "Escape":
        setShowSuggestions(false);
        setSelectedIndex(-1);
        break;
    }
  }

  return (
    <div className="w-full relative">
      <form
        onSubmit={handleSubmit}
        className={`relative flex flex-col gap-3 border-2 bg-paper p-2 shadow-[6px_6px_0_0_#111111] transition-shadow duration-300 sm:flex-row sm:items-center sm:gap-0 ${
          showError
            ? "border-red-500 shadow-[6px_6px_0_0_#ef4444]"
            : "border-ink"
        } ${shaking ? "animate-[shake_0.5s_ease-in-out]" : ""}`}
      >
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => {
            const v = e.target.value;
            setValue(v);
            if (showError) setShowError(false);

            // Debounced autocomplete, scoped to the market currently selected
            if (debounceRef.current) clearTimeout(debounceRef.current);
            debounceRef.current = setTimeout(
              () => fetchSuggestions(v, region),
              250
            );
          }}
          onFocus={() => {
            if (suggestions.length > 0) setShowSuggestions(true);
          }}
          onKeyDown={handleKeyDown}
          placeholder={
            region === "INDIA"
              ? "Research Reliance, TCS, HDFC Bank..."
              : "Research Microsoft, Apple, Walmart..."
          }
          aria-label={`Research a ${REGION_LABELS[region]} company`}
          aria-autocomplete="list"
          aria-expanded={showSuggestions}
          aria-activedescendant={selectedIndex >= 0 ? `suggestion-${selectedIndex}` : undefined}
          role="combobox"
          className="w-full flex-1 bg-transparent px-4 py-4 font-sans text-base text-ink placeholder:text-ink-3 focus:outline-none sm:text-lg"
        />
        <button
          type="submit"
          className="flex items-center justify-center gap-2 whitespace-nowrap bg-ink px-6 py-4 font-mono text-xs font-bold tracking-[0.15em] text-paper uppercase transition-colors hover:bg-ink-2"
        >
          Start Research
          <ArrowRight size={15} />
        </button>
      </form>

      {/* Autocomplete dropdown */}
      {showSuggestions && suggestions.length > 0 && (
        <div
          ref={dropdownRef}
          role="listbox"
          aria-label="Company suggestions"
          className="absolute z-50 mt-1 w-full border-2 border-ink bg-paper shadow-[4px_4px_0_0_#111111] overflow-hidden"
        >
          {suggestions.map((s, i) => (
            <div
              key={`${s.ticker}-${i}`}
              id={`suggestion-${i}`}
              role="option"
              aria-selected={i === selectedIndex}
              className={`flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors ${
                i === selectedIndex
                  ? "bg-ink text-paper"
                  : "hover:bg-ink-5 text-ink"
              } ${i > 0 ? "border-t border-ink-10" : ""}`}
              onClick={(e) => {
                setValue(s.ticker || s.name);
                setShowSuggestions(false);
                handleSubmit(e, s.ticker || s.name);
              }}
              onMouseEnter={() => setSelectedIndex(i)}
            >
              <Building2 size={14} className={i === selectedIndex ? "text-paper-3" : "text-ink-3"} />
              <div className="flex-1 min-w-0">
                <div className="font-sans text-sm font-semibold truncate">
                  {s.name}
                </div>
              </div>
              <div className={`flex items-center gap-2 shrink-0 ${i === selectedIndex ? "text-paper-3" : "text-ink-3"}`}>
                <span className="font-mono text-xs font-bold">{s.ticker}</span>
                {s.exchange && (
                  <span className="font-mono text-[10px]">{s.exchange}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Market selector. Stated before the search box because it is a
          constraint on the search, not a filter applied to its results. */}
      <fieldset className="mt-3 border-2 border-ink-10 bg-paper-2 px-3 py-2">
        <legend className="sr-only">Research market</legend>
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-[10px] font-bold tracking-[0.2em] text-ink-3 uppercase">
            Market
          </span>
          <div className="flex gap-0" role="radiogroup" aria-label="Research market">
            {RESEARCH_REGIONS.map((r) => {
              const active = r === region;
              return (
                <button
                  key={r}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => {
                    if (r === region) return;
                    setRegion(r);
                    // Market changed under a typed query, so the suggestions for
                    // the previous market are stale by definition.
                    setSuggestions([]);
                    setShowSuggestions(false);
                    setSelectedIndex(-1);
                    if (value.trim().length >= 2) fetchSuggestions(value, r);
                  }}
                  className={`border-2 px-4 py-1.5 font-mono text-[11px] font-bold tracking-[0.1em] uppercase transition-colors ${
                    active
                      ? "border-ink bg-ink text-paper"
                      : "border-transparent text-ink-3 hover:border-ink/20 hover:text-ink"
                  }`}
                >
                  {REGION_LABELS[r]}
                </button>
              );
            })}
          </div>
          <span className="font-mono text-[10px] text-ink-3">
            {REGION_EXCHANGES[region]}
          </span>
        </div>
      </fieldset>

      {/* Premium validation toast */}
      <div
        className={`overflow-hidden transition-all duration-300 ease-out ${
          showError ? "mt-3 max-h-20 opacity-100" : "mt-0 max-h-0 opacity-0"
        }`}
      >
        <div className="flex items-center gap-3 border border-red-200 bg-gradient-to-r from-red-50 to-orange-50 px-4 py-3 shadow-sm">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-red-500/10">
            <AlertCircle size={16} className="text-red-500" />
          </div>
          <div className="flex-1">
            <p className="font-sans text-sm font-semibold text-red-700">
              Company name or ticker required
            </p>
            <p className="mt-0.5 font-sans text-xs text-red-500/80">
              Enter a company name or ticker symbol to begin your research.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setShowError(false);
              inputRef.current?.focus();
            }}
            className="shrink-0 rounded border border-red-200 bg-white px-3 py-1.5 font-mono text-[10px] font-bold tracking-[0.1em] text-red-600 uppercase transition-colors hover:bg-red-50"
          >
            Dismiss
          </button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="mr-1 font-mono text-[10px] font-bold tracking-[0.2em] text-ink-3 uppercase">Try:</span>
        {QUICK_TICKERS[region].map((t) => (
          <TickerChip key={t} ticker={t} onClick={() => {
            navigate(`/research?ticker=${encodeURIComponent(t)}&region=${region}`);
          }} />
        ))}
      </div>
    </div>
  );
}

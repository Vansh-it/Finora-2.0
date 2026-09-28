import { useState, useEffect, useRef, useCallback, type FormEvent } from "react";
import { ArrowRight, AlertCircle, Search, Building2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import TickerChip from "./TickerChip";

const QUICK_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"];

interface Suggestion {
  ticker: string;
  name: string;
  exchange?: string;
  cik?: string;
}

export default function ResearchInput() {
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

  const fetchSuggestions = useCallback(async (query: string) => {
    if (query.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    setIsLoading(true);
    try {
      const res = await fetch(`/api/company/suggest?q=${encodeURIComponent(query)}&limit=8`);
      if (res.ok) {
        const data = await res.json();
        // Handle both {results: [...]} and [...] response formats
        const items = Array.isArray(data) ? data : (data.results || []);
        setSuggestions(items);
        setShowSuggestions(items.length > 0);
        setSelectedIndex(-1);
      }
    } catch {
      // Silently ignore autocomplete errors
    } finally {
      setIsLoading(false);
    }
  }, []);

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
    // If it looks like a ticker (1-5 uppercase letters), use as ticker
    // Otherwise use as search query
    const isTicker = /^[A-Za-z]{1,5}$/.test(query);
    if (isTicker) {
      navigate(`/research?ticker=${query.toUpperCase()}`);
    } else {
      navigate(`/research?ticker=${encodeURIComponent(query)}`);
    }
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

            // Debounced autocomplete
            if (debounceRef.current) clearTimeout(debounceRef.current);
            debounceRef.current = setTimeout(() => fetchSuggestions(v), 250);
          }}
          onFocus={() => {
            if (suggestions.length > 0) setShowSuggestions(true);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Research Microsoft, Apple, Walmart..."
          aria-label="Research a company"
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
        {QUICK_TICKERS.map((t) => (
          <TickerChip key={t} ticker={t} onClick={() => {
            navigate(`/research?ticker=${t}`);
          }} />
        ))}
      </div>
    </div>
  );
}

import { useEffect, useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import EditorialHeading from "../components/EditorialHeading";
import Annotation from "../components/Annotation";
import { cn } from "../utils/cn";
import { runResearch } from "../lib/api";

const STAGES = [
  { key: "company", title: "Entity Identified", detail: "Resolved company name to CIK and primary exchange listing." },
  { key: "filings", title: "SEC Filings Located", detail: "Located most recent 10-K, 10-Q and 8-K filings via EDGAR." },
  { key: "financials", title: "Financial Statements", detail: "Extracting income statement, balance sheet & cash flow from XBRL." },
  { key: "metrics", title: "Metrics Calculated", detail: "Deriving profitability, growth, efficiency and valuation metrics." },
  { key: "sources", title: "Sources Discovered", detail: "Searching for authoritative company financial sources." },
  { key: "verify", title: "Source Verification", detail: "Cross-checking figures against external sources." },
  { key: "summary", title: "Analysis Generated", detail: "Generating the executive research memo." },
  { key: "valuation", title: "Valuation Complete", detail: "Fetching market data and calculating valuation multiples." },
  { key: "complete", title: "Research File Complete", detail: "Assembling the final research record." },
];

type StageStatus = "pending" | "active" | "done" | "error";

export default function ResearchProcessingPage() {
  const [params] = useSearchParams();
  const ticker = (params.get("ticker") || "AAPL").toUpperCase();
  const navigate = useNavigate();
  const [stageStatuses, setStageStatuses] = useState<StageStatus[]>(
    () => STAGES.map(() => "pending" as StageStatus)
  );
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const startedRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    // Start elapsed timer
    timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);

    async function run() {
      try {
        // Animate stages as the pipeline runs
        // Stage 0: immediately show as active
        updateStage(0, "active");

        const result = await runResearch(ticker, "latest");

        // Stop timer
        if (timerRef.current) clearInterval(timerRef.current);

        if (result.status === "error") {
          setErrorMsg(result.error || "Research pipeline failed");
          // Mark current stage as error
          setStageStatuses((prev) => {
            const idx = prev.findIndex((s) => s === "active");
            if (idx >= 0) prev[idx] = "error";
            return [...prev];
          });
          return;
        }

        // Mark all stages as done
        setStageStatuses(STAGES.map(() => "done" as StageStatus));

        // Navigate to dashboard after short delay
        setTimeout(() => {
          navigate(`/dashboard?session_id=${result.session_id}`);
        }, 800);
      } catch (err) {
        if (timerRef.current) clearInterval(timerRef.current);
        const msg = err instanceof Error ? err.message : "Could not connect to the Finora backend.";
        setErrorMsg(msg);
        setStageStatuses((prev) => {
          const idx = prev.findIndex((s) => s === "active");
          if (idx >= 0) prev[idx] = "error";
          return [...prev];
        });
      }
    }

    run();

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [ticker, navigate]);

  function updateStage(index: number, status: StageStatus) {
    setStageStatuses((prev) => {
      const next = [...prev];
      next[index] = status;
      return next;
    });
  }

  return (
    <div className="mx-auto min-h-[80vh] max-w-3xl px-4 py-16 sm:px-6 lg:px-0">
      <p className="font-mono text-xs font-semibold tracking-[0.3em] text-ink-3 uppercase">
        Research in progress
      </p>
      <EditorialHeading className="mt-4" size="md">
        Building
        <br />
        the research file.
      </EditorialHeading>

      <div className="mt-8 flex items-center gap-4 border border-ink/20 bg-paper p-4">
        <div className="flex h-10 w-10 items-center justify-center border border-ink font-mono text-sm font-bold">
          {ticker.slice(0, 2)}
        </div>
        <div>
          <div className="font-serif text-lg font-semibold text-ink uppercase">{ticker}</div>
          <Annotation label="NASDAQ" value={ticker} />
        </div>
        {elapsed > 0 && (
          <div className="ml-auto font-mono text-xs text-ink-3">{elapsed}s</div>
        )}
      </div>

      {errorMsg && (
        <div className="mt-6 border-2 border-red-500 bg-red-50 p-4">
          <p className="font-mono text-sm font-bold text-red-700">Error</p>
          <p className="mt-1 text-sm text-red-600">{errorMsg}</p>
          <button
            onClick={() => navigate("/research")}
            className="mt-3 font-mono text-xs font-bold text-red-700 underline hover:text-red-900"
          >
            ← Back to Research
          </button>
        </div>
      )}

      <div className="mt-10 space-y-0">
        {STAGES.map((stage, i) => {
          const status = stageStatuses[i];
          const done = status === "done";
          const active = status === "active";
          const error = status === "error";

          return (
            <div key={stage.key} className="relative flex gap-4 pb-8 last:pb-0">
              {i < STAGES.length - 1 && (
                <div className="absolute top-8 left-[15px] h-full w-px bg-ink/15">
                  <div
                    className={cn(
                      "w-px bg-highlight transition-all duration-500",
                      done ? "h-full" : "h-0"
                    )}
                  />
                </div>
              )}
              <div
                className={cn(
                  "z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 font-mono text-xs font-bold transition-colors",
                  done && "border-ink bg-ink text-paper",
                  active && "border-annotate-blue text-annotate-blue",
                  error && "border-red-500 bg-red-500 text-white",
                  !done && !active && !error && "border-ink/25 text-ink-3"
                )}
              >
                {done ? (
                  <CheckCircle2 size={16} />
                ) : active ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : error ? (
                  <XCircle size={16} />
                ) : (
                  i + 1
                )}
              </div>
              <div
                className={cn(
                  "pt-0.5 transition-opacity",
                  !done && !active && !error && "opacity-40"
                )}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "font-mono text-[10px] font-bold tracking-widest uppercase",
                      done ? "text-ink-3" : active ? "text-annotate-blue" : error ? "text-red-500" : "text-ink-3"
                    )}
                  >
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <h3
                    className={cn(
                      "font-serif text-lg font-semibold text-ink",
                      done && "relative"
                    )}
                  >
                    {stage.title}
                    {done && (
                      <span
                        className="mark-highlight absolute inset-0 -z-10 block"
                        aria-hidden
                      />
                    )}
                  </h3>
                  {active && (
                    <span className="font-mono text-xs text-annotate-blue">
                      processing...
                    </span>
                  )}
                  {error && (
                    <span className="font-mono text-xs text-red-500">failed</span>
                  )}
                </div>
                <p className="mt-1 text-sm text-ink-2">{stage.detail}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

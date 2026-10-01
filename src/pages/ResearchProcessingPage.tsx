import { useEffect, useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import EditorialHeading from "../components/EditorialHeading";
import Annotation from "../components/Annotation";
import { cn } from "../utils/cn";
import { runResearch } from "../lib/api";
import { researchIndia } from "../lib/indiaApi";
import { resolveRegion, type RegionRoute } from "../lib/regionRouter";
import {
  exchangeLabelForRegion,
  identifierForRoute,
  nameForRoute,
  stagesForRegion,
  type ResearchStage,
} from "../lib/researchStages";

type StageStatus = "pending" | "active" | "done" | "error";

/**
 * The region route is the only thing that decides which pipeline runs. Until it
 * answers, the screen shows no market-specific wording at all: naming NASDAQ,
 * EDGAR or 10-K before the company is known is exactly the wrong claim to make
 * about an Indian company.
 */
const PENDING_STAGES: ResearchStage[] = [
  {
    key: "routing",
    title: "Resolving Company",
    detail: "Locating the company on its listing exchange to select the right research pipeline.",
  },
];

export default function ResearchProcessingPage() {
  const [params] = useSearchParams();
  const query = (params.get("ticker") || params.get("query") || "AAPL").trim();
  const navigate = useNavigate();
  const [stages, setStages] = useState<ResearchStage[]>(PENDING_STAGES);
  const [stageStatuses, setStageStatuses] = useState<StageStatus[]>(() =>
    PENDING_STAGES.map(() => "pending" as StageStatus)
  );
  const [route, setRoute] = useState<RegionRoute | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [routing, setRouting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startedRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    // Start elapsed timer
    timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);

    function applyStages(next: ResearchStage[]) {
      setStages(next);
      setStageStatuses(next.map(() => "pending" as StageStatus));
    }

    function updateStage(index: number, status: StageStatus) {
      setStageStatuses((prev) => {
        const next = [...prev];
        next[index] = status;
        return next;
      });
    }

    function markActiveFailed() {
      setStageStatuses((prev) => {
        const next = [...prev];
        const idx = next.findIndex((s) => s === "active");
        if (idx >= 0) next[idx] = "error";
        return next;
      });
    }

    async function run() {
      try {
        updateStage(0, "active");
        setRouting(true);

        // 1. Region dispatch. No filings are fetched until the query is placed
        //    on an exchange, so an Indian company cannot reach SEC/EDGAR.
        let resolved: RegionRoute;
        try {
          resolved = await resolveRegion(query);
        } finally {
          setRouting(false);
        }
        setRoute(resolved);
        applyStages(stagesForRegion(resolved.region as "US" | "INDIA"));

        if (resolved.region === "INDIA") {
          await runIndia(resolved);
        } else {
          await runUs(resolved);
        }
      } catch (err) {
        if (timerRef.current) clearInterval(timerRef.current);
        const msg = err instanceof Error ? err.message : "Could not connect to the Finora backend.";
        setErrorMsg(msg);
        markActiveFailed();
      }
    }

    async function runIndia(resolved: RegionRoute) {
      // Entity placement is already done; the rest narrates the India pipeline.
      updateStage(0, "done");
      updateStage(1, "active");
      const result = await researchIndia(resolved.query);

      if (timerRef.current) clearInterval(timerRef.current);

      if (result.status === "error" || !result.usable || !result.dashboard) {
        setErrorMsg(result.message || "India research returned no usable data.");
        markActiveFailed();
        return;
      }

      setStageStatuses((prev) => prev.map(() => "done" as StageStatus));
      setTimeout(() => {
        navigate(
          `/dashboard/india?query=${encodeURIComponent(resolved.query)}`,
          { state: { indiaPayload: result.dashboard } }
        );
      }, 800);
    }

    async function runUs(resolved: RegionRoute) {
      const result = await runResearch(resolved.query, "latest");

      if (timerRef.current) clearInterval(timerRef.current);

      if (result.status === "error") {
        setErrorMsg(result.error || "Research pipeline failed");
        markActiveFailed();
        return;
      }

      setStageStatuses((prev) => prev.map(() => "done" as StageStatus));

      setTimeout(() => {
        navigate(`/dashboard?session_id=${result.session_id}`);
      }, 800);
    }

    run();

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [query, navigate]);

  const label = route ? identifierForRoute(route) : query;
  const exchange = route ? exchangeLabelForRegion(route) : "—";
  const displayName = route ? nameForRoute(route, query) : query;

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
          {label.slice(0, 2)}
        </div>
        <div>
          <div className="font-serif text-lg font-semibold text-ink uppercase">
            {displayName}
          </div>
          <Annotation
            label={routing || !route ? "Resolving" : exchange}
            value={label}
          />
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
        {stages.map((stage, i) => {
          const status = stageStatuses[i];
          const done = status === "done";
          const active = status === "active";
          const error = status === "error";

          return (
            <div key={stage.key} className="relative flex gap-4 pb-8 last:pb-0">
              {i < stages.length - 1 && (
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

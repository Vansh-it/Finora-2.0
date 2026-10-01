import { useEffect, useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Building2, CheckCircle2, Loader2, XCircle } from "lucide-react";
import EditorialHeading from "../components/EditorialHeading";
import Annotation from "../components/Annotation";
import { cn } from "../utils/cn";
import { runResearch } from "../lib/api";
import { researchIndia } from "../lib/indiaApi";
import {
  AmbiguousCompanyQueryError,
  RegionMismatchError,
  resolveRegion,
  type RegionRoute,
} from "../lib/regionRouter";
import {
  exchangeLabelForRegion,
  identifierForRoute,
  nameForRoute,
  researchRegionFromParam,
  REGION_LABELS,
  stagesForRegion,
  type ResearchRegion,
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
  // The market the user selected in the search box, carried through the URL. An
  // absent or unrecognised value means the US default, which is what a bare link
  // has always meant.
  const selectedRegion = researchRegionFromParam(params.get("region"));
  const navigate = useNavigate();
  const [stages, setStages] = useState<ResearchStage[]>(PENDING_STAGES);
  const [stageStatuses, setStageStatuses] = useState<StageStatus[]>(() =>
    PENDING_STAGES.map(() => "pending" as StageStatus)
  );
  const [route, setRoute] = useState<RegionRoute | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  /**
   * Two refusals the user can act on, kept apart from `errorMsg` because they are
   * not failures. A mismatch means the company is real and named, in the other
   * market — one click fixes it. An ambiguity means the name is not specific
   * enough, so the candidates have to be offered.
   */
  const [mismatch, setMismatch] = useState<RegionRoute | null>(null);
  const [ambiguous, setAmbiguous] = useState<RegionRoute | null>(null);
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
          // Scoped to the selected market. The backend will not answer from the
          // other one, so a wrong-market company surfaces as a switchable
          // refusal rather than a confident report on the wrong company.
          resolved = await resolveRegion(query, selectedRegion);
        } finally {
          setRouting(false);
        }
        setRoute(resolved);
        applyStages(stagesForRegion(resolved.region as ResearchRegion));

        if (resolved.region === "INDIA") {
          await runIndia(resolved);
        } else {
          await runUs(resolved);
        }
      } catch (err) {
        if (timerRef.current) clearInterval(timerRef.current);
        if (err instanceof RegionMismatchError) {
          setMismatch(err.route);
          markActiveFailed();
          return;
        }
        if (err instanceof AmbiguousCompanyQueryError) {
          setAmbiguous(err.route);
          markActiveFailed();
          return;
        }
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
      // Region is sent explicitly. The endpoint refuses a request without one, so
      // the market the user chose cannot be dropped between routing and running.
      const result = await runResearch(resolved.query, "latest", "US");

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
  // A refusal replaces the progress screen: showing live-looking stages for a
  // research that cannot start is the misleading state this is meant to prevent.
  const blocked = Boolean(mismatch || ambiguous);

  return (
    <div className="mx-auto min-h-[80vh] max-w-3xl px-4 py-16 sm:px-6 lg:px-0">
      <p className="font-mono text-xs font-semibold tracking-[0.3em] text-ink-3 uppercase">
        {blocked ? "Cannot start" : "Research in progress"}
      </p>
      <EditorialHeading className="mt-4" size="md">
        {blocked ? (
          <>Check the market.</>
        ) : (
          <>
            Building
            <br />
            the research file.
          </>
        )}
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
            label={
              mismatch?.region
                ? `Listed in ${REGION_LABELS[mismatch.region as ResearchRegion]}`
                : routing || !route
                  ? "Resolving"
                  : exchange
            }
            value={label}
          />
        </div>
        {!blocked && elapsed > 0 && (
          <div className="ml-auto font-mono text-xs text-ink-3">{elapsed}s</div>
        )}
      </div>

      {/* Cross-market refusal. The company is named, so this is a wrong-market
          message and not an error: the fix is switching tabs, never a retry, and
          never quietly researching it in the market the user is not in. */}
      {mismatch && (
        <div className="mt-6 border-2 border-annotate-blue bg-blue-50 p-4">
          <p className="font-mono text-sm font-bold tracking-widest text-annotate-blue uppercase">
            Listed in{" "}
            {mismatch.region === "INDIA" ? "India" : "the US"} — not{" "}
            {REGION_LABELS[selectedRegion]}
          </p>
          <p className="mt-1 text-sm text-ink-2">{mismatch.message}</p>
          {mismatch.identity && (
            <p className="mt-2 font-mono text-xs text-ink-3">
              {mismatch.identity.display_name}
              {mismatch.identity.identifier &&
                ` · ${mismatch.identity.identifier}`}
              {mismatch.identity.exchange && ` · ${mismatch.identity.exchange}`}
            </p>
          )}
          <div className="mt-4 flex flex-wrap gap-3">
            {mismatch.region && (
              <button
                onClick={() =>
                  navigate(
                    `/research?ticker=${encodeURIComponent(query)}&region=${mismatch.region}`
                  )
                }
                className="border-2 border-ink bg-ink px-4 py-2 font-mono text-xs font-bold tracking-[0.15em] text-paper uppercase hover:bg-ink-2"
              >
                Switch to {REGION_LABELS[mismatch.region as ResearchRegion]} &amp;
                research
              </button>
            )}
            <button
              onClick={() => navigate("/research")}
              className="border-2 border-ink/30 px-4 py-2 font-mono text-xs font-bold tracking-[0.15em] text-ink-2 uppercase hover:border-ink hover:text-ink"
            >
              Search {REGION_LABELS[selectedRegion]} instead
            </button>
          </div>
        </div>
      )}

      {/* Ambiguity inside the selected market. The router declined to pick, so
          the candidates are offered as choices. */}
      {ambiguous && (
        <div className="mt-6 border-2 border-ink bg-paper p-4">
          <p className="font-mono text-sm font-bold tracking-widest text-ink uppercase">
            More than one {REGION_LABELS[selectedRegion]} company
          </p>
          <p className="mt-1 text-sm text-ink-2">{ambiguous.message}</p>
          <div className="mt-4 flex flex-col gap-2">
            {(ambiguous.considered ?? [])
              .filter((c) => c.ambiguous && c.candidates.length > 0)
              .flatMap((c) => c.candidates)
              .map((candidate, i) => {
                const name =
                  (candidate.display_name as string) ||
                  (candidate.name as string) ||
                  (candidate.nse_symbol as string) ||
                  "?";
                const sym =
                  (candidate.nse_symbol as string) ||
                  (candidate.ticker as string) ||
                  (candidate.symbol as string) ||
                  "";
                return (
                  <button
                    key={`${name}-${sym}-${i}`}
                    onClick={() =>
                      navigate(
                        `/research?ticker=${encodeURIComponent(sym || name)}&region=${selectedRegion}`
                      )
                    }
                    className="flex items-center gap-3 border-2 border-ink/20 px-4 py-3 text-left transition-colors hover:border-ink hover:bg-ink hover:text-paper"
                  >
                    <Building2 size={14} className="shrink-0 text-ink-3" />
                    <span className="flex-1 font-sans text-sm font-semibold">
                      {name}
                    </span>
                    {sym && (
                      <span className="font-mono text-xs font-bold">{sym}</span>
                    )}
                  </button>
                );
              })}
          </div>
          <button
            onClick={() => navigate("/research")}
            className="mt-4 font-mono text-xs font-bold text-ink-3 underline hover:text-ink"
          >
            ← Back to Research
          </button>
        </div>
      )}

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

      {!blocked && (
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
      )}
    </div>
  );
}

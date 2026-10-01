import { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import EditorialHeading from "../components/EditorialHeading";
import HighlightText from "../components/HighlightText";
import ResearchInput from "../components/ResearchInput";
import Annotation from "../components/Annotation";
import PaperTexture from "../components/PaperTexture";
import ResearchProcessingPage from "./ResearchProcessingPage";
import {
  researchRegionFromParam,
  REGION_EXCHANGES,
} from "../lib/researchStages";

export default function ResearchPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const ticker = params.get("ticker");
  // The URL owns the selected market, so reloading /research?region=INDIA — or
  // sharing that link — opens the selector on India rather than resetting it.
  const region = researchRegionFromParam(params.get("region"));
  const [remaining, setRemaining] = useState<number | null>(null);
  const [limit, setLimit] = useState(5);
  const [exhausted, setExhausted] = useState(false);

  useEffect(() => {
    fetch("/api/auth/profile")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.usage) {
          setRemaining(data.usage.remaining);
          setLimit(data.usage.limit);
          if (data.usage.remaining <= 0) setExhausted(true);
        }
      })
      .catch(() => {});
  }, []);

  if (ticker) return <ResearchProcessingPage />;

  return (
    <div className="relative">
      <PaperTexture />
      <div className="mx-auto max-w-4xl px-4 py-20 sm:px-6 lg:px-0">
        <p className="mb-4 font-mono text-xs font-semibold tracking-[0.3em] text-ink-3 uppercase">New Research File</p>
        <EditorialHeading size="md">
          What company should
          <br />
          <HighlightText>Finora investigate?</HighlightText>
        </EditorialHeading>

        {exhausted ? (
          <div className="mt-8 max-w-lg border-2 border-ink/20 bg-paper p-8">
            <h3 className="font-serif text-2xl font-semibold text-ink">Research limit reached.</h3>
            <p className="mt-3 text-sm leading-relaxed text-ink-2">
              You have used all {limit} researches available in this Finora preview.
              Each account is limited to {limit} company researches to ensure quality access for all users.
            </p>
            <p className="mt-2 font-mono text-xs text-ink-3">
              Your research history is still available below.
            </p>
            <div className="mt-6 flex gap-3">
              <button
                onClick={() => navigate("/history")}
                className="border-2 border-ink bg-ink px-6 py-3 font-mono text-xs font-bold tracking-wider text-paper uppercase transition-colors hover:bg-ink-2"
              >
                View History
              </button>
              <button
                onClick={() => navigate("/")}
                className="border-2 border-ink/25 bg-paper px-6 py-3 font-mono text-xs font-bold tracking-wider text-ink uppercase transition-colors hover:border-ink"
              >
                Back to Home
              </button>
            </div>
          </div>
        ) : (
          <>
            <p className="mt-6 max-w-lg text-base leading-relaxed text-ink-2">
              Choose a market, then enter a company name or ticker. Finora reads
              that market's authoritative filings, extracts the financial
              statements, calculates institutional-grade metrics, and verifies
              every figure against independent sources. Companies listed in the
              other market are named for you rather than researched in the wrong
              currency.
            </p>

            {remaining !== null && (
              <p className="mt-3 font-mono text-xs text-ink-3">
                {remaining} of {limit} researches remaining
              </p>
            )}

            <div className="mt-10 max-w-2xl">
              <ResearchInput region={region} />
            </div>
            <p className="mt-4 max-w-2xl font-mono text-xs text-ink-3">
              Searching {REGION_EXCHANGES[region]}. Companies listed elsewhere are
              reported rather than researched in the wrong market.
            </p>
          </>
        )}

        <div className="mt-16 grid grid-cols-1 gap-6 border-t border-ink/15 pt-10 sm:grid-cols-3">
          <Annotation label="Step 01" value="Identify the company & its listing" />
          <Annotation label="Step 02" value="Read the market's filings" tone="blue" />
          <Annotation label="Step 03" value="Verify & explain" tone="red" />
        </div>
      </div>
    </div>
  );
}

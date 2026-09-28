import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import EditorialHeading from "../components/EditorialHeading";
import HighlightText from "../components/HighlightText";
import PaperTexture from "../components/PaperTexture";

interface ResearchEntry {
  session_id: string;
  company: string;
  ticker: string;
  period: string;
  created_at: string;
  headline: string;
  metric_count: number;
  source_count: number;
  status: string;
}

interface UsageInfo {
  used: number;
  limit: number;
  remaining: number;
}

export default function HistoryPage() {
  const navigate = useNavigate();
  const [researches, setResearches] = useState<ResearchEntry[]>([]);
  const [usage, setUsage] = useState<UsageInfo>({ used: 0, limit: 5, remaining: 5 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/research/history")
      .then((res) => {
        if (!res.ok) return null;
        return res.json();
      })
      .then((data) => {
        if (data) {
          setResearches(data.researches || []);
          setUsage(data.usage || { used: 0, limit: 5, remaining: 5 });
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  function formatDate(iso: string): string {
    try {
      const d = new Date(iso);
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    } catch {
      return "";
    }
  }

  const usagePct = usage.limit > 0 ? (usage.used / usage.limit) * 100 : 0;

  return (
    <div>
      {/* Header */}
      <section className="relative border-b border-ink/15">
        <PaperTexture />
        <div className="mx-auto max-w-5xl px-4 py-20 sm:px-6 lg:px-0">
          <p className="mb-4 font-mono text-xs font-semibold tracking-[0.3em] text-ink-3 uppercase">
            Research History
          </p>
          <EditorialHeading size="md">
            Your research
            <br />
            <HighlightText>record.</HighlightText>
          </EditorialHeading>

          {/* Usage bar */}
          <div className="mt-8 max-w-md">
            <div className="flex items-baseline justify-between font-mono text-xs text-ink-2">
              <span className="font-semibold tracking-wider uppercase">
                {usage.used} of {usage.limit} researches used
              </span>
              <span className="text-ink-3">{usage.remaining} remaining</span>
            </div>
            <div className="mt-2 h-1.5 bg-ink/10">
              <div
                className="h-full bg-ink transition-all duration-500"
                style={{ width: `${usagePct}%` }}
              />
            </div>
          </div>
        </div>
      </section>

      {/* Research list */}
      <section className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-0">
        {loading ? (
          <div className="py-20 text-center">
            <div className="inline-block h-6 w-6 animate-spin border-2 border-ink border-t-transparent" />
            <p className="mt-4 font-mono text-sm text-ink-3">Loading research history...</p>
          </div>
        ) : researches.length === 0 ? (
          <div className="py-20 text-center">
            <p className="text-ink-2">No completed research yet.</p>
            <Link
              to="/research"
              className="mt-6 inline-flex items-center gap-2 border-2 border-ink bg-paper px-6 py-3 font-mono text-xs font-bold tracking-wider uppercase transition-colors hover:bg-ink hover:text-paper"
            >
              Start Research <ArrowRight size={14} />
            </Link>
          </div>
        ) : (
          <div className="space-y-6">
            {researches.map((r, i) => (
              <button
                key={r.session_id}
                onClick={() => navigate(`/dashboard?session_id=${r.session_id}`)}
                className="group w-full border border-ink/20 bg-paper p-6 text-left transition-colors hover:border-ink sm:flex sm:items-start sm:justify-between"
              >
                <div className="flex-1">
                  <div className="flex items-baseline gap-3">
                    <span className="font-mono text-xs font-bold text-ink-3">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <h3 className="font-serif text-lg font-semibold text-ink uppercase">
                      {r.company}
                    </h3>
                    {r.ticker && (
                      <span className="font-mono text-xs font-semibold tracking-widest text-ink-3">
                        {r.ticker}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 font-mono text-xs text-ink-3">
                    {r.period && <span>{r.period} · </span>}
                    researched {formatDate(r.created_at)}
                  </p>
                  {r.headline && (
                    <p className="mt-3 max-w-xl font-serif text-sm italic leading-snug text-ink-2">
                      "{r.headline}"
                    </p>
                  )}
                  <p className="mt-2 font-mono text-[10px] text-ink-3">
                    {r.metric_count} metrics · {r.source_count} sources
                  </p>
                </div>
                <div className="mt-4 shrink-0 sm:ml-6 sm:mt-0">
                  <span className="inline-flex items-center gap-1.5 border border-ink px-4 py-2 font-mono text-[10px] font-bold tracking-widest text-ink uppercase transition-colors group-hover:bg-ink group-hover:text-paper">
                    Open Research <ArrowRight size={12} />
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

    </div>
  );
}

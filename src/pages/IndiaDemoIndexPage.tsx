import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listIndiaDemoCompanies, type IndiaDemoCompany } from "../lib/indiaApi";
import EditorialHeading from "../components/EditorialHeading";
import HighlightText from "../components/HighlightText";

/**
 * India demo index — lists development fixture companies.
 * Route: /dashboard/demo/india
 */
export default function IndiaDemoIndexPage() {
  const [companies, setCompanies] = useState<IndiaDemoCompany[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listIndiaDemoCompanies()
      .then((r) => setCompanies(r.companies))
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load demo companies")
      );
  }, []);

  return (
    <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
      <p className="font-mono text-xs font-semibold tracking-[0.25em] text-ink-3 uppercase">
        India Dashboards · Development Preview
      </p>
      <EditorialHeading size="lg" className="mt-2">
        <HighlightText>India Dashboard Demos</HighlightText>
      </EditorialHeading>
      <p className="mt-4 max-w-xl text-sm leading-relaxed text-ink-2">
        These dashboards run on clearly-labeled development fixture data while the
        India Adapter phase connects official filings. No live company research is
        shown here.
      </p>

      {error && (
        <p className="mt-8 border border-annotate-red px-4 py-3 font-mono text-xs text-annotate-red">
          {error} — is the backend running (npm run dev:all)?
        </p>
      )}

      <div className="mt-10 divide-y divide-ink/12 border-y border-ink/20">
        {companies.map((c) => (
          <Link
            key={c.slug}
            to={`/dashboard/demo/india/${c.slug}`}
            className="group flex items-center justify-between py-5 transition-colors hover:bg-paper-2/40"
          >
            <div>
              <div className="font-serif text-xl font-semibold text-ink">{c.name}</div>
              <div className="mt-1 flex items-center gap-3 font-mono text-[11px] text-ink-3 uppercase">
                <span className="font-bold text-ink">{c.ticker}</span>
                <span>{c.entity_type}</span>
                <span className="text-annotate-blue">Fixture data</span>
              </div>
            </div>
            <span className="font-mono text-xs text-ink-3 transition-colors group-hover:text-ink">
              Open →
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

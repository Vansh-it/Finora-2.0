import { useState } from "react";
import { X } from "lucide-react";
import type {
  IndiaDashboardPayload,
  IndiaMetricCard,
  IndiaRedFlag,
} from "../../../types/india";

type InspectTarget =
  | { kind: "metric"; metric: IndiaMetricCard }
  | { kind: "flag"; flag: IndiaRedFlag }
  | { kind: "coverage" }
  | { kind: "model"; model: string };

/** Evidence drawer — formula, inputs, sources and rules for any inspected item. */
export default function IndiaEvidenceDrawer({
  target,
  payload,
  onClose,
}: {
  target: InspectTarget | null;
  payload: IndiaDashboardPayload;
  onClose: () => void;
}) {
  const [showCoverageDetail, setShowCoverageDetail] = useState(false);
  if (!target) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/40" onClick={onClose}>
      <aside
        className="thin-scroll h-full w-full max-w-lg overflow-y-auto border-l border-ink bg-paper p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <h3 className="font-serif text-xl font-semibold text-ink">
            {target.kind === "metric" && target.metric.display_name}
            {target.kind === "flag" && target.flag.title}
            {target.kind === "coverage" && "Research Coverage"}
            {target.kind === "model" && `${target.model} Model`}
          </h3>
          <button
            onClick={onClose}
            aria-label="Close evidence drawer"
            className="text-ink-3 hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        {target.kind === "metric" && <MetricEvidence metric={target.metric} payload={payload} />}
        {target.kind === "flag" && <FlagEvidence flag={target.flag} />}
        {target.kind === "coverage" && (
          <CoverageEvidence payload={payload} expanded={showCoverageDetail} onToggle={() => setShowCoverageDetail((v) => !v)} />
        )}
        {target.kind === "model" && <ModelEvidence payload={payload} model={target.model} />}
      </aside>
    </div>
  );
}

function MetricEvidence({
  metric,
  payload,
}: {
  metric: IndiaMetricCard;
  payload: IndiaDashboardPayload;
}) {
  const sources = (metric.source_ids ?? [])
    .map((id) => payload.sources.find((s) => s.source_id === id))
    .filter(Boolean);

  return (
    <div className="mt-5 space-y-5">
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-3xl font-bold text-ink tabular">
          {metric.display_value}
        </span>
        <StatusPill status={metric.status} />
      </div>

      {metric.formula && (
        <Section title="Formula">
          <p className="font-mono text-sm text-ink-2">{metric.formula}</p>
        </Section>
      )}

      {metric.inputs && metric.inputs.length > 0 && (
        <Section title="Inputs">
          <ul className="space-y-1 font-mono text-sm text-ink-2">
            {metric.inputs.map((i) => (
              <li key={i}>· {i.replace(/_/g, " ")}</li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Period">
        <p className="font-mono text-sm text-ink-2">{metric.period}</p>
      </Section>

      <Section title="Sources">
        {sources.length === 0 ? (
          <p className="font-mono text-sm text-ink-3">No sources recorded</p>
        ) : (
          <ul className="space-y-2">
            {sources.map((s) => (
              <li key={s!.source_id} className="font-mono text-xs text-ink-2">
                <span className="font-bold">{s!.source_name}</span>
                {s!.is_fixture && (
                  <span className="ml-2 text-annotate-blue">[FIXTURE]</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function FlagEvidence({ flag }: { flag: IndiaRedFlag }) {
  return (
    <div className="mt-5 space-y-5">
      <div className="flex items-center gap-2">
        <span
          className={
            "border px-2 py-0.5 font-mono text-[10px] font-bold tracking-[0.12em] uppercase " +
            (flag.severity === "HIGH"
              ? "border-annotate-red text-annotate-red"
              : "border-annotate-blue text-annotate-blue")
          }
        >
          {flag.severity || flag.status}
        </span>
        <span className="font-mono text-[10px] tracking-[0.12em] text-ink-3 uppercase">
          {flag.category}
        </span>
      </div>

      {flag.rule && (
        <Section title="Rule">
          <p className="text-sm leading-relaxed text-ink-2">{flag.rule}</p>
        </Section>
      )}

      <Section title="Evidence">
        {flag.evidence.length === 0 ? (
          <p className="font-mono text-sm text-ink-3">{flag.reason}</p>
        ) : (
          <div className="divide-y divide-ink/10 border border-ink/15">
            {flag.evidence.map((e, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2">
                <span className="font-mono text-xs text-ink-2">{e.label}</span>
                <span className="font-mono text-xs font-bold text-ink tabular">{e.value}</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Status">
        <p className="font-mono text-sm text-ink-2">{flag.status}</p>
        {flag.status === "PENDING_SOURCE_INTEGRATION" && (
          <p className="mt-1 text-xs text-ink-3">
            This detector activates when real India source ingestion lands.
          </p>
        )}
      </Section>
    </div>
  );
}

function CoverageEvidence({
  payload,
  expanded,
  onToggle,
}: {
  payload: IndiaDashboardPayload;
  expanded: boolean;
  onToggle: () => void;
}) {
  const c = payload.completeness;
  return (
    <div className="mt-5 space-y-5">
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-3xl font-bold text-ink tabular">
          {c.coverage_pct != null ? `${c.coverage_pct}%` : "—"}
        </span>
        <span className="font-mono text-sm text-ink-3">
          {c.available} of {c.expected} applicable metrics
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Stat label="Reported" value={c.reported} />
        <Stat label="Calculated" value={c.calculated} />
        <Stat label="Derived" value={c.derived} />
        <Stat label="Market Data" value={c.market_data} />
        <Stat label="Unavailable" value={c.unavailable} />
        <Stat label="Not Applicable" value={c.not_applicable} />
      </div>

      <Section title="Coverage by category">
        <div className="divide-y divide-ink/10 border border-ink/15">
          {c.categories.map((cat) => (
            <div key={cat.category} className="px-3 py-2.5">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-ink-2">{cat.display_name}</span>
                <span className="font-mono text-xs font-bold text-ink tabular">
                  {cat.coverage_pct != null ? `${cat.coverage_pct}%` : "—"}
                </span>
              </div>
              {expanded && cat.missing.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {cat.missing.map((m) => (
                    <li key={m.metric_id} className="font-mono text-[11px] text-ink-3">
                      · {m.display_name}: {m.reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
        <button
          onClick={onToggle}
          className="mt-2 font-mono text-[10px] font-semibold tracking-[0.12em] text-ink-3 uppercase underline hover:text-ink"
        >
          {expanded ? "Hide missing fields" : "Show missing fields & reasons"}
        </button>
      </Section>
    </div>
  );
}

function ModelEvidence({ payload, model }: { payload: IndiaDashboardPayload; model: string }) {
  const m = payload.forensics.models.find((x) => x.model === model);
  if (!m) return <p className="mt-5 text-sm text-ink-2">Model not found.</p>;
  return (
    <div className="mt-5 space-y-5">
      <div className="flex items-center gap-2">
        <span className="border border-ink/25 px-2 py-0.5 font-mono text-[10px] font-bold tracking-[0.12em] uppercase">
          {m.applicable ? "Applicable" : "Not Applicable"}
        </span>
        <span className="font-mono text-xs text-ink-3">{m.status}</span>
      </div>
      <p className="text-sm leading-relaxed text-ink-2">{m.reason}</p>
      {m.result && (
        <div className="border border-ink/15 p-4">
          <div className="font-mono text-2xl font-bold text-ink tabular">
            {m.result.score}/{m.result.max}
          </div>
          <ul className="mt-3 space-y-1">
            {m.result.signals.map((s) => (
              <li key={s.label} className="flex justify-between font-mono text-xs">
                <span className="text-ink-2">{s.label}</span>
                <span className={s.value === 1 ? "text-annotate-green font-bold" : "text-ink-3"}>
                  {s.value === 1 ? "✓ +1" : "✕ +0"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-ink/15 p-3">
      <div className="font-mono text-lg font-bold text-ink tabular">{value}</div>
      <div className="font-mono text-[9px] font-semibold tracking-[0.12em] text-ink-3 uppercase">
        {label}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className="border border-ink/25 px-2 py-0.5 font-mono text-[10px] font-semibold tracking-[0.12em] text-ink-2 uppercase">
      {status}
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-ink/15 pt-4">
      <p className="mb-2 font-mono text-[10px] font-semibold tracking-[0.2em] text-ink-3 uppercase">
        {title}
      </p>
      {children}
    </div>
  );
}

export type { InspectTarget };

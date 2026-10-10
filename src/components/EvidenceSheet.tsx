import { useState } from 'react';
import { ArrowLeft, BadgeCheck, Copy, ExternalLink, FileText, TriangleAlert } from 'lucide-react';
import type { MetricEvidence } from '../lib/data';
import { formatCompact, formatMultiple, formatPercent } from '../lib/format';
import { BottomSheet } from './BottomSheet';
import { useToast } from '../hooks/toast';

function fmtInput(value: number, format: MetricEvidence['inputs'][number]['format']): string {
  if (format === 'money') return formatCompact(value);
  if (format === 'percent') return formatPercent(value * 100);
  if (format === 'multiple') return formatMultiple(value);
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

export function EvidenceSheet({ evidence, onClose, depth = 0 }: {
  evidence: MetricEvidence | null;
  onClose: () => void;
  depth?: number;
}) {
  const toast = useToast();
  const [child, setChild] = useState<MetricEvidence | null>(null);

  if (!evidence) return null;

  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${label} copied`, 'ok');
    } catch {
      toast('Copy not available', 'warn');
    }
  };

  return (
    <>
      <BottomSheet open snap={depth > 0 ? 95 : 75} onClose={onClose} title={depth > 0 ? 'Input evidence' : 'Evidence receipt'}>
        <div className="anim-fade">
          {depth > 0 && (
            <button onClick={onClose} className="pressable mb-3 flex min-h-[44px] items-center gap-1.5 text-sm font-medium text-[#ff8a3d]">
              <ArrowLeft size={16} /> Back to {evidence.metric}
            </button>
          )}
          <p className="mono-label text-[#ff8a3d]">{evidence.period} · {evidence.form}</p>
          <h3 className="mt-1 font-display text-[20px] font-semibold tracking-tight text-white">{evidence.metric}</h3>
          <p className="num mt-1 text-[30px] font-semibold leading-none text-white">{evidence.displayValue}</p>

          {evidence.unavailableReason ? (
            <div className="mt-4 rounded-2xl border border-dashed border-[#fbbf24]/40 bg-[#fbbf24]/[0.06] p-4">
              <p className="flex items-center gap-2 text-sm font-semibold text-[#fbbf24]"><TriangleAlert size={16} /> Unavailable</p>
              <p className="mt-1 text-sm leading-6 text-[#d7d3c8]">{evidence.unavailableReason}</p>
            </div>
          ) : (
            <>
              <div className="mt-4 rounded-2xl border border-white/10 bg-black/40 p-3.5">
                <p className="mono-label mb-1.5 text-[#6b675c]">Formula · Python engine</p>
                <p className="num text-[14px] leading-6 text-[#ffb25c]">{evidence.formula}</p>
              </div>

              {evidence.inputs.length > 0 && (
                <div className="mt-3">
                  <p className="mono-label mb-2 text-[#6b675c]">Inputs · tap to drill in</p>
                  <div className="space-y-2">
                    {evidence.inputs.map((inp) => (
                      <button
                        key={inp.name}
                        disabled={depth >= 2}
                        onClick={() => setChild({
                          metric: inp.name, period: evidence.period, value: inp.value,
                          displayValue: fmtInput(inp.value, inp.format),
                          formula: `${inp.name} = audited filing value`, inputs: [],
                          form: evidence.form, filingDate: evidence.filingDate,
                          accession: evidence.accession, xbrl: evidence.xbrl,
                          verified: evidence.verified, corroborating: evidence.corroborating,
                        })}
                        className="pressable flex min-h-[52px] w-full items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 disabled:opacity-60"
                      >
                        <span className="truncate text-[14px] text-[#d7d3c8]">{inp.name}</span>
                        <span className="num shrink-0 text-[14px] font-semibold text-white">{fmtInput(inp.value, inp.format)}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          <div className="mt-4 space-y-2.5 rounded-2xl border border-white/10 bg-white/[0.02] p-3.5">
            <div className="flex items-center gap-2 text-[13px] text-[#d7d3c8]">
              <FileText size={15} className="shrink-0 text-[#ff8a3d]" />
              <span>{evidence.form} · filed {evidence.filingDate}</span>
            </div>
            <button onClick={() => copy(evidence.accession, 'Accession')} className="pressable flex min-h-[44px] w-full items-center justify-between gap-2 rounded-xl bg-black/40 px-3">
              <span className="num truncate text-[12px] text-[#a7a29a]">{evidence.accession}</span>
              <Copy size={14} className="shrink-0 text-[#ff8a3d]" />
            </button>
            <div className="flex flex-wrap items-center gap-2">
              <span className="num rounded-lg border border-white/12 bg-black/40 px-2 py-1 text-[11px] text-[#7ab8ff]">{evidence.xbrl}</span>
              <a
                href="https://www.sec.gov/cgi-bin/browse-edgar" target="_blank" rel="noopener noreferrer"
                className="pressable flex min-h-[44px] items-center gap-1.5 rounded-lg border border-[#ff5a1f]/40 bg-[#ff5a1f]/10 px-3 text-[13px] font-semibold text-[#ff8a3d]"
              >
                Open on SEC <ExternalLink size={13} />
              </a>
            </div>
          </div>

          <div className={`mt-3 flex items-start gap-2.5 rounded-2xl border p-3.5 ${evidence.verified ? 'border-[#34d399]/30 bg-[#34d399]/[0.06]' : 'border-[#fbbf24]/30 bg-[#fbbf24]/[0.06]'}`}>
            <BadgeCheck size={18} className={evidence.verified ? 'mt-0.5 shrink-0 text-[#34d399]' : 'mt-0.5 shrink-0 text-[#fbbf24]'} />
            <div>
              <p className="text-[14px] font-semibold text-white">
                {evidence.verified ? `Cross-verified · ${evidence.corroborating} sources` : 'Not cross-verified'}
              </p>
              {evidence.mismatch && <p className="mt-0.5 text-[13px] leading-5 text-[#fbbf24]">{evidence.mismatch}</p>}
              <p className="mt-0.5 font-mono text-[11px] text-[#6b675c]">SEC = authority · Python = calculation · AI = interpretation</p>
            </div>
          </div>
        </div>
      </BottomSheet>
      {child && <EvidenceSheet evidence={child} onClose={() => setChild(null)} depth={depth + 1} />}
    </>
  );
}

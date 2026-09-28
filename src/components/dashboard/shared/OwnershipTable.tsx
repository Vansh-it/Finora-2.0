import type { SharedOwnershipColumn } from "./types";

/**
 * Ownership history table.
 *
 * Generic over the row type: the holder categories are a region concern, so
 * the caller passes the columns. A missing disclosure renders as an em dash
 * with an explanatory title, never as 0% — "did not disclose" and "held
 * nothing" are different claims.
 */
export default function OwnershipTable<Row extends { period: string }>({
  rows,
  columns,
  unavailableMessage = "Shareholding data unavailable.",
}: {
  rows: Row[];
  columns: Array<SharedOwnershipColumn<Row>>;
  unavailableMessage?: string;
}) {
  if (rows.length === 0) {
    return (
      <p className="font-mono text-xs tracking-[0.15em] text-ink-3 uppercase">
        {unavailableMessage}
      </p>
    );
  }
  return (
    <div className="thin-scroll overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr className="border-b-2 border-ink">
            <th className="py-2 pr-4 text-left font-mono text-[10px] font-bold tracking-widest text-ink-3 uppercase">
              Holder
            </th>
            {rows.map((r) => (
              <th
                key={r.period}
                className="py-2 pl-4 text-right font-mono text-[10px] font-bold tracking-widest text-ink-3 uppercase"
              >
                {r.period}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {columns.map(({ key, label }) => (
            <tr key={key} className="border-b border-ink/12">
              <td className="py-3 pr-4 text-ink-2">{label}</td>
              {rows.map((r) => {
                const v = r[key] as number | null | undefined;
                return (
                  <td
                    key={r.period}
                    className="py-3 pl-4 text-right font-mono tabular text-ink"
                    title={v == null ? "Not disclosed for this period" : undefined}
                  >
                    {v == null ? "—" : `${v.toFixed(1)}%`}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

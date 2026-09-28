import type { IndiaDashboardPayload, IndiaOwnershipRow } from "../../../types/india";
import { MacroContextStrip, OwnershipTable } from "../shared";
import type { SharedOwnershipColumn } from "../shared";

/**
 * India-specific dashboard sections.
 *
 * Only the two components that carry a genuinely Indian domain fact live
 * here. Everything else (statements, metric cards, red flags, forensic
 * models, source ledger) is region-agnostic and is imported from
 * `../shared` directly — re-exporting it here would only hide that.
 */

/**
 * Holder categories.
 *
 * Promoter, FII/FPI, DII and pledged-share tracking are Indian disclosure
 * concepts with no US equivalent, so the column set is India data, not a
 * layout concern. The table itself is shared and generic over its row type.
 */
const OWNERSHIP_COLUMNS: Array<SharedOwnershipColumn<IndiaOwnershipRow>> = [
  { key: "promoter_pct", label: "Promoter" },
  { key: "promoter_pledge_pct", label: "Pledge" },
  { key: "fii_pct", label: "FII/FPI" },
  { key: "dii_pct", label: "DII" },
  { key: "mutual_fund_pct", label: "Mutual Funds" },
  { key: "public_pct", label: "Public" },
  { key: "institutional_pct", label: "Institutional" },
];

/** Ownership history table — promoter, FII/DII, MF, public. */
export function IndiaOwnershipTable({
  ownership,
}: {
  ownership: IndiaDashboardPayload["ownership"];
}) {
  return (
    <OwnershipTable
      rows={ownership.available ? ownership.rows : []}
      columns={OWNERSHIP_COLUMNS}
    />
  );
}

/** India macro strip — fixture-labeled macro context. */
export function IndiaMacroStrip({
  macro,
}: {
  macro: IndiaDashboardPayload["macro"];
}) {
  return <MacroContextStrip macro={macro} title="India Macro Context" />;
}

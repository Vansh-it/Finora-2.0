/**
 * INR formatting — Indian numbering (lakh / crore / lakh crore).
 * The backend pre-formats most display strings; these utilities cover
 * client-side formatting (charts, tooltips, ownership tables).
 *
 * 1 lakh = 100,000; 1 crore = 10,000,000; 1 lakh crore = 1e12.
 */

const LAKH = 1e5;
const CRORE = 1e7;
const LAKH_CRORE = 1e12;

function indianGrouping(n: number): string {
  const s = Math.round(Math.abs(n)).toString();
  if (s.length <= 3) return s;
  const tail = s.slice(-3);
  const head = s.slice(0, -3);
  const parts: string[] = [];
  let h = head;
  while (h.length > 2) {
    parts.unshift(h.slice(-2));
    h = h.slice(0, -2);
  }
  if (h) parts.unshift(h);
  return [...parts, tail].join(",");
}

/** Format full numeric INR → ₹87,800 Cr / ₹1.24 lakh Cr / ₹9.4 lakh. */
export function formatInr(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const a = Math.abs(value);

  if (a >= LAKH_CRORE) {
    const v = a / LAKH_CRORE;
    const text = v >= 10 ? v.toFixed(1).replace(/\.0$/, "") : v.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
    return `${sign}₹${text} lakh Cr`;
  }
  if (a >= CRORE) {
    const v = a / CRORE;
    const text = a >= 10 * CRORE
      ? Math.round(v).toLocaleString("en-IN")
      : v.toFixed(1).replace(/\.0$/, "");
    return `${sign}₹${text} Cr`;
  }
  if (a >= LAKH) {
    const v = a / LAKH;
    return `${sign}₹${v.toFixed(2).replace(/0+$/, "").replace(/\.$/, "")} lakh`;
  }
  return `${sign}₹${indianGrouping(value)}`;
}

/** EPS with paise precision: ₹42.71 / -₹3.20. */
export function formatEps(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value >= 0 ? `₹${value.toFixed(2)}` : `-₹${Math.abs(value).toFixed(2)}`;
}

/** Percent already in percent units: 18.4%. */
export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

/** Signed percent for changes: +12.3% / -4.1%. */
export function formatSignedPercent(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%`;
}

/** Multiples: 3.2×. */
export function formatRatio(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(decimals)}×`;
}

/** Axis tick helper for charts in ₹ Cr. */
export function inrCroreTick(value: number): string {
  const cr = value / CRORE;
  if (Math.abs(cr) >= 100000) return `₹${(cr / 100000).toFixed(1)} lakh Cr`;
  if (Math.abs(cr) >= 1) return `₹${Math.round(cr).toLocaleString("en-IN")} Cr`;
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

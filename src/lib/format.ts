// Centralised money + number formatting. Every screen uses these.
export function formatCompact(value: number, currency = 'USD'): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '(' : '';
  const close = value < 0 ? ')' : '';
  const symbol = currency === 'USD' ? '$' : currency + ' ';
  const fmt = (n: number, s: string) => `${sign}${symbol}${n.toFixed(1)}${s}${close}`;
  if (abs >= 1e12) return fmt(abs / 1e12, 'T');
  if (abs >= 1e9) return fmt(abs / 1e9, 'B');
  if (abs >= 1e6) return fmt(abs / 1e6, 'M');
  if (abs >= 1e3) return fmt(abs / 1e3, 'K');
  return `${sign}${symbol}${abs.toFixed(0)}${close}`;
}

export function formatFull(value: number, currency = 'USD'): string {
  const symbol = currency === 'USD' ? '$' : currency + ' ';
  const abs = Math.abs(value);
  const body = abs.toLocaleString('en-US', { maximumFractionDigits: 0 });
  return value < 0 ? `(${symbol}${body})` : `${symbol}${body}`;
}

export function formatPercent(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

export function formatMultiple(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return `${value.toFixed(1)}x`;
}

export function formatSafe(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '—';
}

export function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return iso;
  }
}

export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = String(Math.floor(s / 3600)).padStart(2, '0');
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const sec = String(s % 60).padStart(2, '0');
  return `${h}:${m}:${sec}`;
}

export function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

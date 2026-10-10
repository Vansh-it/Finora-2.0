import { useState } from 'react';
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';
import { AlertCircle, Eye, EyeOff, Inbox, Loader2, RefreshCw, ShieldCheck } from 'lucide-react';
import { cn } from '../lib/cn';

// ---------- Button ----------
type BtnVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: BtnVariant;
  size?: 'md' | 'lg';
  loading?: boolean;
}
export function Button({ variant = 'primary', size = 'md', loading, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      className={cn(
        'pressable flex min-h-[48px] w-full items-center justify-center gap-2 rounded-2xl px-5 font-display text-[15px] font-semibold tracking-tight',
        size === 'lg' && 'min-h-[56px] text-base',
        variant === 'primary' && 'btn-primary',
        variant === 'secondary' && 'border border-white/15 bg-white/[0.06] text-white active:bg-white/10',
        variant === 'ghost' && 'text-[#a7a29a] active:bg-white/5 active:text-white',
        variant === 'danger' && 'border border-[#f87171]/40 bg-[#f87171]/10 text-[#f87171]',
        className,
      )}
      {...rest}
    >
      {loading && <Loader2 size={18} className="animate-spin" />}
      {children}
    </button>
  );
}

export function IconButton({ className, children, label, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      className={cn('pressable flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] text-white active:bg-white/10', className)}
      {...rest}
    >
      {children}
    </button>
  );
}

// ---------- Cards / chips ----------
export function Card({ className, children, onClick }: { className?: string; children: ReactNode; onClick?: () => void }) {
  const Tag = (onClick ? 'button' : 'div') as 'button';
  return (
    <Tag onClick={onClick} className={cn('card-dark block w-full p-4 text-left', onClick && 'pressable', className)}>
      {children}
    </Tag>
  );
}

export function TickerChip({ ticker, className }: { ticker: string; className?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-lg border border-[#ff5a1f]/40 bg-[#ff5a1f]/12 px-2 py-1 font-mono text-[11px] font-semibold tracking-wider text-[#ff8a3d]', className)}>
      {ticker}
    </span>
  );
}

export function TierBadge({ tier }: { tier: 'PRIMARY' | 'OFFICIAL' | 'CORROBORATING' }) {
  const color = tier === 'PRIMARY' ? 'text-[#34d399] border-[#34d399]/40 bg-[#34d399]/10'
    : tier === 'OFFICIAL' ? 'text-[#7ab8ff] border-[#7ab8ff]/40 bg-[#7ab8ff]/10'
    : 'text-[#e3b008] border-[#e3b008]/40 bg-[#e3b008]/10';
  return (
    <span className={cn('inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-[0.1em]', color)}>
      {tier}
    </span>
  );
}

export function SegmentedControl<T extends string>({ options, value, onChange, labels }: {
  options: readonly T[]; value: T; onChange: (v: T) => void; labels?: Partial<Record<T, string>>;
}) {
  return (
    <div role="tablist" aria-label="View options" className="flex rounded-2xl border border-white/10 bg-black/40 p-1">
      {options.map((o) => {
        const active = o === value;
        return (
          <button
            key={o} role="tab" aria-selected={active}
            onClick={() => onChange(o)}
            className={cn(
              'min-h-[44px] flex-1 rounded-xl px-2 text-[13px] font-semibold transition-all',
              active ? 'bg-white text-black shadow' : 'text-[#a7a29a] active:text-white',
            )}
          >
            {labels?.[o] ?? o}
          </button>
        );
      })}
    </div>
  );
}

// ---------- feedback ----------
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('skeleton rounded-xl', className)} />;
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span role="status" aria-label={label} className="inline-flex items-center gap-2 text-[#a7a29a]">
      <Loader2 size={18} className="animate-spin text-[#ff5a1f]" />
      <span className="text-sm">{label}…</span>
    </span>
  );
}

export function ProgressBar({ value, max = 100, className }: { value: number; max?: number; className?: string }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div role="progressbar" aria-valuenow={value} aria-valuemax={max} className={cn('h-2 overflow-hidden rounded-full bg-white/10', className)}>
      <div className="h-full rounded-full bg-gradient-to-r from-[#ff5a1f] to-[#ffb25c] transition-[width] duration-500" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-8 py-12 text-center anim-fade">
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04]">
        <Inbox size={26} className="text-[#ff8a3d]" />
      </div>
      <h3 className="font-display text-lg font-semibold text-white">{title}</h3>
      <p className="mt-1 text-sm leading-6 text-[#a7a29a]">{body}</p>
      {action && <div className="mt-5 w-full">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center px-8 py-12 text-center anim-fade">
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-[#f87171]/30 bg-[#f87171]/10">
        <AlertCircle size={26} className="text-[#f87171]" />
      </div>
      <h3 className="font-display text-lg font-semibold text-white">Something went wrong</h3>
      <p className="mt-1 text-sm leading-6 text-[#a7a29a]">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="pressable mt-5 flex min-h-[48px] items-center gap-2 rounded-2xl border border-white/15 bg-white/[0.06] px-6 text-sm font-semibold text-white">
          <RefreshCw size={16} /> Try again
        </button>
      )}
    </div>
  );
}

export function UnavailableMetric({ reason }: { reason?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-white/15 bg-black/30 p-3">
      <p className="num text-lg text-[#6b675c]">—</p>
      <p className="mt-1 text-xs leading-5 text-[#a7a29a]">{reason ?? 'This metric is unavailable for this filing.'}</p>
    </div>
  );
}

// ---------- forms ----------
interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}
export function Field({ label, error, hint, id, type, ...rest }: FieldProps) {
  const [show, setShow] = useState(false);
  const isPw = type === 'password';
  const inputId = id ?? label.replace(/\s+/g, '-').toLowerCase();
  return (
    <div>
      <label htmlFor={inputId} className="mono-label mb-1.5 block text-[#a7a29a]">{label}</label>
      <div className="relative">
        <input
          id={inputId}
          type={isPw && show ? 'text' : type}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${inputId}-err` : hint ? `${inputId}-hint` : undefined}
          className={cn(
            'min-h-[52px] w-full rounded-2xl border bg-black/40 px-4 text-white placeholder:text-[#6b675c]',
            error ? 'border-[#f87171]/60' : 'border-white/12 focus:border-[#ff5a1f]/60',
            isPw && 'pr-12',
          )}
          {...rest}
        />
        {isPw && (
          <button
            type="button" aria-label={show ? 'Hide password' : 'Show password'}
            onClick={() => setShow(!show)}
            className="absolute right-1 top-1 flex h-11 w-11 items-center justify-center rounded-xl text-[#a7a29a]"
          >
            {show ? <EyeOff size={19} /> : <Eye size={19} />}
          </button>
        )}
      </div>
      {error && <p id={`${inputId}-err`} role="alert" className="mt-1.5 text-[13px] text-[#f87171]">{error}</p>}
      {!error && hint && <p id={`${inputId}-hint`} className="mt-1.5 text-[13px] text-[#6b675c]">{hint}</p>}
    </div>
  );
}

// ---------- editorial ----------
export function HighlightText({ children }: { children: ReactNode }) {
  return <span className="highlight-mark">{children}</span>;
}

export function EditorialHeading({ kicker, title, right }: { kicker?: string; title: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-3">
      <div>
        {kicker && <p className="mono-label mb-1.5 text-[#ff8a3d]">{kicker}</p>}
        <h2 className="font-display text-[20px] font-semibold leading-[26px] tracking-tight text-white">{title}</h2>
      </div>
      {right}
    </div>
  );
}

export function SourceStamp({ text = 'SEC Verified' }: { text?: string }) {
  return (
    <span className="stamp"><ShieldCheck size={13} />{text}</span>
  );
}

export function Stars({ value, size = 16 }: { value: number; size?: number }) {
  return (
    <span role="img" aria-label={`${value} out of 5 stars`} className="inline-flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <svg key={i} width={size} height={size} viewBox="0 0 20 20" fill={i <= value ? '#ff5a1f' : 'none'} stroke={i <= value ? '#ff5a1f' : '#6b675c'} strokeWidth={1.5}>
          <path d="M10 1.5l2.6 5.3 5.9.9-4.2 4.1 1 5.8L10 14.9l-5.3 2.7 1-5.8L1.5 7.7l5.9-.9L10 1.5z" />
        </svg>
      ))}
    </span>
  );
}

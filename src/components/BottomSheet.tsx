import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn';
import { useKeyboardInset } from '../hooks/hooks';

// Bottom sheet with snap points, drag-to-close, focus trap, history-back support.
let openCount = 0;
const openStack: string[] = [];

export function BottomSheet({
  open, onClose, title, children, snap = 75, wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  snap?: 40 | 75 | 95;
  wide?: boolean;
}) {
  const id = useId();
  const titleId = `sheet-title-${id}`;
  const sheetRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const drag = useRef<{ startY: number; dy: number; dragging: boolean }>({ startY: 0, dy: 0, dragging: false });
  const [offset, setOffset] = useState(0);
  const keyboard = useKeyboardInset();

  const heights: Record<number, string> = { 40: '40dvh', 75: '75dvh', 95: '95dvh' };
  const pushed = useRef(false);
  const closedByPop = useRef(false);
  const openRef = useRef(open);
  openRef.current = open;

  // UI-initiated close: drop our history entry (if on top) then notify parent.
  const close = useCallback(() => {
    if (!closedByPop.current && history.state && (history.state as { sheet?: string }).sheet === id) {
      history.back();
    }
    onClose();
  }, [onClose, id]);

  // reset guards whenever the sheet is closed
  useEffect(() => {
    if (!open) {
      pushed.current = false;
      closedByPop.current = false;
    }
  }, [open ]);

  // open/close lifecycle: scroll lock, focus, history entry.
  // StrictMode-safe: the push happens once per open (ref-guarded) and cleanup
  // never navigates, so the dev double-mount can't auto-close the sheet.
  useEffect(() => {
    if (!open) return;
    triggerRef.current = document.activeElement as HTMLElement | null;
    openCount++;
    const main = document.querySelector('.app-main') as HTMLElement | null;
    const prevOverflow = main?.style.overflow;
    if (main) main.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
    if (!pushed.current) {
      history.pushState({ sheet: id }, '');
      pushed.current = true;
      openStack.push(id);
    }
    const onPop = () => {
      // only the top-most sheet handles browser-back (stacked sheets close one at a time)
      if (openStack[openStack.length - 1] !== id) return;
      openStack.pop();
      closedByPop.current = true;
      onClose();
    };
    window.addEventListener('popstate', onPop);
    const t = setTimeout(() => sheetRef.current?.focus({ preventScroll: true }), 60);
    return () => {
      clearTimeout(t);
      window.removeEventListener('popstate', onPop);
      const idx = openStack.lastIndexOf(id);
      if (idx >= 0 && !openRef.current) openStack.splice(idx, 1);
      openCount = Math.max(0, openCount - 1);
      if (openCount === 0) {
        if (main && prevOverflow !== undefined) main.style.overflow = prevOverflow;
        document.body.style.overflow = '';
      }
      // restore focus only on a real close, not the StrictMode remount
      if (!openRef.current) triggerRef.current?.focus?.();
    };
  }, [open, onClose, id]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
      if (e.key === 'Tab') {
        const root = sheetRef.current;
        if (!root) return;
        const els = root.querySelectorAll<HTMLElement>('button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])');
        if (!els.length) return;
        const first = els[0];
        const last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, close]);

  if (!open) return null;

  const onTouchStart = (e: React.TouchEvent) => {
    drag.current = { startY: e.touches[0].clientY, dy: 0, dragging: true };
  };
  const onTouchMove = (e: React.TouchEvent) => {
    if (!drag.current.dragging) return;
    const content = contentRef.current;
    const dy = e.touches[0].clientY - drag.current.startY;
    // only drag sheet when pulling down and content is at top
    if (dy > 0 && (content?.scrollTop ?? 0) <= 0) {
      drag.current.dy = dy;
      setOffset(dy);
    }
  };
  const onTouchEnd = () => {
    if (!drag.current.dragging) return;
    drag.current.dragging = false;
    const h = sheetRef.current?.getBoundingClientRect().height ?? 400;
    if (drag.current.dy > h * 0.25 || drag.current.dy > 140) close();
    else setOffset(0);
  };

  return (
    <div className="absolute inset-0 z-[70]" role="presentation">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-[2px] anim-fade"
        onClick={close}
        aria-hidden
      />
      <div className="absolute inset-x-0 bottom-0 flex justify-center" style={{ paddingBottom: keyboard > 0 ? keyboard : 0 }}>
        <div
          ref={sheetRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          tabIndex={-1}
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
          className={cn('w-full overflow-hidden rounded-t-[22px] border-t border-x border-white/12 bg-[#14151a] shadow-[0_-20px_60px_rgba(0,0,0,0.6)] outline-none', wide && 'max-w-[430px]')}
          style={{
            height: heights[snap],
            transform: `translateY(${offset}px)`,
            transition: drag.current.dragging ? 'none' : 'transform .22s ease-out',
            animation: offset === 0 ? 'sheet-up .26s cubic-bezier(.22,1,.36,1) both' : undefined,
          }}
        >
          <div className="flex min-h-[44px] cursor-grab items-center justify-center pt-2 active:cursor-grabbing" aria-hidden>
            <div className="h-1.5 w-10 rounded-full bg-white/20" />
          </div>
          <div className="flex items-center justify-between px-5 pb-3">
            <h2 id={titleId} className="font-display text-[17px] font-semibold tracking-tight text-white">{title}</h2>
            <button
              onClick={close}
              aria-label="Close panel"
              className="pressable flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] text-white"
            >
              <svg width={16} height={16} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><path d="M3 3l10 10M13 3L3 13" /></svg>
            </button>
          </div>
          <div ref={contentRef} className="safe-bottom h-[calc(100%-96px)] overflow-y-auto px-5 pb-8">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ConfirmSheet({ open, onClose, title, body, confirmLabel, onConfirm, danger }: {
  open: boolean; onClose: () => void; title: string; body: string; confirmLabel: string; onConfirm: () => void; danger?: boolean;
}) {
  return (
    <BottomSheet open={open} onClose={onClose} title={title} snap={40}>
      <p className="text-[15px] leading-6 text-[#d7d3c8]">{body}</p>
      <div className="mt-6 flex gap-3">
        <button onClick={onClose} className="pressable min-h-[52px] flex-1 rounded-2xl border border-white/15 bg-white/[0.06] font-display text-[15px] font-semibold text-white">Cancel</button>
        <button
          onClick={() => { onConfirm(); onClose(); }}
          className={cn('pressable min-h-[52px] flex-1 rounded-2xl font-display text-[15px] font-semibold text-white', danger ? 'border border-[#f87171]/50 bg-[#f87171]/15 text-[#f87171]' : 'btn-primary')}
        >
          {confirmLabel}
        </button>
      </div>
    </BottomSheet>
  );
}

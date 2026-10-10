import { useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Loader2, ArrowDown } from 'lucide-react';

export function PullToRefresh({ onRefresh, children }: { onRefresh: () => Promise<void>; children: ReactNode }) {
  const [pull, setPull] = useState(0);
  const [busy, setBusy] = useState(false);
  const start = useRef<number | null>(null);

  const onTouchStart = (e: React.TouchEvent<HTMLDivElement>) => {
    const scroller = e.currentTarget.closest('.app-main') as HTMLElement | null;
    if (scroller && scroller.scrollTop === 0 && !busy) start.current = e.touches[0].clientY;
  };
  const onTouchMove = (e: React.TouchEvent<HTMLDivElement>) => {
    if (start.current == null || busy) return;
    const dy = e.touches[0].clientY - start.current;
    if (dy > 0) setPull(Math.min(110, dy * 0.45));
  };
  const onTouchEnd = async () => {
    if (start.current == null) return;
    start.current = null;
    if (pull > 72 && !busy) {
      setBusy(true);
      try {
        await onRefresh();
      } finally {
        setBusy(false);
        setPull(0);
      }
    } else setPull(0);
  };

  return (
    <div onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}>
      <div
        className="flex items-center justify-center gap-2 overflow-hidden text-[13px] font-medium text-[#ff8a3d] transition-[height]"
        style={{ height: busy ? 48 : pull }}
        aria-live="polite"
      >
        {busy ? <Loader2 size={16} className="animate-spin" /> : pull > 72 ? <Loader2 size={16} className="animate-spin" /> : <ArrowDown size={16} />}
        {busy ? 'Refreshing…' : pull > 72 ? 'Release to refresh' : pull > 20 ? 'Pull to refresh' : ''}
      </div>
      {children}
    </div>
  );
}

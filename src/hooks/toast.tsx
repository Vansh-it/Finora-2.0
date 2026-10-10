import { createContext, useCallback, useContext, useState } from 'react';
import type { ReactNode } from 'react';
import { CheckCircle2, AlertTriangle, Info } from 'lucide-react';

interface ToastItem { id: number; msg: string; kind: 'ok' | 'warn' | 'info' }
const ToastCtx = createContext<(msg: string, kind?: ToastItem['kind']) => void>(() => {});

export const useToast = () => useContext(ToastCtx);

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((msg: string, kind: ToastItem['kind'] = 'ok') => {
    const id = nextId++;
    setItems((p) => [...p.slice(-2), { id, msg, kind }]);
    setTimeout(() => setItems((p) => p.filter((t) => t.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none absolute inset-x-0 bottom-[76px] z-[90] flex flex-col items-center gap-2 px-6" aria-live="polite">
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            className="pointer-events-auto flex max-w-full items-center gap-2 rounded-full border border-white/12 bg-[#1e1f26]/95 px-4 py-2.5 text-[13px] font-medium text-white shadow-[0_12px_32px_rgba(0,0,0,0.6)] backdrop-blur"
            style={{ animation: 'toast-up .25s ease-out both' }}
          >
            {t.kind === 'ok' && <CheckCircle2 size={16} className="shrink-0 text-[#34d399]" />}
            {t.kind === 'warn' && <AlertTriangle size={16} className="shrink-0 text-[#fbbf24]" />}
            {t.kind === 'info' && <Info size={16} className="shrink-0 text-[#7ab8ff]" />}
            <span className="truncate">{t.msg}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

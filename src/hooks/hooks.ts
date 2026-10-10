import { useCallback, useEffect, useRef, useState } from 'react';

export function useKeyboardInset(): number {
  const [inset, setInset] = useState(0);
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const update = () => {
      const covered = window.innerHeight - vv.height - vv.offsetTop;
      setInset(Math.max(0, Math.round(covered)));
    };
    vv.addEventListener('resize', update);
    vv.addEventListener('scroll', update);
    update();
    return () => {
      vv.removeEventListener('resize', update);
      vv.removeEventListener('scroll', update);
    };
  }, []);
  return inset;
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(mq.matches);
    const fn = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener('change', fn);
    return () => mq.removeEventListener('change', fn);
  }, []);
  return reduced;
}

// ---- tiny stale-while-revalidate cache (no react-query) ----
const MEM = new Map<string, { data: unknown; at: number }>();

export interface QueryState<T> {
  data: T | undefined;
  error: Error | null;
  loading: boolean;
  refreshing: boolean;
  refetch: () => Promise<void>;
}

export function useCachedQuery<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
  opts?: { ttlMs?: number; enabled?: boolean },
): QueryState<T> {
  const ttl = opts?.ttlMs ?? 60_000;
  const enabled = opts?.enabled ?? true;
  const cached = MEM.get(key);
  const [data, setData] = useState<T | undefined>(cached ? (cached.data as T) : undefined);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(enabled && !cached);
  const [refreshing, setRefreshing] = useState(false);
  const ctrl = useRef<AbortController | null>(null);

  const refetch = useCallback(async () => {
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    if (MEM.get(key)) setRefreshing(true);
    else setLoading(true);
    try {
      const d = await fetcher(c.signal);
      if (c.signal.aborted) return;
      MEM.set(key, { data: d, at: Date.now() });
      setData(d);
      setError(null);
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      setError(e as Error);
    } finally {
      if (!c.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [key, fetcher]);

  useEffect(() => {
    if (!enabled) return;
    const hit = MEM.get(key);
    if (hit && Date.now() - hit.at < ttl) {
      setData(hit.data as T);
      setLoading(false);
      return;
    }
    void refetch();
    return () => ctrl.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);

  return { data, error, loading, refreshing, refetch };
}

// ---- animated count-up ----
export function useCountUp(target: number, duration = 900, enabled = true): number {
  const reduced = useReducedMotion();
  const [val, setVal] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    if (reduced) {
      setVal(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(target * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration, enabled, reduced]);
  return val;
}

// ---- online status ----
export function useOnline(): boolean {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);
  return online;
}

// ---- reveal on scroll ----
export function useReveal<T extends HTMLElement>(): React.RefObject<T | null> {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const kids = el.querySelectorAll('[data-reveal]');
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            (e.target as HTMLElement).classList.add('anim-rise');
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12 },
    );
    kids.forEach((k) => io.observe(k));
    return () => io.disconnect();
  }, []);
  return ref;
}

import { Component, useEffect } from 'react';
import type { ReactNode } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ChevronLeft, Home, LayoutDashboard, MessageSquare, Search, User, WifiOff, BookOpen, Star } from 'lucide-react';
import { cn } from '../lib/cn';
import { isAuthed } from '../lib/auth';
import { useKeyboardInset, useOnline } from '../hooks/hooks';

// ---------- TopBar ----------
export function TopBar({ title, action, root }: { title?: string; action?: ReactNode; root?: boolean }) {
  const nav = useNavigate();
  const loc = useLocation();
  const canBack = !root && loc.key !== 'default';
  return (
    <header className="safe-top z-40 border-b-2 border-white/10 bg-[#0a0a0c]/95 backdrop-blur">
      <div className="flex h-[52px] items-center gap-2 px-3">
        <div className="w-16 shrink-0">
          {canBack ? (
            <button onClick={() => nav(-1)} aria-label="Go back" className="pressable flex h-11 w-11 items-center justify-center rounded-xl text-white">
              <ChevronLeft size={22} />
            </button>
          ) : (
            <Link to="/" aria-label="Finora home" className="flex h-11 items-center px-1 font-display text-[19px] font-bold tracking-tight text-white">
              Finora<span className="text-[#ff5a1f]">.</span>
            </Link>
          )}
        </div>
        <h1 className="flex-1 truncate text-center font-display text-[15px] font-semibold tracking-tight text-white">
          {title ?? ''}
        </h1>
        <div className="flex w-16 shrink-0 items-center justify-end">{action}</div>
      </div>
    </header>
  );
}

// ---------- BottomTabBar ----------
const AUThed_TABS = [
  { to: '/research', label: 'Research', icon: Search },
  { to: '/dashboard', label: 'Board', icon: LayoutDashboard },
  { to: '/chat', label: 'Ask AI', icon: MessageSquare, center: true },
  { to: '/reviews', label: 'Reviews', icon: Star },
  { to: '/profile', label: 'Me', icon: User },
];
const GUEST_TABS = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/methodology', label: 'Method', icon: BookOpen },
  { to: '/reviews', label: 'Reviews', icon: Star },
  { to: '/auth', label: 'Sign in', icon: User },
];

const HIDE_ON = ['/auth'];

export function BottomTabBar() {
  const loc = useLocation();
  const nav = useNavigate();
  const inset = useKeyboardInset();
  const authed = isAuthed();

  if (HIDE_ON.some((p) => loc.pathname.startsWith(p))) return null;
  if (loc.pathname === '/research' && new URLSearchParams(loc.search).has('ticker')) return null;
  if (inset > 80) return null;

  const tabs = authed ? AUThed_TABS : GUEST_TABS;
  const isActive = (to: string) => (to === '/' ? loc.pathname === '/' : loc.pathname.startsWith(to));

  return (
    <nav aria-label="Primary" className="safe-bottom z-40 border-t border-white/10 bg-[#0e0e11]/98 backdrop-blur">
      <div className="flex h-[64px] items-stretch">
        {tabs.map((t) => {
          const active = isActive(t.to);
          const Icon = t.icon;
          const center = 'center' in t && t.center;
          return (
            <button
              key={t.to + t.label}
              onClick={() => nav(t.to)}
              aria-current={active ? 'page' : undefined}
              className="pressable relative flex min-h-[64px] flex-1 flex-col items-center justify-center gap-1"
            >
              {center ? (
                <span className={cn(
                  '-mt-6 flex h-[52px] w-[52px] items-center justify-center rounded-2xl border border-white/20',
                  active ? 'btn-primary' : 'bg-[#1e1f26] text-white',
                )}>
                  <Icon size={22} fill={active ? 'currentColor' : 'none'} />
                </span>
              ) : (
                <Icon size={22} className={active ? 'text-[#ff5a1f]' : 'text-[#6b675c]'} fill={active ? 'currentColor' : 'none'} strokeWidth={active ? 0 : 2} />
              )}
              <span className={cn(
                'font-mono text-[10px] font-medium uppercase tracking-[0.08em]',
                active ? 'text-white underline decoration-[#ff5a1f] decoration-2 underline-offset-4' : 'text-[#6b675c]',
              )}>
                {t.label}
              </span>
              {active && !center && <span className="absolute top-0 h-[3px] w-10 rounded-b-full bg-[#ff5a1f]" />}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

// ---------- offline banner ----------
export function OfflineBanner() {
  const online = useOnline();
  if (online) return null;
  return (
    <div role="alert" className="z-50 flex items-center justify-center gap-2 bg-[#fbbf24] px-4 py-2 text-[13px] font-semibold text-black">
      <WifiOff size={15} /> You&apos;re offline — showing saved data
    </div>
  );
}

// ---------- error boundary ----------
export class ErrorBoundary extends Component<{ children: ReactNode }, { bad: boolean }> {
  state = { bad: false };
  static getDerivedStateFromError() { return { bad: true }; }
  render() {
    if (this.state.bad) {
      return (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
          <p className="font-display text-5xl font-bold text-white">404</p>
          <p className="text-sm text-[#a7a29a]">This screen hit a snag.</p>
          <button onClick={() => window.location.reload()} className="pressable min-h-[52px] rounded-2xl btn-primary px-8 font-display text-[15px] font-semibold text-white">
            Reload Finora
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---------- protected route ----------
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const loc = useLocation();
  if (!isAuthed()) {
    const params = new URLSearchParams(loc.search);
    const ticker = params.get('ticker');
    return <Navigate to="/auth" replace state={{ from: loc.pathname + loc.search, ticker }} />;
  }
  return <>{children}</>;
}

// ---------- scroll restoration per route ----------
const POS = new Map<string, number>();
export function ScrollKeeper({ mainRef }: { mainRef: React.RefObject<HTMLElement | null> }) {
  const loc = useLocation();
  useEffect(() => {
    const main = mainRef.current;
    if (!main) return;
    const save = () => POS.set(loc.key, main.scrollTop);
    main.addEventListener('scroll', save, { passive: true });
    return () => main.removeEventListener('scroll', save);
  }, [loc.key, mainRef]);
  useEffect(() => {
    const main = mainRef.current;
    if (main) main.scrollTop = POS.get(loc.key) ?? 0;
  }, [loc.pathname, loc.search, mainRef]);
  return null;
}

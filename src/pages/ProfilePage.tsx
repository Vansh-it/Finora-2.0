import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Bell, Check, ChevronRight, FileText, LogOut, Pencil, ShieldCheck, Star, X, Zap,
} from 'lucide-react';
import { getHistory, getUsage, signOutUser, updateProfile } from '../lib/api';
import { clearSession, getUser } from '../lib/auth';
import { ConfirmSheet } from '../components/BottomSheet';
import { Button, ProgressBar, Skeleton, TickerChip } from '../components/ui';
import { PixelAvatar } from '../components/PixelAvatar';
import { formatDate } from '../lib/format';
import { useCachedQuery } from '../hooks/hooks';
import { useToast } from '../hooks/toast';

// Account + preferences entries. Kept as data so the rows stay consistent.
const ACCOUNT_ROWS = [
  { label: 'About Finora', sub: 'What Finora is and how it works', to: '/about', icon: FileText },
  { label: 'Methodology', sub: 'How every number is verified', to: '/methodology', icon: ShieldCheck },
  { label: 'Reviews', sub: 'See what other researchers say', to: '/reviews', icon: Star },
  { label: 'Terms of Service', sub: 'The rules of the road', to: '/terms', icon: FileText },
  { label: 'Privacy Policy', sub: 'How your data is handled', to: '/privacy', icon: ShieldCheck },
] as const;

export function ProfilePage() {
  const nav = useNavigate();
  const toast = useToast();
  const user = getUser();
  const usage = useCachedQuery('usage', async () => getUsage());
  const hist = useCachedQuery('history', async () => getHistory());

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(user?.name ?? '');
  const [saving, setSaving] = useState(false);
  const [confirmOut, setConfirmOut] = useState(false);
  const [displayName, setDisplayName] = useState(user?.name ?? '');
  const [alerts, setAlerts] = useState(false);

  // Deterministic identity seed — the same account always draws the same character.
  const seed = user?.email ?? user?.name ?? 'finora';

  const save = async () => {
    const prev = displayName;
    setDisplayName(name.trim());
    setEditing(false);
    setSaving(true);
    try {
      const r = await updateProfile(name);
      setDisplayName(r.name);
      toast('Name updated');
    } catch (e) {
      setDisplayName(prev);
      setName(prev);
      toast(e instanceof Error ? e.message : 'Update failed', 'warn');
    } finally {
      setSaving(false);
    }
  };

  const signOut = () => {
    clearSession();
    void signOutUser();
    nav('/', { replace: true });
    toast('Signed out', 'info');
  };

  const toggleAlerts = async () => {
    if (!alerts && 'Notification' in window && Notification.permission === 'default') {
      try { await Notification.requestPermission(); } catch { /* ignore */ }
    }
    setAlerts((v) => !v);
  };

  const recent = hist.data?.slice(0, 3) ?? [];

  return (
    <div className="grid-glow px-5 pb-10 pt-6">
      {/* Identity */}
      <div className="card-dark anim-rise relative overflow-hidden p-5">
        <div className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-[#ff5a1f]/10 blur-2xl" aria-hidden />
        <div className="relative flex items-center gap-4">
          <PixelAvatar seed={seed} size={72} className="shrink-0" />
          <div className="min-w-0 flex-1">
            {editing ? (
              <div className="flex items-center gap-1.5">
                <input
                  aria-label="Your name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoFocus
                  className="min-h-[48px] w-full rounded-xl border border-[#ff5a1f]/60 bg-black/40 px-3 text-[16px] text-white outline-none"
                />
                <button onClick={save} disabled={saving} aria-label="Save name" className="pressable flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#34d399] text-black disabled:opacity-50">
                  <Check size={18} />
                </button>
                <button onClick={() => { setEditing(false); setName(displayName); }} aria-label="Cancel editing" className="pressable flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/15 text-white">
                  <X size={18} />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-1">
                <h1 className="truncate font-display text-[21px] font-bold text-white">{displayName || 'Researcher'}</h1>
                <button onClick={() => setEditing(true)} aria-label="Edit name" className="pressable flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-[#a7a29a]">
                  <Pencil size={17} />
                </button>
              </div>
            )}
            <p className="truncate text-[13px] text-[#a7a29a]">{user?.email}</p>
            <span className="mono-label mt-2 inline-flex items-center gap-1 rounded-md border border-[#34d399]/40 bg-[#34d399]/10 px-2 py-0.5 text-[10px] text-[#34d399]">
              <Zap size={11} /> Free tier
            </span>
          </div>
        </div>
      </div>

      {/* Usage */}
      <div className="card-dark anim-rise stagger-1 mt-3 p-4">
        <div className="flex items-center justify-between">
          <p className="mono-label text-[#6b675c]">Research usage</p>
          <span className="mono-label text-[#6b675c]">Resets every 24h</span>
        </div>
        {usage.data ? (
          <>
            <p className="mt-1.5 text-[14px] text-[#a7a29a]">
              <span className="num text-[24px] font-semibold text-white">{usage.data.remaining}</span> of {usage.data.limit} researches left today
            </p>
            <ProgressBar value={usage.data.used} max={usage.data.limit} className="mt-2.5" />
          </>
        ) : (
          <Skeleton className="mt-3 h-8 w-full" />
        )}
      </div>

      {/* Latest researches */}
      <div className="anim-rise stagger-2 mt-6">
        {/* items-center keeps the label and "View all" on one line; -my-2 cancels
            the 44px tap target's height so it doesn't open a gap under the label. */}
        <div className="mb-3 flex items-center justify-between">
          <p className="mono-label text-[#6b675c]">Latest researches</p>
          <Link to="/history" className="-my-2 pressable flex min-h-[44px] items-center gap-0.5 font-mono text-[11px] tracking-wider text-[#ff8a3d]">
            View all <ChevronRight size={13} />
          </Link>
        </div>
        <div className="space-y-2.5">
          {hist.loading && !hist.data && [0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
          {!hist.loading && recent.length === 0 && (
            <div className="card-dark p-4 text-center">
              <p className="text-[14px] text-[#a7a29a]">No researches yet.</p>
              <Link to="/research" className="pressable mt-2 inline-flex min-h-[44px] items-center font-display text-[14px] font-semibold text-[#ff8a3d]">
                Start your first research
              </Link>
            </div>
          )}
          {recent.map((h) => (
            <Link key={h.sessionId} to={`/dashboard?session_id=${h.sessionId}`} className="card-dark pressable flex items-center gap-3 p-3.5">
              <TickerChip ticker={h.ticker} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-medium text-white">{h.company}</p>
                {h.date && <p className="truncate font-mono text-[11px] text-[#6b675c]">{formatDate(h.date)}{h.period ? ` · ${h.period}` : ''}</p>}
              </div>
              <ChevronRight size={16} className="shrink-0 text-[#6b675c]" />
            </Link>
          ))}
        </div>
      </div>

      {/* Account */}
      <div className="anim-rise stagger-3 mt-6">
        <p className="mono-label mb-2 text-[#6b675c]">Account</p>
        <div className="overflow-hidden rounded-2xl border border-white/10">
          {ACCOUNT_ROWS.map((r) => (
            <Link key={r.to} to={r.to} className="pressable flex min-h-[60px] items-center gap-3 border-b border-white/[0.06] bg-[#14151a] px-4 last:border-0">
              <r.icon size={18} className="shrink-0 text-[#ff8a3d]" />
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-medium text-white">{r.label}</p>
                <p className="truncate text-[12px] text-[#6b675c]">{r.sub}</p>
              </div>
              <ChevronRight size={17} className="shrink-0 text-[#6b675c]" />
            </Link>
          ))}
        </div>
      </div>

      {/* Preferences */}
      <div className="anim-rise stagger-3 mt-6">
        <p className="mono-label mb-2 text-[#6b675c]">Preferences</p>
        <div className="overflow-hidden rounded-2xl border border-white/10">
          <button
            onClick={toggleAlerts}
            aria-pressed={alerts}
            className="pressable flex min-h-[60px] w-full items-center gap-3 border-b border-white/[0.06] bg-[#14151a] px-4 text-left last:border-0"
          >
            <Bell size={18} className="shrink-0 text-[#ff8a3d]" />
            <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-white">Research alerts</span>
            <span className={alerts ? 'mono-label shrink-0 text-[11px] text-[#34d399]' : 'mono-label shrink-0 text-[11px] text-[#6b675c]'}>{alerts ? 'ON' : 'OFF'}</span>
          </button>
        </div>
      </div>

      {/* Sign out */}
      <div className="anim-rise stagger-3 mt-6">
        <Button variant="danger" onClick={() => setConfirmOut(true)}>
          <LogOut size={17} /> Sign out
        </Button>
        <p className="mt-3 text-center font-mono text-[10px] text-[#6b675c]">Finora v2.0 · Every number has a receipt</p>
      </div>

      <ConfirmSheet
        open={confirmOut} onClose={() => setConfirmOut(false)}
        title="Sign out?" body="You'll need to sign back in to research and chat." confirmLabel="Sign out" danger
        onConfirm={signOut}
      />
    </div>
  );
}

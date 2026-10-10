import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Check, LogOut, Pencil, X } from 'lucide-react';
import { getHistory, getUsage, signOutUser, updateProfile } from '../lib/api';
import { clearSession, getUser } from '../lib/auth';
import { ConfirmSheet } from '../components/BottomSheet';
import { Button, ProgressBar, Skeleton, TickerChip } from '../components/ui';
import { useCachedQuery } from '../hooks/hooks';
import { useToast } from '../hooks/toast';

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

  return (
    <div className="grid-glow px-5 pb-10 pt-6">
      <div className="card-dark anim-rise flex items-center gap-4 p-5">
        <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-[#ff5a1f] to-[#ffb25c] font-display text-[24px] font-bold text-black">
          {(displayName || 'F')[0].toUpperCase()}
        </span>
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
            <div className="flex items-center gap-2">
              <h1 className="truncate font-display text-[20px] font-bold text-white">{displayName}</h1>
              <button onClick={() => setEditing(true)} aria-label="Edit name" className="pressable flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-[#a7a29a]">
                <Pencil size={17} />
              </button>
            </div>
          )}
          <p className="mt-0.5 truncate text-[13px] text-[#a7a29a]">{user?.email}</p>
          <span className="mono-label mt-1.5 inline-block rounded-md border border-[#34d399]/40 bg-[#34d399]/10 px-1.5 py-0.5 text-[#34d399]">Free tier</span>
        </div>
      </div>

      <div className="card-dark anim-rise stagger-1 mt-3 p-4">
        <p className="mono-label text-[#6b675c]">Research usage</p>
        {usage.data ? (
          <>
            <p className="mt-1 text-[14px] text-white">{usage.data.remaining} of {usage.data.limit} remaining</p>
            <ProgressBar value={usage.data.used} max={usage.data.limit} className="mt-2" />
          </>
        ) : <Skeleton className="mt-2 h-4 w-full" />}
      </div>

      <div className="anim-rise stagger-2 mt-5">
        <p className="mono-label mb-2 text-[#6b675c]">Latest researches</p>
        <div className="space-y-2">
          {hist.data?.slice(0, 3).map((h) => (
            <Link key={h.sessionId} to={`/dashboard?session_id=${h.sessionId}`} className="card-dark pressable flex items-center gap-3 p-3.5">
              <TickerChip ticker={h.ticker} />
              <span className="min-w-0 flex-1 truncate text-[14px] text-white">{h.company}</span>
            </Link>
          )) ?? <Skeleton className="h-14 w-full" />}
        </div>
      </div>

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

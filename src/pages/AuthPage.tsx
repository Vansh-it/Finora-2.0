import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { FileText, ShieldCheck } from 'lucide-react';
import { Button, Field, SegmentedControl, TickerChip } from '../components/ui';
import { ApiError, signIn, signUp } from '../lib/api';
import { clearPendingTicker, setSession } from '../lib/auth';
import { useToast } from '../hooks/toast';
import { useKeyboardInset } from '../hooks/hooks';

type Mode = 'Sign In' | 'Sign Up';

export function AuthPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const toast = useToast();
  const inset = useKeyboardInset();
  const [mode, setMode] = useState<Mode>('Sign Up');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverErr, setServerErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const pendingTicker: string | undefined = (loc.state as { ticker?: string } | null)?.ticker
    ?? sessionStorage.getItem('finora_pending_ticker') ?? undefined;

  const strength = pw.length === 0 ? '' : pw.length < 8 ? 'Too short — use 8+ characters' : /[A-Z]/.test(pw) && /[0-9]/.test(pw) ? 'Strong password' : 'Good — add a number or capital letter';

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (mode === 'Sign Up' && name.trim().length < 2) e.name = 'Please enter your name.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) e.email = 'Enter a valid email address.';
    if (pw.length < 8) e.pw = 'Password must be at least 8 characters.';
    setErrors(e);
    if (Object.keys(e).length) {
      const first = mode === 'Sign Up' && e.name ? 'name' : e.email ? 'email' : 'password';
      document.getElementById(first)?.focus();
    }
    return Object.keys(e).length === 0;
  };

  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setServerErr(null);
    if (!validate()) return;
    setBusy(true);
    try {
      const res = mode === 'Sign Up'
        ? await signUp(name.trim(), email.trim(), pw)
        : await signIn(email.trim(), pw);
      setSession(res.token, res.user);
      const ticker = pendingTicker;
      clearPendingTicker();
      toast(mode === 'Sign Up' ? `Welcome, ${res.user.name}` : `Welcome back, ${res.user.name}`);
      nav(ticker ? `/research?ticker=${encodeURIComponent(ticker)}` : '/research', { replace: true });
    } catch (e) {
      setServerErr(e instanceof ApiError ? e.message : 'Could not reach Finora. Check your connection and try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid-glow flex min-h-full flex-col px-5 pb-6 pt-6">
      <div className="anim-rise">
        <p className="font-display text-[26px] font-bold tracking-tight text-white">Finora<span className="text-[#ff5a1f]">.</span></p>
        <p className="mt-1 text-[15px] text-[#d7d3c8]">Verify the numbers behind every company.</p>
        <div className="mt-4 hidden min-h-[90px] gap-2 min-[380px]:flex" aria-hidden>
          <div className="card-dark flex flex-1 rotate-[-2deg] items-center gap-2 p-3">
            <FileText size={18} className="shrink-0 text-[#ff8a3d]" />
            <p className="font-mono text-[11px] text-[#d7d3c8]">10-K parsed<br />in seconds</p>
          </div>
          <div className="card-dark flex flex-1 rotate-[1.5deg] items-center gap-2 p-3">
            <ShieldCheck size={18} className="shrink-0 text-[#34d399]" />
            <p className="font-mono text-[11px] text-[#d7d3c8]">Every number<br />has a receipt</p>
          </div>
        </div>
      </div>

      {pendingTicker && (
        <div className="anim-pop mt-4 flex items-center gap-2.5 rounded-2xl border border-[#ff5a1f]/40 bg-[#ff5a1f]/[0.08] p-3.5" role="status">
          <span className="text-[14px] text-[#d7d3c8]">You asked to research</span>
          <TickerChip ticker={pendingTicker} />
        </div>
      )}

      <div className="anim-rise stagger-1 mt-5">
        <SegmentedControl options={['Sign In', 'Sign Up'] as const} value={mode} onChange={setMode} />
      </div>

      <form onSubmit={submit} noValidate className="anim-rise stagger-2 mt-5 space-y-4">
        {mode === 'Sign Up' && (
          <Field label="Name" id="name" value={name} onChange={(e) => setName(e.target.value)} onBlur={validate}
            placeholder="Ada Lovelace" autoComplete="name" enterKeyHint="next" error={errors.name} />
        )}
        <Field label="Email" id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} onBlur={mode === 'Sign In' ? undefined : validate}
          placeholder="you@example.com" autoComplete="email" inputMode="email" enterKeyHint="next" error={errors.email} />
        <Field label="Password" id="password" type="password" value={pw} onChange={(e) => setPw(e.target.value)}
          placeholder="8+ characters" autoComplete={mode === 'Sign Up' ? 'new-password' : 'current-password'}
          enterKeyHint="go" error={errors.pw} hint={mode === 'Sign Up' ? strength : undefined} />
        <div aria-live="assertive">
          {serverErr && <p role="alert" className="rounded-xl border border-[#f87171]/40 bg-[#f87171]/10 p-3 text-[13px] text-[#f87171]">{serverErr}</p>}
        </div>
        <div style={{ paddingBottom: inset > 0 ? inset : 0 }}>
          <Button type="submit" size="lg" loading={busy}>
            {mode === 'Sign Up' ? 'Create account' : 'Sign in'}
          </Button>
          <p className="mt-3 text-center font-mono text-[11px] text-[#6b675c]">
            {mode === 'Sign Up' ? 'Free · 5 researches / 24h · No card' : '5 researches refresh every 24 hours'}
          </p>
        </div>
      </form>
    </div>
  );
}

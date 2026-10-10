import { useEffect, useRef, useState } from 'react';
import { ArrowDown, SendHorizonal, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { followUps, sendChat } from '../lib/api';
import type { ChatMsg } from '../lib/api';
import { useKeyboardInset } from '../hooks/hooks';
import { useToast } from '../hooks/toast';

const SUGGESTIONS = ['Explain ROIC like I\'m new', 'What is a 10-K?', 'How do you verify numbers?', 'Piotroski vs Altman?'];

export function ChatPage() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showJump, setShowJump] = useState(false);
  const inset = useKeyboardInset();
  const toast = useToast();
  const scrollRef = useRef<HTMLDivElement>(null);
  const pressTimer = useRef<number>(0);
  const pinned = useRef(true);

  const scrollDown = (smooth = true) => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  };

  useEffect(() => {
    if (pinned.current) scrollDown(false);
  }, [msgs]);

  const send = async (text: string) => {
    const t = text.trim();
    if (!t || busy) return;
    setError(null);
    const next: ChatMsg[] = [...msgs.slice(-9), { role: 'user', text: t }];
    setMsgs(next);
    setInput('');
    setBusy(true);
    pinned.current = true;
    try {
      const res = await sendChat(next);
      setMsgs([...next, { role: 'assistant', text: res.text, ms: res.ms }]);
      setTimeout(() => scrollDown(), 50);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Finora AI is unreachable right now.');
    } finally {
      setBusy(false);
    }
  };

  const copyMsg = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast('Message copied');
    } catch {
      toast('Copy unavailable', 'warn');
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-white/10 px-5 py-3">
        <h1 className="font-display text-[20px] font-bold tracking-tight text-white">Talk to your research analyst</h1>
        <p className="mono-label mt-0.5 text-[#6b675c]">Finora AI · cites filings</p>
      </div>

      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
          pinned.current = nearBottom;
          setShowJump(!nearBottom && msgs.length > 2);
        }}
        className="relative flex-1 space-y-3 overflow-y-auto px-5 py-4"
        aria-live="polite"
        aria-label="Chat messages"
      >
        {msgs.length === 0 && !busy && (
          <div className="anim-fade pt-6 text-center">
            <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-[#ff5a1f]/15">
              <Sparkles size={24} className="text-[#ff8a3d]" />
            </span>
            <p className="mt-3 font-display text-[17px] font-semibold text-white">Ask about markets, metrics, filings</p>
            <p className="mt-1 text-[14px] text-[#a7a29a]">Answers are grounded in verified data.</p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)} className="pressable min-h-[44px] rounded-full border border-white/12 bg-white/[0.04] px-4 text-[13px] text-[#d7d3c8]">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {msgs.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <div
              onTouchStart={() => { pressTimer.current = window.setTimeout(() => copyMsg(m.text), 500); }}
              onTouchEnd={() => window.clearTimeout(pressTimer.current)}
              onContextMenu={(e) => { e.preventDefault(); copyMsg(m.text); }}
              className={
                m.role === 'user'
                  ? 'max-w-[85%] rounded-2xl rounded-br-md bg-[#ff5a1f] px-3.5 py-2.5 text-[14px] leading-6 text-white anim-rise'
                  : 'memo-md max-w-[88%] rounded-2xl rounded-bl-md border border-white/10 bg-white/[0.04] px-3.5 py-2.5 anim-rise'
              }
            >
              {m.role === 'user' ? m.text : <ReactMarkdown>{m.text}</ReactMarkdown>}
              {m.role === 'assistant' && m.ms != null && <p className="mt-1 font-mono text-[10px] text-[#6b675c]">Finora AI · {m.ms}ms</p>}
              {m.role === 'assistant' && i === msgs.length - 1 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {followUps().slice(0, 2).map((f) => (
                    <button key={f} onClick={() => send(f)} className="pressable min-h-[40px] rounded-full border border-[#ff5a1f]/35 bg-[#ff5a1f]/[0.08] px-3 text-[12px] text-[#ffb25c]">
                      {f}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex items-center gap-1 px-1" role="status" aria-label="Finora is typing">
            {[0, 1, 2].map((i) => <span key={i} className="typing-dot h-2 w-2 rounded-full bg-[#ff8a3d]" />)}
          </div>
        )}

        {error && (
          <div role="alert" className="rounded-2xl border border-[#f87171]/40 bg-[#f87171]/10 p-3.5 text-[13px] text-[#f87171]">
            {error}
            <button
              onClick={() => { const last = [...msgs].reverse().find((m) => m.role === 'user'); if (last) send(last.text); }}
              className="pressable ml-2 min-h-[44px] rounded-lg border border-[#f87171]/40 px-3 font-semibold"
            >
              Retry
            </button>
          </div>
        )}
      </div>

      {showJump && (
        <div className="flex justify-center">
          <button onClick={() => { pinned.current = true; scrollDown(); }} className="pressable absolute bottom-[150px] z-10 flex min-h-[44px] items-center gap-1.5 rounded-full border border-white/15 bg-[#1e1f26] px-4 text-[13px] font-medium text-white shadow-xl" aria-label="Jump to latest message">
            <ArrowDown size={15} /> Latest
          </button>
        </div>
      )}

      <form
        onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="border-t border-white/10 bg-[#0e0e11] px-4 pb-3 pt-2.5"
        style={{ paddingBottom: `calc(12px + ${inset > 0 ? inset : 0}px)` }}
      >
        <div className="flex items-end gap-2">
          <textarea
            aria-label="Message Finora AI"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={1}
            placeholder="Ask about any company…"
            className="max-h-[120px] min-h-[48px] flex-1 resize-none rounded-2xl border border-white/12 bg-black/40 px-4 py-3 text-white outline-none placeholder:text-[#6b675c] focus:border-[#ff5a1f]/60"
          />
          <button
            type="submit" disabled={!input.trim() || busy} aria-label="Send message"
            className="btn-primary pressable flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-white disabled:opacity-50"
          >
            <SendHorizonal size={19} />
          </button>
        </div>
        <p className="mt-1.5 text-center font-mono text-[10px] text-[#6b675c]">Long-press a message to copy · Finora AI can make mistakes — verify receipts</p>
      </form>
    </div>
  );
}

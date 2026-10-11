import { useEffect, useRef, useState } from 'react';
import { ArrowDown, SendHorizonal, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { followUps, sendChat, streamChat } from '../lib/api';
import type { ChatMsg } from '../lib/api';
import { useKeyboardInset } from '../hooks/hooks';
import { useToast } from '../hooks/toast';
import CrystalizedBall from '../components/CrystalizedBall';
import { cn } from '../lib/cn';

const SUGGESTIONS = [
  "Explain ROIC like I'm new",
  'What is a 10-K?',
  'How do you verify numbers?',
  'Piotroski vs Altman?',
];

export function ChatPage() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showJump, setShowJump] = useState(false);
  const [started, setStarted] = useState(false);
  const [showBall, setShowBall] = useState(true);
  const inset = useKeyboardInset();
  const toast = useToast();
  const scrollRef = useRef<HTMLDivElement>(null);
  const pressTimer = useRef<number>(0);
  const pinned = useRef(true);

  // Once the conversation starts, let the ball fade out then stop the WebGL
  // loop entirely — it is purely an intro flourish and shouldn't draw battery.
  useEffect(() => {
    if (!started) return;
    const t = window.setTimeout(() => setShowBall(false), 750);
    return () => window.clearTimeout(t);
  }, [started]);

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
    setStarted(true);
    const history: ChatMsg[] = [...msgs.slice(-9), { role: 'user', text: t }];
    setMsgs([...history, { role: 'assistant', text: '' }]);
    setInput('');
    setBusy(true);
    pinned.current = true;
    const t0 = performance.now();
    let acc = '';
    try {
      for await (const chunk of streamChat(history)) {
        acc += chunk;
        setMsgs([...history, { role: 'assistant', text: acc }]);
      }
      if (!acc) throw new Error('empty stream');
      setMsgs([...history, { role: 'assistant', text: acc, ms: Math.round(performance.now() - t0) }]);
      setTimeout(() => scrollDown(), 50);
    } catch {
      // Streaming can be unavailable (older proxy, no body). Keep any partial
      // answer; otherwise fall back to the non-streaming endpoint.
      if (acc) {
        setMsgs([...history, { role: 'assistant', text: acc, ms: Math.round(performance.now() - t0) }]);
      } else {
        try {
          const res = await sendChat(history);
          setMsgs([...history, { role: 'assistant', text: res.text, ms: res.ms }]);
          setTimeout(() => scrollDown(), 50);
        } catch (e) {
          setMsgs(history);
          setError(e instanceof Error ? e.message : 'Finora AI is unreachable right now.');
        }
      }
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

  const lastIdx = msgs.length - 1;

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      <div className="relative min-h-0 flex-1">
        {/* ── Intro: crystalized ball + title + suggested questions ── */}
        <div
          className={cn(
            'absolute inset-0 flex flex-col transition-opacity duration-500',
            started ? 'pointer-events-none opacity-0' : 'opacity-100',
          )}
          aria-hidden={started}
        >
          <div className="relative min-h-[42%] flex-1 overflow-hidden">
            {showBall && (
              <CrystalizedBall
                preset="ember"
                color="#FF6B00"
                theme="dark"
                size={0.62}
                speed={0.9}
                dustSpeed={1.1}
                particleCount={9000}
                interactive
                hoverStrength={0.4}
                intro
              />
            )}
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-[#0a0a0c] to-transparent" />
          </div>
          <div className="relative px-6 pb-4 text-center">
            <span className="mono-label text-[#ff8a3d]">Finora AI · cites filings</span>
            <h1 className="mt-2 font-display text-[24px] font-bold leading-[30px] tracking-tight text-white">
              Ask your research analyst
            </h1>
            <p className="mx-auto mt-2 max-w-[300px] text-[14px] leading-6 text-[#a7a29a]">
              Answers are grounded in verified numbers — every claim links back to a source.
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-2 px-5 pb-4">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="pressable min-h-[44px] rounded-full border border-[#ff5a1f]/30 bg-[#ff5a1f]/[0.08] px-4 text-[13px] text-[#ffb25c]"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* ── Conversation ── */}
        <div
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
            pinned.current = nearBottom;
            setShowJump(!nearBottom && msgs.length > 2);
          }}
          className={cn(
            'h-full space-y-3 overflow-y-auto px-5 py-4 transition-opacity duration-500',
            started ? 'opacity-100' : 'pointer-events-none opacity-0',
          )}
          aria-live="polite"
          aria-label="Chat messages"
          aria-hidden={!started}
        >
          {msgs.map((m, i) => {
            if (m.role === 'user') {
              return (
                <div key={i} className="flex justify-end">
                  <div
                    onTouchStart={() => { pressTimer.current = window.setTimeout(() => copyMsg(m.text), 500); }}
                    onTouchEnd={() => window.clearTimeout(pressTimer.current)}
                    onContextMenu={(e) => { e.preventDefault(); copyMsg(m.text); }}
                    className="anim-rise max-w-[85%] rounded-2xl rounded-br-md bg-[#ff5a1f] px-3.5 py-2.5 text-[14px] leading-6 text-white"
                  >
                    {m.text}
                  </div>
                </div>
              );
            }
            const streaming = busy && i === lastIdx;
            return (
              <div key={i} className="flex items-start gap-2">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#ff5a1f]/15">
                  <Sparkles size={14} className="text-[#ff8a3d]" />
                </span>
                <div
                  onTouchStart={() => { if (m.text) pressTimer.current = window.setTimeout(() => copyMsg(m.text), 500); }}
                  onTouchEnd={() => window.clearTimeout(pressTimer.current)}
                  onContextMenu={(e) => { if (m.text) { e.preventDefault(); copyMsg(m.text); } }}
                  className="anim-rise max-w-[88%] rounded-2xl rounded-bl-md border border-white/10 bg-white/[0.04] px-3.5 py-2.5"
                >
                  {m.text === '' && busy ? (
                    <span className="flex h-6 items-center gap-1" role="status" aria-label="Finora is thinking">
                      {[0, 1, 2].map((d) => <span key={d} className="typing-dot h-2 w-2 rounded-full bg-[#ff8a3d]" />)}
                    </span>
                  ) : (
                    <div className="memo-md">
                      <ReactMarkdown>{m.text}</ReactMarkdown>
                      {streaming && <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-[#ff8a3d] align-text-bottom" />}
                    </div>
                  )}
                  {m.text !== '' && m.ms != null && <p className="mt-1 font-mono text-[10px] text-[#6b675c]">Finora AI · {m.ms}ms</p>}
                  {!busy && i === lastIdx && m.text !== '' && (
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
            );
          })}

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
          <button
            onClick={() => { pinned.current = true; scrollDown(); }}
            className="pressable absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-white/15 bg-[#1e1f26] px-4 py-2 text-[13px] font-medium text-white shadow-xl"
            aria-label="Jump to latest message"
          >
            <ArrowDown size={15} /> Latest
          </button>
        )}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="relative z-10 bg-gradient-to-t from-[#0a0a0c] via-[#0a0a0c]/85 to-transparent px-4 pt-5"
        style={{ paddingBottom: `calc(${inset > 80 ? 12 : 36}px + ${inset > 0 ? inset : 0}px)` }}
      >
        <div className="flex items-end gap-2 rounded-[28px] border border-white/12 bg-[#16171c]/95 p-1.5 shadow-[0_14px_40px_rgba(0,0,0,0.55)] backdrop-blur-sm">
          <textarea
            aria-label="Message Finora AI"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !('ontouchstart' in window)) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={1}
            placeholder="Ask about any company…"
            className="max-h-[120px] min-h-[46px] flex-1 resize-none bg-transparent px-3.5 py-3 text-white outline-none placeholder:text-[#6b675c]"
          />
          <button
            type="submit" disabled={!input.trim() || busy} aria-label="Send message"
            className="btn-primary pressable flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-white disabled:opacity-50"
          >
            <SendHorizonal size={19} />
          </button>
        </div>
      </form>
    </div>
  );
}

import { useEffect, useRef, useState } from 'react';
import { SendHorizonal, Loader2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { followUps, sendChat } from '../lib/api';
import type { ChatMsg } from '../lib/api';
import { BottomSheet } from './BottomSheet';
import { TickerChip } from './ui';

export function AskFinoraSheet({ open, onClose, ticker, sessionId }: { open: boolean; onClose: () => void; ticker: string; sessionId?: string }) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // scroll only the sheet's own message list — never the page behind it
    const el = listRef.current;
    if (open && el) el.scrollTop = el.scrollHeight;
  }, [msgs, open, busy]);

  const send = async (text: string) => {
    const t = text.trim();
    if (!t || busy) return;
    setError(null);
    const next: ChatMsg[] = [...msgs.slice(-9), { role: 'user', text: t }];
    setMsgs(next);
    setInput('');
    setBusy(true);
    try {
      const r = await sendChat(next, ticker, sessionId);
      setMsgs([...next, { role: 'assistant', text: r.text, ms: r.ms }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reach Finora AI.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <BottomSheet open={open} onClose={onClose} title={`Ask Finora`} snap={75}>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[13px] text-[#a7a29a]">Asking about</span>
        <TickerChip ticker={ticker} />
      </div>

      <div ref={listRef} className="max-h-[46dvh] space-y-3 overflow-y-auto pb-2">
        {msgs.length === 0 && (
          <div>
            <p className="text-sm leading-6 text-[#a7a29a]">Ask anything about {ticker} — answers cite the filings behind them.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {followUps().map((f) => (
                <button
                  key={f}
                  onClick={() => send(f)}
                  className="pressable min-h-[44px] rounded-full border border-[#ff5a1f]/35 bg-[#ff5a1f]/[0.08] px-4 text-[13px] font-medium text-[#ffb25c]"
                >
                  {f}
                </button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <div className={
              m.role === 'user'
                ? 'max-w-[85%] rounded-2xl rounded-br-md bg-[#ff5a1f] px-3.5 py-2.5 text-[14px] leading-6 text-white'
                : 'memo-md max-w-[88%] rounded-2xl rounded-bl-md border border-white/10 bg-white/[0.04] px-3.5 py-2.5'
            }>
              {m.role === 'user' ? m.text : (
                <>
                  <ReactMarkdown>{m.text}</ReactMarkdown>
                  {m.ms != null && <p className="mt-1 font-mono text-[10px] text-[#6b675c]">Finora AI · {m.ms}ms</p>}
                </>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-1.5 px-1 text-[#ff8a3d]" aria-label="Finora is typing">
            <Loader2 size={15} className="animate-spin" />
            <span className="text-[13px]">Reading filings…</span>
          </div>
        )}
        {error && (
          <div role="alert" className="rounded-xl border border-[#f87171]/40 bg-[#f87171]/10 p-3 text-[13px] text-[#f87171]">
            {error}
            <button onClick={() => { const last = [...msgs].reverse().find((m) => m.role === 'user'); if (last) send(last.text); }} className="ml-2 font-semibold underline">Retry</button>
          </div>
        )}
      </div>

      <form
        className="sticky bottom-0 -mx-5 mt-3 border-t border-white/10 bg-[#14151a] px-5 pb-2 pt-3"
        onSubmit={(e) => { e.preventDefault(); send(input); }}
      >
        <div className="flex items-end gap-2">
          <textarea
            aria-label="Ask about this company"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={1}
            placeholder={`Ask about ${ticker}…`}
            className="max-h-[120px] min-h-[48px] flex-1 resize-none rounded-2xl border border-white/12 bg-black/40 px-4 py-3 text-white outline-none placeholder:text-[#6b675c] focus:border-[#ff5a1f]/60"
          />
          <button
            type="submit" disabled={!input.trim() || busy} aria-label="Send question"
            className="btn-primary pressable flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-white disabled:opacity-50"
          >
            <SendHorizonal size={19} />
          </button>
        </div>
      </form>
    </BottomSheet>
  );
}

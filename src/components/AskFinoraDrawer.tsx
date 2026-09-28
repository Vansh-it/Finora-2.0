import { useState, useRef } from "react";
import { X, ArrowUp, Sparkles, Loader2 } from "lucide-react";
import ChatMessage, { type ChatMessageData } from "./ChatMessage";
import { sendDashboardChatMessage, type ChatHistoryMessage } from "../lib/api";

const SUGGESTED = [
  "How did you calculate ROIC?",
  "Why did margins change?",
  "Explain this company simply.",
  "What are the biggest risks?",
  "Which numbers were cross-verified?",
  "What does this valuation mean?",
];

interface AskFinoraDrawerProps {
  sessionId?: string | null;
}

export default function AskFinoraDrawer({ sessionId }: AskFinoraDrawerProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chatHistoryRef = useRef<ChatHistoryMessage[]>([]);

  async function ask(question: string) {
    if (!question.trim() || loading) return;

    const userMsg: ChatMessageData = { role: "user", content: question };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setLoading(true);
    setError(null);

    chatHistoryRef.current.push({ role: "user", content: question });

    try {
      let res;
      if (sessionId) {
        res = await sendDashboardChatMessage(question, sessionId, chatHistoryRef.current.slice(-10));
      } else {
        // Fallback to regular chat if no session
        const { sendChatMessage } = await import("../lib/api");
        res = await sendChatMessage(question, chatHistoryRef.current.slice(-10));
      }

      const assistantMsg: ChatMessageData = {
        role: "assistant",
        content: res.response,
        bold: [],
        source: `Finora AI · ${res.elapsed_ms}ms`,
        followUps: ["Tell me more", "Show me the source"],
      };

      setMessages((m) => [...m, assistantMsg]);
      chatHistoryRef.current.push({ role: "assistant", content: res.response });
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Failed to get response";
      setError(errMsg);
      chatHistoryRef.current.pop();
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed right-5 bottom-5 z-40 flex items-center gap-2 bg-ink px-5 py-3.5 font-mono text-xs font-bold tracking-widest text-paper uppercase shadow-[4px_4px_0_0_#E9FF32] transition-transform hover:-translate-y-0.5 sm:right-8 sm:bottom-8"
      >
        <Sparkles size={14} />
        Ask Finora
      </button>

      {open && (
        <div className="fixed inset-0 z-[70] flex justify-end">
          <button aria-label="Close chat" className="absolute inset-0 bg-ink/30" onClick={() => setOpen(false)} />
          <div className="relative flex h-full w-full max-w-lg flex-col border-l-2 border-ink bg-paper">
            <div className="flex items-center justify-between border-b border-ink/15 p-5">
              <div>
                <p className="font-mono text-xs font-semibold tracking-[0.2em] text-ink-3 uppercase">Finora Research Assistant</p>
                <h2 className="font-serif text-xl font-semibold text-ink">Ask About This Research</h2>
              </div>
              <button onClick={() => setOpen(false)} aria-label="Close" className="text-ink-2 hover:text-ink">
                <X size={20} />
              </button>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              {messages.length === 0 && !loading && (
                <div>
                  <p className="mb-3 font-mono text-[10px] font-semibold tracking-widest text-ink-3 uppercase">
                    Suggested Questions
                  </p>
                  <div className="flex flex-col gap-2">
                    {SUGGESTED.map((q) => (
                      <button
                        key={q}
                        onClick={() => ask(q)}
                        disabled={loading}
                        className="border border-ink/25 px-4 py-3 text-left text-sm text-ink-2 transition-colors hover:border-ink hover:text-ink disabled:opacity-50"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((m, i) => (
                <ChatMessage key={i} message={m} onFollowUp={ask} />
              ))}
              {loading && (
                <div className="flex items-center gap-2 text-ink-3">
                  <Loader2 size={16} className="animate-spin" />
                  <span className="font-mono text-xs">Finora is reading this research…</span>
                </div>
              )}
            </div>

            {error && (
              <div className="border-t border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <form
              onSubmit={(e) => {
                e.preventDefault();
                ask(input);
              }}
              className="flex items-center gap-2 border-t border-ink/15 p-4"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about this research..."
                disabled={loading}
                className="flex-1 border border-ink/25 bg-paper px-4 py-3 text-sm text-ink placeholder:text-ink-3 focus:outline-none disabled:opacity-50"
              />
              <button
                type="submit"
                aria-label="Send"
                disabled={loading || !input.trim()}
                className="flex h-11 w-11 items-center justify-center bg-ink text-paper transition-colors hover:bg-ink-2 disabled:opacity-50"
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={16} />}
              </button>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

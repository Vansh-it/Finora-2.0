import { useState, useRef, useEffect } from "react";
import { ArrowUp, Loader2 } from "lucide-react";
import ChatMessage, { type ChatMessageData } from "../components/ChatMessage";
import EditorialHeading from "../components/EditorialHeading";
import HighlightText from "../components/HighlightText";
import { sendChatMessage, type ChatHistoryMessage } from "../lib/api";

const SUGGESTIONS = [
  "How did you calculate ROIC for Apple?",
  "Compare Apple and Microsoft margins.",
  "What's the biggest risk in NVIDIA's filings?",
  "Explain EV/EBITDA like I'm new to investing.",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatHistoryRef = useRef<ChatHistoryMessage[]>([]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function ask(q: string) {
    if (!q.trim() || loading) return;

    const userMsg: ChatMessageData = { role: "user", content: q };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setLoading(true);
    setError(null);

    // Add to history for context
    chatHistoryRef.current.push({ role: "user", content: q });

    try {
      const res = await sendChatMessage(q, chatHistoryRef.current.slice(-10));

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
      // Remove the user message from history since it failed
      chatHistoryRef.current.pop();
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[85vh] max-w-3xl flex-col px-4 py-12 sm:px-6 lg:px-0">
      <div className="mb-10">
        <EditorialHeading size="md">
          Talk to your
          <br />
          <HighlightText>research analyst.</HighlightText>
        </EditorialHeading>
        <p className="mt-4 max-w-xl text-sm text-ink-2">
          Ask about any figure, filing, or trend. Every answer cites the source it came from.
        </p>
      </div>

      {messages.length === 0 && !loading && (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-center text-ink-3 text-sm">
            Start a conversation about any public company or financial topic.
          </p>
        </div>
      )}

      <div className="flex-1 space-y-6">
        {messages.map((m, i) => (
          <ChatMessage key={i} message={m} onFollowUp={ask} />
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-ink-3">
            <Loader2 size={16} className="animate-spin" />
            <span className="font-mono text-xs">Thinking...</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {error && (
        <div className="mb-4 border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="mt-8 mb-4 flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => ask(s)}
            disabled={loading}
            className="border border-ink/25 px-3 py-2 text-left font-mono text-[11px] text-ink-2 transition-colors hover:border-ink hover:text-ink disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
        className="sticky bottom-4 flex items-center gap-2 border-2 border-ink bg-paper p-2 shadow-[4px_4px_0_0_#111111]"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask Finora about any company or figure..."
          disabled={loading}
          className="flex-1 bg-transparent px-3 py-3 text-sm text-ink placeholder:text-ink-3 focus:outline-none disabled:opacity-50"
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
  );
}

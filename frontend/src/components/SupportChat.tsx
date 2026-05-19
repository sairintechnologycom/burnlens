"use client";

import { useCallback, useRef, useState } from "react";
import SupportChatMessages from "./SupportChatMessages";
import type { ChatMessage } from "@/lib/support/types";

const GREETING: ChatMessage = {
  role: "assistant",
  content: "Hi! Ask me anything about BurnLens — installation, billing, providers, troubleshooting. I'll cite the docs.",
};

export default function SupportChat() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([GREETING]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<number, "up" | "down" | undefined>>({});
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || streaming) return;
    setError(null);
    const userMsg: ChatMessage = { role: "user", content: trimmed };
    const placeholder: ChatMessage = { role: "assistant", content: "" };
    setMessages((m) => [...m, userMsg, placeholder]);
    setInput("");
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/support-chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: trimmed }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const text = await res.text();
        setError(
          res.status === 429
            ? "You're sending messages too quickly. Please wait a moment."
            : `Request failed (${res.status}). ${text}`
        );
        setMessages((m) => m.slice(0, -1));
        return;
      }

      const citeHeader = res.headers.get("x-support-citations");
      let citations: ChatMessage["citations"] = [];
      if (citeHeader) {
        try {
          citations = JSON.parse(atob(citeHeader));
        } catch {
          citations = [];
        }
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let acc = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });
        setMessages((m) => {
          const copy = m.slice();
          copy[copy.length - 1] = { role: "assistant", content: acc, citations };
          return copy;
        });
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setError((err as Error).message);
      setMessages((m) => m.slice(0, -1));
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming]);

  const onFeedback = useCallback(
    (idx: number, rating: "up" | "down") => {
      setFeedback((f) => ({ ...f, [idx]: rating }));
      const assistantMsg = messages[idx];
      const userMsg = messages[idx - 1];
      if (!assistantMsg || !userMsg) return;
      void fetch("/api/support-feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          rating,
          question: userMsg.content,
          answer: assistantMsg.content,
        }),
      });
    },
    [messages]
  );

  return (
    <>
      <button
        type="button"
        aria-label={open ? "Close support chat" : "Open support chat"}
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-5 right-5 z-50 rounded-full bg-[color:var(--cyan)] px-4 py-3 text-sm font-medium text-[#0a0b0f] shadow-lg hover:opacity-90"
      >
        {open ? "Close" : "Ask BurnLens"}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="BurnLens support chat"
          className="fixed bottom-20 right-5 z-50 flex h-[32rem] w-[22rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-[color:var(--border)] bg-[color:var(--card-bg)] shadow-2xl"
        >
          <header className="flex items-center justify-between border-b border-[color:var(--border)] px-4 py-2 text-sm text-[color:var(--text)]">
            <span className="font-medium">BurnLens Support</span>
            <a href="mailto:support@burnlens.app" className="text-xs text-[color:var(--muted)] underline hover:text-[color:var(--text)]">
              Email instead
            </a>
          </header>

          <div className="flex-1 overflow-y-auto">
            <SupportChatMessages
              messages={messages}
              isStreaming={streaming}
              onFeedback={onFeedback}
              feedback={feedback}
            />
          </div>

          {error && (
            <div className="border-t border-[color:var(--red)] bg-[color:var(--sev-c-bg)] px-4 py-2 text-xs text-[color:var(--red)]">
              {error}
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
            className="flex gap-2 border-t border-[color:var(--border)] p-2"
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question…"
              maxLength={2000}
              disabled={streaming}
              className="flex-1 rounded-md bg-[color:var(--stat-bg)] px-3 py-2 text-sm text-[color:var(--text)] outline-none placeholder:text-[color:var(--muted)] focus:ring-2 focus:ring-[color:var(--cyan)]"
            />
            <button
              type="submit"
              disabled={streaming || !input.trim()}
              className="rounded-md bg-[color:var(--cyan)] px-3 py-2 text-sm font-medium text-[#0a0b0f] disabled:opacity-50"
            >
              {streaming ? "…" : "Send"}
            </button>
          </form>
        </div>
      )}
    </>
  );
}

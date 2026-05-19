"use client";

import type { ChatMessage } from "@/lib/support/types";

interface Props {
  messages: ChatMessage[];
  isStreaming: boolean;
  onFeedback: (index: number, rating: "up" | "down") => void;
  feedback: Record<number, "up" | "down" | undefined>;
}

export default function SupportChatMessages({ messages, isStreaming, onFeedback, feedback }: Props) {
  return (
    <div className="flex flex-col gap-4 overflow-y-auto px-4 py-3">
      {messages.map((m, i) => (
        <div key={i} className={`flex flex-col gap-2 ${m.role === "user" ? "items-end" : "items-start"}`}>
          <div
            className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
              m.role === "user"
                ? "bg-[color:var(--cyan)] text-[#0a0b0f]"
                : "bg-[color:var(--stat-bg)] text-[color:var(--text)]"
            }`}
          >
            {m.content || (isStreaming && i === messages.length - 1 ? "…" : "")}
          </div>

          {m.role === "assistant" && m.citations && m.citations.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {m.citations.map((c, ci) => (
                <a
                  key={ci}
                  href={c.url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-[color:var(--border)] px-2 py-0.5 text-xs text-[color:var(--muted)] hover:text-[color:var(--text)] hover:border-[color:var(--cyan)]"
                >
                  [{ci + 1}] {c.heading}
                </a>
              ))}
            </div>
          )}

          {m.role === "assistant" && !isStreaming && m.content && i !== 0 && (
            <div className="flex items-center gap-2 text-xs text-[color:var(--muted)]">
              <span>Was this helpful?</span>
              <button
                type="button"
                onClick={() => onFeedback(i, "up")}
                aria-label="Helpful"
                className={`rounded-full px-2 py-0.5 ${
                  feedback[i] === "up"
                    ? "bg-[color:var(--tag-f-bg)] text-[color:var(--tag-f)]"
                    : "hover:bg-[color:var(--stat-bg)]"
                }`}
              >
                👍
              </button>
              <button
                type="button"
                onClick={() => onFeedback(i, "down")}
                aria-label="Not helpful"
                className={`rounded-full px-2 py-0.5 ${
                  feedback[i] === "down"
                    ? "bg-[color:var(--sev-c-bg)] text-[color:var(--red)]"
                    : "hover:bg-[color:var(--stat-bg)]"
                }`}
              >
                👎
              </button>
              {feedback[i] === "down" && (
                <a
                  className="ml-2 underline hover:text-[color:var(--text)]"
                  href={`mailto:support@burnlens.app?subject=BurnLens%20chat%20follow-up&body=Question%3A%20${encodeURIComponent(messages[i - 1]?.content ?? "")}%0A%0AChat%20answer%3A%20${encodeURIComponent(m.content)}`}
                >
                  Email support
                </a>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

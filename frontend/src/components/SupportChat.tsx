"use client";

import { useCallback, useState } from "react";
import SupportChatResults, { type SearchResultView } from "./SupportChatMessages";
import { searchChunks } from "@/lib/support/retrieval";
import indexData from "@/lib/support/index.json";
import type { SupportIndex } from "@/lib/support/types";

const INDEX = indexData as SupportIndex;
const TOP_K = 3;

export default function SupportChat() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultView[]>([]);
  const [searched, setSearched] = useState(false);

  const search = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed) return;
    setQuery(trimmed);
    const hits = searchChunks(trimmed, INDEX.chunks, TOP_K).map((r) => ({
      source: r.chunk.source,
      heading: r.chunk.heading,
      url: r.chunk.url,
      text: r.chunk.text,
    }));
    setResults(hits);
    setSearched(true);
  }, [input]);

  return (
    <>
      <button
        type="button"
        aria-label={open ? "Close support" : "Open support"}
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-5 right-5 z-50 rounded-full bg-[color:var(--cyan)] px-4 py-3 text-sm font-medium text-[#0a0b0f] shadow-lg hover:opacity-90"
      >
        {open ? "Close" : "Ask BurnLens"}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="BurnLens support search"
          className="fixed bottom-20 right-5 z-50 flex h-[32rem] w-[24rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-[color:var(--border)] bg-[color:var(--card-bg)] shadow-2xl"
        >
          <header className="flex items-center justify-between border-b border-[color:var(--border)] px-4 py-2 text-sm text-[color:var(--text)]">
            <span className="font-medium">BurnLens Support</span>
            <a
              href="mailto:support@burnlens.app"
              className="text-xs text-[color:var(--muted)] underline hover:text-[color:var(--text)]"
            >
              Email instead
            </a>
          </header>

          <div className="flex-1 overflow-y-auto">
            <SupportChatResults query={query} results={results} searched={searched} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              search();
            }}
            className="flex gap-2 border-t border-[color:var(--border)] p-2"
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Search the docs…"
              maxLength={2000}
              className="flex-1 rounded-md bg-[color:var(--stat-bg)] px-3 py-2 text-sm text-[color:var(--text)] outline-none placeholder:text-[color:var(--muted)] focus:ring-2 focus:ring-[color:var(--cyan)]"
            />
            <button
              type="submit"
              disabled={!input.trim()}
              className="rounded-md bg-[color:var(--cyan)] px-3 py-2 text-sm font-medium text-[#0a0b0f] disabled:opacity-50"
            >
              Search
            </button>
          </form>
        </div>
      )}
    </>
  );
}

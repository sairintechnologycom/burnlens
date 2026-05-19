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
        aria-label={open ? "Close BurnLens support" : "Ask BurnLens"}
        onClick={() => setOpen((v) => !v)}
        className="support-chat-trigger"
      >
        {open ? "Close" : "Ask BurnLens"}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="BurnLens support search"
          className="support-chat-panel"
        >
          <header className="support-chat-header">
            <span className="support-chat-header-title">BurnLens Support</span>
            <a
              href="mailto:support@burnlens.app"
              className="support-chat-header-link"
            >
              Email instead
            </a>
          </header>

          <div className="support-chat-body">
            <SupportChatResults query={query} results={results} searched={searched} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              search();
            }}
            className="support-chat-form"
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Search the docs…"
              maxLength={2000}
              className="support-chat-input"
            />
            <button
              type="submit"
              disabled={!input.trim()}
              className="support-chat-submit"
            >
              Search
            </button>
          </form>
        </div>
      )}
    </>
  );
}

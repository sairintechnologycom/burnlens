"use client";

export interface SearchResultView {
  source: string;
  heading: string;
  url: string;
  text: string;
}

interface Props {
  query: string;
  results: SearchResultView[];
  searched: boolean;
}

export default function SupportChatResults({ query, results, searched }: Props) {
  if (!searched) {
    return (
      <div className="flex flex-col gap-3 px-4 py-4 text-sm text-[color:var(--muted)]">
        <p className="text-[color:var(--text)]">Ask anything about BurnLens.</p>
        <p>I&rsquo;ll search the README, architecture docs, providers guide, and FAQ.</p>
        <ul className="ml-4 list-disc space-y-1">
          <li>How do I install BurnLens?</li>
          <li>What providers are supported?</li>
          <li>Why does my dashboard show $0?</li>
          <li>How do I rotate my API key?</li>
        </ul>
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="flex flex-col gap-3 px-4 py-4 text-sm">
        <p className="text-[color:var(--text)]">
          No matches found for{" "}
          <span className="text-[color:var(--cyan)]">&ldquo;{query}&rdquo;</span>.
        </p>
        <p className="text-[color:var(--muted)]">
          Try different keywords, or{" "}
          <a
            className="underline hover:text-[color:var(--text)]"
            href={`mailto:support@burnlens.app?subject=BurnLens%20support&body=Question%3A%20${encodeURIComponent(query)}`}
          >
            email support@burnlens.app
          </a>
          .
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 overflow-y-auto px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-[color:var(--muted)]">
        Top {results.length} {results.length === 1 ? "match" : "matches"} for &ldquo;{query}&rdquo;
      </p>

      {results.map((r, i) => (
        <a
          key={i}
          href={r.url}
          target="_blank"
          rel="noreferrer"
          className="block rounded-lg border border-[color:var(--border)] bg-[color:var(--stat-bg)] p-3 text-sm hover:border-[color:var(--cyan)]"
        >
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="font-medium text-[color:var(--text)]">{r.heading}</span>
            <span className="shrink-0 text-xs text-[color:var(--muted)]">{r.source}</span>
          </div>
          <p className="line-clamp-6 whitespace-pre-wrap text-[color:var(--muted)]">{r.text}</p>
        </a>
      ))}

      <div className="pt-1 text-xs text-[color:var(--muted)]">
        Not what you needed?{" "}
        <a
          className="underline hover:text-[color:var(--text)]"
          href={`mailto:support@burnlens.app?subject=BurnLens%20support&body=Question%3A%20${encodeURIComponent(query)}`}
        >
          Email support
        </a>
        .
      </div>
    </div>
  );
}

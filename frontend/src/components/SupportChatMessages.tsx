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
      <div className="support-chat-intro">
        <p className="lead">Ask anything about BurnLens.</p>
        <p>I&rsquo;ll search the README, architecture docs, providers guide, and FAQ.</p>
        <ul>
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
      <div className="support-chat-empty">
        <p>
          No matches found for &ldquo;{query}&rdquo;.
        </p>
        <p className="muted">
          Try different keywords, or{" "}
          <a
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
    <>
      <div className="support-chat-resultlabel">
        Top {results.length} {results.length === 1 ? "match" : "matches"} for &ldquo;{query}&rdquo;
      </div>

      {results.map((r, i) => (
        <a
          key={i}
          href={r.url}
          target="_blank"
          rel="noreferrer"
          className="support-chat-result"
        >
          <div className="support-chat-result-head">
            <span className="support-chat-result-title">{r.heading}</span>
            <span className="support-chat-result-source">{r.source}</span>
          </div>
          <p className="support-chat-result-text">{r.text}</p>
        </a>
      ))}

      <div className="support-chat-footer-hint">
        Not what you needed?{" "}
        <a
          href={`mailto:support@burnlens.app?subject=BurnLens%20support&body=Question%3A%20${encodeURIComponent(query)}`}
        >
          Email support
        </a>
        .
      </div>
    </>
  );
}

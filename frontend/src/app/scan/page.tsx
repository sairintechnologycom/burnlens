import Link from "next/link";
import type { Metadata } from "next";
import { CopyCommand } from "@/components/CopyCommand";

export const metadata: Metadata = {
  title: "Scan your AI coding agent spend — Claude Code, Cursor, Codex, Gemini CLI · BurnLens",
  description:
    "See exactly what Claude Code, Cursor, Codex, and Gemini CLI cost you this week. BurnLens reads local agent logs and shows spend per session, repo, and developer — no proxy, no signup.",
  alternates: { canonical: "/scan" },
  openGraph: {
    title: "See what your AI coding agents actually cost",
    description:
      "BurnLens scans Claude Code, Cursor, Codex, and Gemini CLI local logs and shows spend per session, repo, and developer. One command, no proxy.",
    url: "https://burnlens.app/scan",
    siteName: "BurnLens",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: "See what your AI coding agents actually cost",
    description:
      "BurnLens scans Claude Code, Cursor, Codex, and Gemini CLI local logs and shows spend per session, repo, and developer.",
  },
};

const faqStructuredData = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Which coding agents does BurnLens scan?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "BurnLens reads local session logs for Claude Code (~/.claude/projects/), Cursor (local bubble DB), OpenAI Codex (SQLite session store), and Gemini CLI (~/.gemini/tmp/). Each reader parses the agent's native format, deduplicates turns, and routes cost through the BurnLens pricing engine.",
      },
    },
    {
      "@type": "Question",
      name: "Does scanning send my prompts or code anywhere?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. burnlens scan reads files on your machine and writes cost rows to a local SQLite database at ~/.burnlens/burnlens.db. Nothing leaves your machine unless you opt in to cloud sync, which uploads selected pseudonymous cost metadata — never prompt or response content.",
      },
    },
    {
      "@type": "Question",
      name: "Do I need to run the BurnLens proxy to scan agent logs?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. burnlens scan is independent from the proxy. You can install BurnLens, run a single scan command, and see retroactive cost history for every agent session that already exists on your machine — no proxy, no env vars, no code changes.",
      },
    },
    {
      "@type": "Question",
      name: "What if a model isn't in the BurnLens pricing data?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "The session is still imported with a $0 cost and the model name is logged so you can spot gaps. Pricing data lives in burnlens/cost/pricing_data/*.json — adding a missing model is a one-line PR.",
      },
    },
  ],
};

const AGENTS = [
  {
    name: "Claude Code",
    path: "~/.claude/projects/",
    detail: "Parses JSONL session files. Deduplicates repeated message.id entries. Attributes cost per session and per project directory.",
  },
  {
    name: "Cursor",
    path: "Cursor's local bubble database",
    detail: "Reads Cursor's local SQLite store. Routes each turn through the cost engine by provider + model.",
  },
  {
    name: "OpenAI Codex",
    path: "Codex CLI SQLite session DB",
    detail: "Handles the event_msg wrapper and turn_context model fields. Tested against 700+ sessions / 88K events.",
  },
  {
    name: "Gemini CLI",
    path: "~/.gemini/tmp/<project>/chats/",
    detail: "Supports both JSON and JSONL chat formats. Imports session count, turns, and model usage.",
  },
];

export default function ScanLandingPage() {
  return (
    <div className="legal-page">
      <script type="application/ld+json">{JSON.stringify(faqStructuredData)}</script>

      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <p
          style={{
            fontFamily: "var(--font-mono), monospace",
            fontSize: 11,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--cyan, #e07840)",
            marginBottom: 8,
          }}
        >
          burnlens scan · no API key · no signup
        </p>
        <h1>See what your AI coding agents actually cost</h1>
        <p className="legal-updated">
          Claude Code, Cursor, Codex, Gemini CLI — local logs, one command, no proxy required
        </p>

        <section>
          <h2>The problem</h2>
          <p>
            You opened Cursor on Monday. You ran Claude Code on Tuesday. You let Codex churn through a refactor on
            Wednesday. By Friday you have <em>no idea</em> how much you spent, which project ate the budget, or which
            session was the runaway. The provider bill says <code>claude-sonnet: $214</code> — it doesn&apos;t say which
            of your repos burned it.
          </p>
        </section>

        <section>
          <h2>What burnlens scan does</h2>
          <p>
            Reads the local session logs your coding agents already write to disk, deduplicates the turns, routes each
            call through the BurnLens pricing engine, and stores the results in a local SQLite database. No proxy, no
            code changes, no signup. Run it once and see retroactive cost history for every session on your machine.
          </p>

          <pre
            style={{
              background: "#0e1318",
              border: "1px solid #1e2830",
              padding: "1rem 1.25rem",
              borderRadius: 8,
              overflowX: "auto",
              fontSize: 13,
              lineHeight: 1.7,
            }}
          >
            <code>{`$ burnlens scan
Scanning Claude Code sessions...
Found 141 session files across 5 projects.
Parsed 37,377 assistant messages.
Total Claude cost imported: $5,578.30

          Top projects by cost
\u250f\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2533\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2533\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2513
\u2503 Project       \u2503      Cost \u2503 Messages \u2503
\u2521\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2547\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2547\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2529
\u2502 payments-api  \u2502 $2,636.62 \u2502   16,405 \u2502
\u2502 burnlens      \u2502 $1,063.03 \u2502    7,916 \u2502
\u2502 web-console   \u2502   $962.94 \u2502    6,658 \u2502
\u2502 infra-tooling \u2502   $736.59 \u2502    4,947 \u2502
\u2502 docs-site     \u2502   $179.12 \u2502    1,451 \u2502
\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2534\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2534\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518

No Cursor DB found at ~/Library/Application Support/Cursor/... Skipping Cursor scan.
No Codex sessions found at ~/.codex/sessions. Skipping Codex scan.
No Gemini CLI sessions found at any known location. Skipping.`}</code>
          </pre>
          <p className="legal-updated" style={{ marginTop: 8 }}>
            Real output from one developer&apos;s laptop, on a clean install with no config file. Repo names replaced; every number is what the scan actually printed.
          </p>
        </section>

        <section>
          <h2>What it scans</h2>
          <table className="lp-compare-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Source</th>
                <th>What you get</th>
              </tr>
            </thead>
            <tbody>
              {AGENTS.map((a) => (
                <tr key={a.name}>
                  <td><strong>{a.name}</strong></td>
                  <td><code>{a.path}</code></td>
                  <td>{a.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section>
          <h2>Try it in three commands</h2>
          <CopyCommand
            eventName="Scan Install Copy"
            command={`pip install burnlens
burnlens scan
burnlens repos    # which repo actually burned the money`}
          />

          <p>
            No env vars to set, no proxy to start, no account to create. The scan reads files and
            writes to a local database; it never asks for an API key, because it never calls an API.
          </p>
          <p>
            <strong>Then ask it the questions the provider bill cannot answer:</strong>
          </p>
          <ul>
            <li><code>burnlens repos</code> — top repos by cost, with request counts and last-seen.</li>
            <li><code>burnlens report --days 30</code> — spend by model over a window, plus waste alerts.</li>
            <li><code>burnlens analyze</code> — the waste detectors, with a dollar figure per finding.</li>
            <li><code>burnlens economics</code> — waste rate, error spend, and cost per outcome.</li>
          </ul>
          <p className="legal-updated">
            <code>burnlens top</code> is a live viewer for proxy traffic happening right now — it
            refreshes until you stop it and shows today only, so it is not the command to run after a
            retroactive scan.
          </p>
          <p>
            <strong>How long the first scan takes</strong> depends on how much history you have. A
            light history finishes in seconds. The 141-session, 37,377-message machine above took a
            few minutes on its first run. Re-runs are idempotent and only pick up what is new.
          </p>
        </section>

        <section>
          <h2>Privacy</h2>
          <p>
            <strong>Everything stays on your machine.</strong> burnlens scan reads local files and writes to a local
            SQLite database at <code>~/.burnlens/burnlens.db</code>. No prompts, no code, no session content ever
            leaves your machine. If you enable cloud sync later for team dashboards, only selected pseudonymous cost metadata and
            costs are uploaded — never prompt or response bodies.
          </p>
        </section>

        <section>
          <h2>FAQ</h2>
          <p><strong>What if a model isn&apos;t priced yet?</strong> The session is still imported with cost = $0 and
          the model name is recorded so you can spot the gap. Adding a missing model is a one-line edit in{" "}
          <code>burnlens/cost/pricing_data/*.json</code>.</p>

          <p><strong>Does scanning interfere with the agent?</strong> No. burnlens scan only reads. It never writes to
          the agent&apos;s own log directories or databases.</p>

          <p><strong>Can I scan from CI?</strong> Yes — burnlens scan is idempotent. Re-running it picks up new
          sessions since the last scan. A scheduled job + cloud sync gives you a team-wide view of coding-agent spend
          across every developer.</p>

          <p><strong>What about Cline, Windsurf, Aider?</strong> Not yet — they&apos;re tracked in{" "}
          <a href="https://github.com/sairintechnologycom/burnlens/issues" target="_blank" rel="noopener noreferrer">
            GitHub issues
          </a>. Each new reader is one file in <code>burnlens/scan/</code> plus a pricing entry; PRs welcome.</p>
        </section>

        <section>
          <h2>Get started</h2>
          <p>
            <Link
              href="/setup?intent=register"
              className="legal-nav-link plausible-event-name=Scan+Get+Started"
            >
              Start the free trial
            </Link>
            {" · "}
            <a
              href="https://github.com/sairintechnologycom/burnlens"
              target="_blank"
              rel="noopener noreferrer"
              className="legal-nav-link plausible-event-name=Scan+GitHub+Click"
            >
              Star on GitHub
            </a>
            {" · "}
            <Link href="/" className="legal-nav-link">Back to homepage</Link>
          </p>
        </section>
      </main>
    </div>
  );
}

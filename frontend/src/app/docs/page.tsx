import Link from "next/link";
import type { Metadata } from "next";
import { Code, GH } from "@/lib/docs";

const TITLE = "BurnLens Docs — install and get your first cost number";
const DESCRIPTION =
  "Install BurnLens, then pick one of two entry points: scan the cost history your coding agents already wrote to disk, or run the local proxy in front of production API traffic. No account required for either.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/docs" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: "https://burnlens.app/docs",
    siteName: "BurnLens",
    type: "article",
  },
};

export default function DocsIndexPage() {
  return (
    <>
      <h1>BurnLens Documentation</h1>
      <p className="legal-updated">
        Checked against the source on 2026-08-16. If a command or config key here does not
        match what your install does, the install is older — run <code>pip show burnlens</code>{" "}
        before assuming the docs are wrong.
      </p>

      <section id="install">
        <h2>Install</h2>
        <p>
          BurnLens is a Python package. The published wheel needs Python 3.10 or newer, and
          everything it records lives in a local SQLite database at{" "}
          <code>~/.burnlens/burnlens.db</code>. Nothing on this page needs an account.
        </p>
        <Code>{`pip install burnlens`}</Code>
      </section>

      <section id="two-doors">
        <h2>Two entry points — you do not need both</h2>
        <p>
          BurnLens answers two different questions, and the way in is different for each.
          Most people start with scanning, because it produces a real number in about
          fifteen seconds without touching any application code.
        </p>

        <h3>1. Scan — what have my coding agents already spent?</h3>
        <p>
          Claude Code, Cursor, Codex and Gemini CLI all write session logs to disk.{" "}
          <code>burnlens scan</code> reads them, prices every call, stores the result, and
          then derives merged-PR outcomes when <code>gh</code> is installed. It is
          retroactive: it works on history that already exists, with no proxy and no
          code change.
        </p>
        <Code>{`burnlens scan
burnlens repos
burnlens outcome show`}</Code>
        <p>
          <Link href="/docs/scan">Full scanning documentation →</Link>
        </p>

        <h3>2. Proxy — stop the next expensive call before it is billed</h3>
        <p>
          For production API traffic, BurnLens runs a local proxy on{" "}
          <code>127.0.0.1:8420</code>. Point your SDK at it and calls route through
          unchanged, including streaming. Because the proxy sees the request before it is
          forwarded, it can refuse one that would breach a budget — the call is never
          billed, rather than being reported after the fact.
        </p>
        <Code>{`burnlens start
export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai`}</Code>
        <p>
          <Link href="/docs/proxy">Full proxy and tagging documentation →</Link>
        </p>
      </section>

      <section id="privacy">
        <h2>What leaves your machine</h2>
        <p>
          Nothing, until you ask for it. The proxy forwards your request to the provider
          you were already calling. Session-log import is local. After import,{" "}
          <code>burnlens scan</code> derives merged PRs through the GitHub CLI when{" "}
          <code>gh</code> is on PATH; if it is not, that is printed rather than skipped.
        </p>
        <p>
          If you enable cloud sync, cost <em>metadata</em> is uploaded — model, token
          counts, timestamps, tag values, repo. Prompt and response bodies are not, and
          there is no setting that turns that on.{" "}
          <Link href="/security">How data is handled</Link>.
        </p>
      </section>

      <section id="cloud">
        <h2>Cloud sync (optional)</h2>
        <p>
          Everything above works offline and free, forever. Cloud sync exists so a team can
          share one dashboard instead of each developer reading their own SQLite file.
        </p>
        <Code>{`burnlens login          # authenticate and enable cloud sync
burnlens sync --status  # what has been pushed, and what has not
burnlens sync --now     # push everything un-synced immediately`}</Code>
        <p>
          The free plan keeps 7 days of history, 10,000 records per month, one API key and
          one seat. Paid plans extend retention and seats — see{" "}
          <Link href="/#pricing">pricing</Link>.
        </p>
      </section>

      <section id="deeper">
        <h2>Reference beyond these pages</h2>
        <ul>
          <li>
            <a href={`${GH}/blob/main/docs/ARCHITECTURE.md`} target="_blank" rel="noreferrer">
              ARCHITECTURE.md
            </a>{" "}
            — how the proxy, pricing engine, WAL and dashboard fit together.
          </li>
          <li>
            <a href={`${GH}/blob/main/docs/BUDGET_ENFORCEMENT.md`} target="_blank" rel="noreferrer">
              BUDGET_ENFORCEMENT.md
            </a>{" "}
            — enforcement semantics under concurrency, streaming and retries, with the
            implementing function cited per claim.
          </li>
          <li>
            <a href={`${GH}/blob/main/docs/PROVIDERS.md`} target="_blank" rel="noreferrer">
              PROVIDERS.md
            </a>{" "}
            — per-provider routing, auth and pricing detail.
          </li>
          <li>
            <Link href="/troubleshooting">Troubleshooting</Link> — common errors and fixes.
          </li>
          <li>
            <Link href="/faq">FAQ</Link> — what BurnLens does and does not do.
          </li>
        </ul>
      </section>
    </>
  );
}

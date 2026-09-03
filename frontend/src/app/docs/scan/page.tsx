import Link from "next/link";
import type { Metadata } from "next";
import { Code } from "@/lib/docs";

const TITLE = "Scanning coding-agent logs — BurnLens Docs";
const DESCRIPTION =
  "burnlens scan reads Claude Code, Cursor, Codex and Gemini CLI session logs from disk, deduplicates the turns, prices every call, and stores the result locally. Sources, flags, and what the data can and cannot tell you.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/docs/scan" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: "https://burnlens.app/docs/scan",
    siteName: "BurnLens",
    type: "article",
  },
};

const AGENTS: { name: string; flag: string; source: string }[] = [
  { name: "Claude Code", flag: "claude", source: "~/.claude/projects/<project>/<session>.jsonl" },
  { name: "Cursor", flag: "cursor", source: "~/Library/Application Support/Cursor/.../state.vscdb" },
  { name: "Codex", flag: "codex", source: "~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl" },
  { name: "Gemini CLI", flag: "gemini", source: "~/.gemini/tmp/<project>/chats/session-*.{json,jsonl}" },
];

export default function DocsScanPage() {
  return (
    <>
      <h1>Scanning coding-agent logs</h1>
      <p className="legal-updated">
        Verified against <code>burnlens scan --help</code> on 2026-09-03. For the shorter
        pitch rather than the reference, see <Link href="/scan">the scan overview</Link>.
      </p>

      <section id="what">
        <h2>What it does</h2>
        <p>
          Coding agents already write a full session log to disk. <code>burnlens scan</code>{" "}
          walks those files, deduplicates the turns, routes each call through the pricing
          engine, and writes the result to <code>~/.burnlens/burnlens.db</code>.
        </p>
        <p>
          There is no proxy, no code change, and no signup. Importing session logs is
          local. After import, scan derives merged-PR outcomes for the current checkout
          through the GitHub CLI (<code>gh</code>) — the same path as{" "}
          <code>burnlens outcome derive</code>. If <code>gh</code> is missing, that is
          printed rather than skipped. <code>--dry-run</code> does not derive. It is
          retroactive — the first run prices history that already happened, which is why it
          produces a real number immediately rather than after a week of collection.
        </p>
        <Code>{`burnlens scan          # every agent it can find
burnlens repos         # top repos by cost
burnlens prs           # top PRs by cost
burnlens report -d 30  # spend by model, plus waste alerts`}</Code>
        <p>
          <code>burnlens top</code> is deliberately not in that list. It is a live viewer for
          traffic arriving through the proxy right now, scoped to today, and it refreshes until
          interrupted — so after a retroactive scan it shows an empty table and never exits.
        </p>
      </section>

      <section id="sources">
        <h2>What it reads</h2>
        <table className="lp-compare-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th><code>--provider</code></th>
              <th>Read from</th>
            </tr>
          </thead>
          <tbody>
            {AGENTS.map((a) => (
              <tr key={a.flag}>
                <td><strong>{a.name}</strong></td>
                <td><code>{a.flag}</code></td>
                <td><code>{a.source}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section id="flags">
        <h2>Flags</h2>
        <Code>{`burnlens scan --provider claude,codex   # 'all' (default), or a comma-separated subset
burnlens scan --since 2026-08-01        # only sessions modified at/after this date
burnlens scan --project burnlens        # substring filter on project basename (Claude Code only)
burnlens scan --dry-run                 # parse and print counts, insert nothing`}</Code>
        <p>
          Re-runs are idempotent. Already-imported records are skipped through a partial
          unique index on <code>(source, request_id)</code>, so scanning on a schedule
          cannot double-count a session.
        </p>
      </section>

      <section id="limits">
        <h2>What the data can and cannot tell you</h2>
        <p>
          Scanned rows carry no prompt or response text — model, token counts, timestamps
          and the repo the session ran in, and nothing else.
        </p>
        <p>
          <strong>Cost is attributed per repository, not per branch or PR.</strong> Agent
          session logs record which repo a session ran in; they do not record which branch
          it belonged to. With several PRs in flight, per-repo spend divided by accepted
          outcomes is the honest reading of what one merged PR costs, and it is what{" "}
          <code>burnlens outcome show</code> reports.
        </p>
        <p>
          <strong>A model with no pricing entry is imported as $ unknown, not
          $0.</strong> The session is still imported and the model name is logged so
          the gap is visible rather than silent — run <code>burnlens pricing</code>{" "}
          if a number looks too low. Any total derived from a scan is therefore a
          floor, not a ceiling. Storage still uses a sentinel 0 so sums do not
          invent a price; CSV export and Cost Confidence print{" "}
          <code>unknown</code> rather than <code>$0.00</code>.
        </p>
        <p>
          <strong>Scan costs use today&apos;s bundled pricing table, not the
          prices in effect when the session ran.</strong> A March session scanned in
          August is costed at August rates. Cost Confidence classifies every
          scanned row as <em>estimated</em> for that reason, among others.
        </p>
        <p>
          Scanned rows also carry no prompt segmentation, so the waste detectors that need
          it (oversized tool schemas, retrieval efficiency, history bloat) stay quiet on
          scan data. Those need proxy traffic — no scan and no upgrade can backfill a
          measurement that was never captured.
        </p>
      </section>

      <section id="next">
        <h2>Next</h2>
        <p>
          After a scan that could reach <code>gh</code>,{" "}
          <code>burnlens outcome show</code> is the cost-per-merged-PR number. Re-run
          derive from another checkout with <code>burnlens outcome derive</code> — see
          the <Link href="/docs/cli">CLI reference</Link>. To meter production API traffic
          rather than agent sessions, see <Link href="/docs/proxy">the proxy</Link>.
        </p>
      </section>
    </>
  );
}

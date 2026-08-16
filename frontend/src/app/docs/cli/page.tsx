import Link from "next/link";
import type { Metadata } from "next";
import { Code, COMMANDS } from "@/lib/docs";

const TITLE = "CLI reference — BurnLens Docs";
const DESCRIPTION =
  "Every burnlens command: scan, start, top, report, analyze, economics, outcome, budgets, key, vkey, routing, recommend, pricing, export, login, sync, doctor, wal. Plus where the config file and database live.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/docs/cli" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: "https://burnlens.app/docs/cli",
    siteName: "BurnLens",
    type: "article",
  },
};

const GROUPS = ["Collect", "Look at spend", "Find waste", "Control spend", "Operate"];

export default function DocsCliPage() {
  return (
    <>
      <h1>CLI reference</h1>
      <p className="legal-updated">
        The top-level surface as of 2026-08-16, taken from <code>burnlens --help</code>.
        Every command takes <code>--help</code> of its own, which is authoritative for your
        installed version.
      </p>

      <section id="paths">
        <h2>Where things live</h2>
        <table className="lp-compare-table">
          <thead>
            <tr>
              <th>What</th>
              <th>Path</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Database</td>
              <td><code>~/.burnlens/burnlens.db</code></td>
            </tr>
            <tr>
              <td>Config (YAML, not TOML)</td>
              <td>
                <code>$BURNLENS_CONFIG_PATH</code>, then <code>./burnlens.yaml</code>,{" "}
                <code>./burnlens.yml</code>, then <code>~/.burnlens/config.yaml</code>
              </td>
            </tr>
            <tr>
              <td>Write-ahead log</td>
              <td><code>~/.burnlens/wal.jsonl</code></td>
            </tr>
            <tr>
              <td>Dead letter queue</td>
              <td><code>~/.burnlens/wal_dlq.jsonl</code></td>
            </tr>
            <tr>
              <td>Proxy</td>
              <td><code>127.0.0.1:8420</code></td>
            </tr>
          </tbody>
        </table>
        <p>
          There is no <code>burnlens --version</code>. Use{" "}
          <code>pip show burnlens</code> to find out what you have installed.
        </p>
      </section>

      {GROUPS.map((group) => (
        <section key={group} id={group.toLowerCase().replace(/\s+/g, "-")}>
          <h2>{group}</h2>
          <table className="lp-compare-table">
            <thead>
              <tr>
                <th>Command</th>
                <th>What it does</th>
              </tr>
            </thead>
            <tbody>
              {COMMANDS.filter((c) => c.group === group).map((c) => (
                <tr key={c.cmd}>
                  <td><code>burnlens {c.cmd}</code></td>
                  <td>{c.what}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      <section id="recipes">
        <h2>Common sequences</h2>
        <p>First cost number, from history that already exists:</p>
        <Code>{`pip install burnlens
burnlens scan
burnlens repos`}</Code>
        <p>Cost per merged PR on a repository, using the <code>gh</code> CLI to resolve outcomes:</p>
        <Code>{`burnlens outcome derive     # merged PRs -> outcomes
burnlens outcome show       # cost per accepted outcome`}</Code>
        <p>
          Both are idempotent and safe on a schedule: outcome ids are derived
          deterministically from the repo and PR number, so re-running only adds
          newly-closed PRs.
        </p>
        <p>Meter and cap production traffic:</p>
        <Code>{`burnlens start
export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai
burnlens key register --label prod-openai --provider openai
burnlens keys`}</Code>
        <p>Find out why nothing is showing up:</p>
        <Code>{`burnlens doctor`}</Code>
      </section>

      <section id="next">
        <h2>Next</h2>
        <p>
          Flags and behaviour per area:{" "}
          <Link href="/docs/scan">scanning</Link>,{" "}
          <Link href="/docs/proxy">proxy and tagging</Link>,{" "}
          <Link href="/docs/budgets">budgets and hard caps</Link>. Errors and their fixes
          live in <Link href="/troubleshooting">troubleshooting</Link>.
        </p>
      </section>
    </>
  );
}

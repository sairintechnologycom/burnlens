import Link from "next/link";
import type { Metadata } from "next";
import data from "@/data/cost-per-outcome.json";

type ModelRow = { model: string; requests: number; cost_usd: number };

type Workflow = {
  workflow_id: string;
  window_start: string;
  window_end: string;
  requests: number;
  cost_usd: number;
  accepted: number;
  rejected: number;
  failed: number;
  cost_per_accepted_usd: number | null;
  tokens_per_accepted: number | null;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cache_read_share: number | null;
  models: ModelRow[];
};

const workflows = data.workflows as Workflow[];
const wf = workflows[0];

function usd(v: number, digits = 2): string {
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function day(iso: string): string {
  return iso.slice(0, 10);
}

function pct(v: number | null): string {
  return v === null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function millions(v: number): string {
  return `${(v / 1_000_000).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
}

const HEADLINE = wf.cost_per_accepted_usd === null ? "—" : usd(wf.cost_per_accepted_usd);

export const metadata: Metadata = {
  title: `What a merged pull request costs: ${HEADLINE} of agent spend`,
  description:
    `Measured unit economics from ${wf.requests.toLocaleString("en-US")} real agent requests: ${HEADLINE} of AI spend per merged pull request, with the method, the window, and the spend that could not be attributed.`,
  alternates: { canonical: "/cost-per-outcome" },
  openGraph: {
    title: `What a merged pull request costs: ${HEADLINE}`,
    description:
      `Real cost-per-accepted-outcome from BurnLens dogfooding itself — ${wf.accepted} merged pull requests against ${usd(wf.cost_usd)} of measured agent spend.`,
    url: "https://burnlens.app/cost-per-outcome",
    siteName: "BurnLens",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: `What a merged pull request costs: ${HEADLINE}`,
    description: `${wf.accepted} merged pull requests, ${usd(wf.cost_usd)} of measured agent spend, and the method behind the division.`,
  },
};

const structuredData = {
  "@context": "https://schema.org",
  "@type": "Dataset",
  name: "Cost per merged pull request from measured AI agent spend",
  description:
    "Unit economics for coding-agent work: total measured agent API spend divided by pull requests merged in the same window, with token composition and attribution coverage.",
  url: "https://burnlens.app/cost-per-outcome",
  temporalCoverage: `${day(wf.window_start)}/${day(wf.window_end)}`,
  creator: { "@type": "Organization", name: "BurnLens", url: "https://burnlens.app" },
  variableMeasured: [
    "cost per accepted outcome",
    "tokens per accepted outcome",
    "cache read share of prompt tokens",
  ],
};

export default function CostPerOutcome() {
  return (
    <div className="legal-page">
      <script type="application/ld+json">{JSON.stringify(structuredData)}</script>

      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>What a merged pull request costs</h1>
        <p className="legal-updated">
          {HEADLINE} per merged pull request · {wf.accepted} merged · {usd(wf.cost_usd)} measured agent
          spend · {day(wf.window_start)} to {day(wf.window_end)}
        </p>

        <section>
          <p>
            Token prices are public. What a unit of finished work costs is not — almost nobody
            measures it, because it needs agent spend and business outcomes joined on the same key.
            BurnLens does that on itself, so this page is our own number, with the arithmetic shown.
          </p>
          <p>
            Over {(wf.requests).toLocaleString("en-US")} agent requests costing {usd(wf.cost_usd)},
            this repository merged {wf.accepted} pull requests and closed {wf.rejected} without
            merging. That is <strong>{HEADLINE} of AI spend per merged pull request</strong>, or{" "}
            {wf.tokens_per_accepted === null ? "—" : millions(wf.tokens_per_accepted)} tokens each.
          </p>
        </section>

        <section>
          <h2>The method, including where it is weak</h2>
          <ul>
            <li>
              <strong>A merged pull request is the accepted outcome.</strong> Closed-unmerged is a
              rejected one. Both come from git, not from a form somebody remembered to fill in —{" "}
              cost-per-outcome products usually die on instrumentation nobody wires up.
            </li>
            <li>
              <strong>Total spend divides by accepted outcomes, not just successful spend.</strong>{" "}
              The {wf.rejected} rejected attempt{wf.rejected === 1 ? "" : "s"} cost real money.
              Charging that to the pull requests that landed is what one merged PR actually costs.
            </li>
            <li>
              <strong>The window is the intersection, not the union.</strong> Spend is measured from{" "}
              {day(wf.window_start)}; git remembers pull requests from well before that. Outcomes
              outside the spend window are excluded, because no telemetry backs them. Counting them
              would divide the same spend by a bigger number and quietly understate the unit cost.
            </li>
            <li>
              <strong>Attribution is per repository, not per pull request.</strong> Agent session logs
              record which repo a session was in, never which branch. With several PRs in flight at
              once, this is an average, not a per-PR invoice.
            </li>
            <li>
              <strong>Human time is not in it.</strong> This is API spend only — the AI cost of the
              work, not its fully loaded cost.
            </li>
          </ul>
        </section>

        <section>
          <h2>Where the money went</h2>
          <div className="lp-compare-wrap">
            <table className="pricing-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Requests</th>
                  <th>Spend</th>
                  <th>Share</th>
                </tr>
              </thead>
              <tbody>
                {wf.models.map((m) => (
                  <tr key={m.model}>
                    <td><code>{m.model}</code></td>
                    <td>{m.requests.toLocaleString("en-US")}</td>
                    <td>{usd(m.cost_usd)}</td>
                    <td>{pct(wf.cost_usd ? m.cost_usd / wf.cost_usd : null)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <h2>Why the token mix matters more than the token price</h2>
          <p>
            {pct(wf.cache_read_share)} of prompt tokens here were prompt-cache reads —{" "}
            {millions(wf.cache_read_tokens)} cached against {millions(wf.input_tokens)} fresh input. A
            coding agent re-sends its whole context every turn, so almost everything it reads is a
            cache hit billed at a fraction of the input rate.
          </p>
          <p>
            Estimate this workload off the input column of a{" "}
            <Link href="/llm-pricing">price list</Link> and you are wrong by close to an order of
            magnitude. Output was only {millions(wf.output_tokens)} tokens — under one percent of
            everything moved.
          </p>
        </section>

        <section>
          <h2>What is not in the number</h2>
          <p>
            The database behind this page holds {usd(data.database.total_cost_usd)} of measured spend
            in total. Only {usd(data.database.attributed_cost_usd)} of it carries a workflow id;{" "}
            {usd(data.database.unattributed_cost_usd)} does not, and none of that unattributed spend
            is in the division above.
          </p>
          <p>
            Most of it is older agent-log scans imported before workflow tagging existed. We publish
            it because a unit-economics number without its attribution coverage is not checkable, and
            the honest version of this metric is the one that shows what it had to leave out.
          </p>
        </section>

        <section>
          <h2>Measure your own</h2>
          <p>
            Cost per accepted outcome is the question token dashboards cannot answer: a model that
            looks cheaper per token can cost more per merged PR once retries and rejected work are
            counted. BurnLens is a local proxy that measures both —{" "}
            <code>pip install burnlens</code>, one environment variable, and merged pull requests are
            derived from git with nothing to integrate.
          </p>
          <p>
            <Link href="/docs">Read the docs</Link> · <Link href="/scan">Scan existing agent logs</Link>{" "}
            · <Link href="/llm-pricing">LLM pricing table</Link> · <Link href="/demo">See the dashboard</Link>
          </p>
        </section>
      </main>
    </div>
  );
}

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
  accepted_outside_window: number;
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
const pub = data.published;

/** Repos with a real unit cost, dearest first — the spread is the story. */
const priced = workflows
  .filter((w) => w.cost_per_accepted_usd !== null)
  .sort((a, b) => b.cost_per_accepted_usd! - a.cost_per_accepted_usd!);

const tokenTotals = workflows.reduce(
  (acc, w) => ({
    input: acc.input + w.input_tokens,
    output: acc.output + w.output_tokens,
    cacheRead: acc.cacheRead + w.cache_read_tokens,
    cacheWrite: acc.cacheWrite + w.cache_write_tokens,
  }),
  { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
);
const promptTokens = tokenTotals.input + tokenTotals.cacheRead;
const cacheShare = promptTokens ? tokenTotals.cacheRead / promptTokens : 0;

function usd(v: number, digits = 2): string {
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function repoName(workflowId: string): string {
  return workflowId.replace(/^repo:/, "");
}

function day(iso: string): string {
  return iso.slice(0, 10);
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function millions(v: number): string {
  return `${(v / 1_000_000).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
}

const CHEAPEST = usd(pub.cheapest_usd ?? 0);
const DEAREST = usd(pub.dearest_usd ?? 0);
const BLENDED = pub.cost_per_accepted_usd === null ? "—" : usd(pub.cost_per_accepted_usd);
const SPREAD = pub.cheapest_usd ? Math.round(pub.dearest_usd! / pub.cheapest_usd) : 0;

export const metadata: Metadata = {
  title: `What a merged pull request costs: ${CHEAPEST} to ${DEAREST} across ${pub.repos} repos`,
  description:
    `Measured unit economics from ${pub.requests.toLocaleString("en-US")} real agent requests across ${pub.repos} repositories: the same team and the same agents produce merged pull requests costing anywhere from ${CHEAPEST} to ${DEAREST}. Method, window, and unattributed spend all shown.`,
  alternates: { canonical: "/cost-per-outcome" },
  openGraph: {
    title: `What a merged pull request costs: ${CHEAPEST} to ${DEAREST}`,
    description:
      `Real cost-per-accepted-outcome across ${pub.repos} repositories — a ${SPREAD}x spread between the cheapest and dearest merged pull request, from ${usd(pub.cost_usd)} of measured agent spend.`,
    url: "https://burnlens.app/cost-per-outcome",
    siteName: "BurnLens",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: `What a merged pull request costs: ${CHEAPEST} to ${DEAREST}`,
    description: `A ${SPREAD}x spread in cost per merged PR across ${pub.repos} repositories, and the method behind the division.`,
  },
};

const structuredData = {
  "@context": "https://schema.org",
  "@type": "Dataset",
  name: "Cost per merged pull request from measured AI agent spend",
  description:
    "Unit economics for coding-agent work across multiple repositories: measured agent API spend divided by pull requests merged in the same telemetry window, with token composition and attribution coverage.",
  url: "https://burnlens.app/cost-per-outcome",
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
          {CHEAPEST} to {DEAREST} per merged pull request · {pub.repos} repositories ·{" "}
          {usd(pub.cost_usd)} measured agent spend · {pub.requests.toLocaleString("en-US")} requests
        </p>

        <section>
          <p>
            Token prices are public. What a unit of finished work costs is not — almost nobody
            measures it, because it needs agent spend and business outcomes joined on the same key.
            BurnLens does that on itself, across every repository it was used to build, so this page
            is our own number with the arithmetic shown.
          </p>
          <p>
            The headline is not a number. It is a <strong>{SPREAD}x spread</strong>. The same
            developer, the same agents, the same models produced merged pull requests costing{" "}
            {CHEAPEST} on one repository and {DEAREST} on another. Blended across all of them it is{" "}
            {BLENDED}, and that blended figure is the least useful number here — it hides exactly the
            variance worth acting on.
          </p>
        </section>

        <section>
          <h2>Cost per merged pull request, by repository</h2>
          <div className="lp-compare-wrap">
            <table className="pricing-table">
              <thead>
                <tr>
                  <th>Repository</th>
                  <th>Per merged PR</th>
                  <th>Merged</th>
                  <th>Spend</th>
                  <th>Requests</th>
                  <th>Tokens per PR</th>
                  <th>Telemetry window</th>
                </tr>
              </thead>
              <tbody>
                {priced.map((w) => (
                  <tr key={w.workflow_id}>
                    <td><code>{repoName(w.workflow_id)}</code></td>
                    <td><strong>{usd(w.cost_per_accepted_usd!)}</strong></td>
                    <td>{w.accepted.toLocaleString("en-US")}</td>
                    <td>{usd(w.cost_usd)}</td>
                    <td>{w.requests.toLocaleString("en-US")}</td>
                    <td>{millions(w.tokens_per_accepted!)}</td>
                    <td>{day(w.window_start)} → {day(w.window_end)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            {priced.length} of {pub.repos} repositories have a unit cost. The other{" "}
            {pub.repos - priced.length} are in the second table below, with the reason each one has
            no number.
          </p>
        </section>

        <section>
          <h2>Why the spread is this wide</h2>
          <p>
            Nothing here says the dear repositories were run badly. A unit cost is a ratio, and both
            halves move:
          </p>
          <ul>
            <li>
              <strong>Small denominators are loud.</strong> A repository with two merged pull
              requests divides real spend by two. Read the merged column before the cost column —
              one number in this table rests on a sample of 2.
            </li>
            <li>
              <strong>Not all agent work becomes a pull request.</strong> Exploration, debugging,
              spikes and abandoned branches cost money and merge nothing. A repository used mostly
              for investigation will always look expensive per PR, and that is a true statement
              about the work, not a defect in the measurement.
            </li>
            <li>
              <strong>Pull request size is not held constant.</strong> One merged PR is not one unit
              of work across repositories. This measures the cost of the granularity each repository
              actually used.
            </li>
          </ul>
          <p>
            That is the honest reading, and it is still actionable: a {SPREAD}x spread tells you
            where to look first, which is more than a token dashboard has ever told anyone.
          </p>
        </section>

        <section>
          <h2>Repositories with no unit cost</h2>
          <div className="lp-compare-wrap">
            <table className="pricing-table">
              <thead>
                <tr>
                  <th>Repository</th>
                  <th>Spend</th>
                  <th>Requests</th>
                  <th>Telemetry window</th>
                  <th>Why no number</th>
                </tr>
              </thead>
              <tbody>
                {workflows
                  .filter((w) => w.cost_per_accepted_usd === null)
                  .map((w) => (
                    <tr key={w.workflow_id}>
                      <td><code>{repoName(w.workflow_id)}</code></td>
                      <td>{usd(w.cost_usd)}</td>
                      <td>{w.requests.toLocaleString("en-US")}</td>
                      <td>{day(w.window_start)} → {day(w.window_end)}</td>
                      <td>
                        {w.accepted_outside_window > 0
                          ? `${w.accepted_outside_window} merged PRs, all outside this window`
                          : "no merged pull requests on record"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <p>
            Two different reasons, and the distinction matters. Most of these repositories are
            trunk-based — work lands on the default branch and no pull request is ever opened, so
            there is no accepted outcome to divide by. Outcomes are derived through the GitHub CLI,
            so a repository whose remote lives elsewhere cannot report them either.
          </p>
          <p>
            One row is different: <code>ShubhLifafa</code> has {
              workflows.find((w) => w.workflow_id === "repo:ShubhLifafa")?.accepted_outside_window ?? 0
            }{" "}
            merged pull requests and still no unit cost, because every one of them closed outside
            the window where its spend was measured. That is the window rule below, visible.
          </p>
        </section>

        <section>
          <h2>The method, including where it is weak</h2>
          <ul>
            <li>
              <strong>A merged pull request is the accepted outcome.</strong> Closed-unmerged is a
              rejected one. Both come from git, not from a form somebody remembered to fill in —
              cost-per-outcome products usually die on instrumentation nobody wires up.
            </li>
            <li>
              <strong>Total spend divides by accepted outcomes, not just successful spend.</strong>{" "}
              Rejected and abandoned attempts cost real money. Charging that to the pull requests
              that landed is what one merged PR actually costs.
            </li>
            <li>
              <strong>Each repository&rsquo;s window is its own, and it is an intersection.</strong>{" "}
              Telemetry for a repository starts when the proxy first saw it; git remembers pull
              requests from well before that. Outcomes outside a repository&rsquo;s spend window are
              excluded, because no telemetry backs them. Counting them would divide the same spend
              by a bigger number and quietly understate the unit cost — on this repository it is the
              difference between {CHEAPEST} and $5.43.
            </li>
            <li>
              <strong>Attribution is per repository, not per pull request.</strong> Agent session
              logs record which repo a session was in, never which branch. With several PRs in
              flight at once, every number here is an average, not a per-PR invoice.
            </li>
            <li>
              <strong>The blended figure is spend-weighted, not an average of the rates.</strong> A
              mean of ratios would weight a 2-PR repository the same as a 104-PR one.
            </li>
            <li>
              <strong>Human time is not in it.</strong> This is API spend only — the AI cost of the
              work, not its fully loaded cost.
            </li>
          </ul>
        </section>

        <section>
          <h2>Why the token mix matters more than the token price</h2>
          <p>
            {pct(cacheShare)} of prompt tokens across all {pub.repos} repositories were
            prompt-cache reads — {millions(tokenTotals.cacheRead)} cached against{" "}
            {millions(tokenTotals.input)} fresh input. A coding agent re-sends its whole context
            every turn, so almost everything it reads is a cache hit billed at a fraction of the
            input rate.
          </p>
          <p>
            Estimate this workload off the input column of a{" "}
            <Link href="/llm-pricing">price list</Link> and you are wrong by close to an order of
            magnitude. Output was only {millions(tokenTotals.output)} tokens — well under one
            percent of everything moved.
          </p>
        </section>

        <section>
          <h2>What is not in the number</h2>
          <p>
            The database behind this page holds {usd(data.database.total_cost_usd)} of measured
            spend. Only {usd(data.database.attributed_cost_usd)} of it carries a workflow id, and
            the {pub.repos} repositories published here account for {usd(pub.cost_usd)} of that.
            None of the remainder is in any division above.
          </p>
          <p>
            Most of the unattributed {usd(data.database.unattributed_cost_usd)} is older agent-log
            scans imported before workflow tagging existed. A little of it carries a workflow id
            that is not a repository at all — an artifact of how session logs encode a working
            directory — and those are excluded rather than published under a name nobody could look
            up.
          </p>
          <p>
            We publish this because a unit-economics number without its attribution coverage is not
            checkable, and the honest version of the metric is the one that shows what it left out.
          </p>
        </section>

        <section>
          <h2>Measure your own</h2>
          <p>
            Cost per accepted outcome is the question token dashboards cannot answer: a model that
            looks cheaper per token can cost more per merged PR once retries and rejected work are
            counted, and a {SPREAD}x spread between your own repositories is invisible until you
            measure it. BurnLens is a local proxy that does —{" "}
            <code>pip install burnlens</code>, one environment variable, and merged pull requests
            are derived from git with nothing to integrate.
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

import Link from "next/link";
import type { Metadata } from "next";
import { Code, GH } from "@/lib/docs";

const TITLE = "Budgets and hard caps — BurnLens Docs";
const DESCRIPTION =
  "Give an API key a daily dollar cap and the BurnLens proxy returns 429 before the call is forwarded upstream, so it is never billed. Team and customer budgets, virtual keys, unpriced-model blocking, and budget-aware model downgrade.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/docs/budgets" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: "https://burnlens.app/docs/budgets",
    siteName: "BurnLens",
    type: "article",
  },
};

export default function DocsBudgetsPage() {
  return (
    <>
      <h1>Budgets and hard caps</h1>
      <p className="legal-updated">
        Config keys read out of <code>burnlens/config.py</code> and{" "}
        <code>burnlens/proxy/router.py</code> on 2026-08-16.
      </p>

      <section id="why">
        <h2>Why this is different from an alert</h2>
        <p>
          An alert tells you that money is gone. Because the proxy sees a request{" "}
          <em>before</em> forwarding it, BurnLens can decline one that would breach a cap:
          the caller gets <code>429</code>, the upstream request is never made, and the
          call never appears on a bill. That is the whole reason the proxy is a proxy and
          not a log shipper.
        </p>
      </section>

      <section id="config">
        <h2>Where config lives</h2>
        <p>
          BurnLens looks for a YAML file in this order: the path in{" "}
          <code>BURNLENS_CONFIG_PATH</code>, then <code>./burnlens.yaml</code> or{" "}
          <code>./burnlens.yml</code>, then <code>~/.burnlens/config.yaml</code>. Every
          example below goes in that file.
        </p>
        <p>
          It is YAML, not TOML. A <code>.toml</code> file in the same place is not picked
          up, and the failure is quiet — your limits simply never apply.
        </p>
      </section>

      <section id="key-caps">
        <h2>Per-key daily caps</h2>
        <p>
          Register a key by label so caps can target it, then give the label a daily dollar
          limit. Raw keys are never displayed back to you.
        </p>
        <Code>{`burnlens key register --label prod-openai --provider openai
burnlens key list
burnlens keys              # today's spend per label against its cap
burnlens keys --json       # same, machine-readable`}</Code>
        <p>
          The caps themselves nest under <code>alerts:</code>, which is not guessable from
          the CLI:
        </p>
        <Code>{`alerts:
  api_key_budgets:
    reset_timezone: Asia/Kolkata   # IANA name; an invalid value falls back to UTC
    prod-openai:
      daily_usd: 50.0
    default:                       # registered labels with no override of their own
      daily_usd: 5.0`}</Code>
        <p>
          At 100% of the cap the proxy returns <code>429</code> before forwarding. The 50%
          and 80% thresholds fire alerts instead of blocking.
        </p>
      </section>

      <section id="team-customer">
        <h2>Team and customer budgets</h2>
        <p>
          These are keyed on the tag values described in{" "}
          <Link href="/docs/proxy#tags">tagging</Link> — untagged traffic cannot be
          budgeted, so tag first.
        </p>
        <Code>{`alerts:
  budget:                    # your own overall spend
    daily_usd: 100.0
    monthly_usd: 2000.0
  budgets:                   # per-team, from X-BurnLens-Tag-Team
    global: 5000.0
    teams:
      platform: 2000.0
      growth: 500.0
  customer_budgets:          # per-customer, from X-BurnLens-Tag-Customer
    default: 50.0
    customers:
      acme-corp: 500.0`}</Code>
        <Code>{`burnlens budgets       # per-team status for the current month
burnlens customers     # per-customer spend and budget status`}</Code>
      </section>

      <section id="vkeys">
        <h2>Virtual keys</h2>
        <p>
          A virtual key lets you hand a team a token instead of the real provider key. The
          real key stays in an environment variable on the proxy host; the virtual key
          carries a monthly budget and an optional model allowlist, and can be revoked
          without rotating anything upstream.
        </p>
        <Code>{`burnlens vkey issue --label growth-team --team growth \\
  --provider openai --upstream-env OPENAI_API_KEY \\
  --budget 500 --allow gpt-5.6-terra,gpt-5.6-sol

burnlens vkey list
burnlens vkey revoke --label growth-team`}</Code>
        <p>
          The raw token is printed once, at issue time, and never stored — so it can never
          be shown again. Store it when you see it.
        </p>
      </section>

      <section id="unpriced">
        <h2>Unpriced models are blocked by default</h2>
        <p>
          A model with no pricing entry costs BurnLens $0. Its spend therefore never
          advances a budget, and a cap covering it would enforce nothing at all. Rather
          than let a cap silently become decorative, such a request is rejected with{" "}
          <code>403</code>.
        </p>
        <Code>{`block_unpriced_models: true   # default`}</Code>
        <p>
          This only applies where a budget actually covers the request. Uncapped traffic on
          a brand-new model is unaffected. Set it to <code>false</code> if you would rather
          have availability than enforcement — for instance when a provider has shipped a
          model before BurnLens has shipped its price — and its spend then counts as $0.
          Check <code>burnlens pricing</code> to see what is priced.
        </p>
      </section>

      <section id="downgrade">
        <h2>Budget-aware model downgrade</h2>
        <p>
          Instead of hard-blocking, BurnLens can route a request to a cheaper model as a
          budget runs low. <strong>This is on by default</strong>, and it only ever
          activates once a budget exists — with no budget configured, nothing is
          downgraded.
        </p>
        <Code>{`routing:
  budget_downgrade: true        # default
  downgrade_threshold_pct: 20   # under 20% of the budget remaining
  downgrade_threshold_usd: 5.0  # ...or under $5 remaining
  log_downgrades: true          # default`}</Code>
        <p>
          The percentage check runs first, so when both would trigger the reason is
          recorded as <code>budget_pct</code>. Every downgrade is logged and{" "}
          <code>burnlens routing</code> shows the activity. Set{" "}
          <code>budget_downgrade: false</code> to always receive the model you asked for
          and take the 429 instead.
        </p>
      </section>

      <section id="semantics">
        <h2>Exact enforcement semantics</h2>
        <p>
          Behaviour under concurrency, streaming responses, retries and unpriced models —
          with the implementing function cited for every claim — is documented in{" "}
          <a href={`${GH}/blob/main/docs/BUDGET_ENFORCEMENT.md`} target="_blank" rel="noreferrer">
            BUDGET_ENFORCEMENT.md
          </a>
          . Read it before relying on a cap as a financial control rather than a guardrail.
        </p>
      </section>
    </>
  );
}

import Link from "next/link";
import type { Metadata } from "next";

const TITLE = "BurnLens Docs — install, scan, proxy, budgets, CLI";
const DESCRIPTION =
  "How to install BurnLens, scan Claude Code / Cursor / Codex / Gemini CLI logs, route production APIs through the local proxy, tag spend, and enforce hard daily caps. Every command and config key verified against the source.";

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

const GH = "https://github.com/sairintechnologycom/burnlens";

// Verified 2026-08-16 by dumping the live provider registry:
//   python -c "import burnlens.proxy.server; from burnlens.providers.registry import all_providers; ..."
// A provider with no env var cannot be redirected by environment alone — the
// docs must say so rather than inventing a plausible-looking variable name.
const PROVIDERS: { name: string; path: string; env: string | null }[] = [
  { name: "OpenAI", path: "/proxy/openai", env: "OPENAI_BASE_URL" },
  { name: "Anthropic", path: "/proxy/anthropic", env: "ANTHROPIC_BASE_URL" },
  { name: "Groq", path: "/proxy/groq", env: "GROQ_BASE_URL" },
  { name: "xAI", path: "/proxy/xai", env: "XAI_BASE_URL" },
  { name: "DeepSeek", path: "/proxy/deepseek", env: "DEEPSEEK_BASE_URL" },
  { name: "Azure OpenAI", path: "/proxy/azure", env: "AZURE_OPENAI_ENDPOINT" },
  { name: "AWS Bedrock", path: "/proxy/bedrock", env: "AWS_ENDPOINT_URL_BEDROCK_RUNTIME" },
  { name: "Google (Gemini)", path: "/proxy/google", env: null },
  { name: "Mistral", path: "/proxy/mistral", env: null },
  { name: "Together", path: "/proxy/together", env: null },
];

const AGENTS: { name: string; source: string }[] = [
  { name: "Claude Code", source: "~/.claude/projects/**/*.jsonl" },
  { name: "Cursor", source: "Cursor globalStorage state.vscdb" },
  { name: "Codex", source: "~/.codex/sessions/**/rollout-*.jsonl" },
  { name: "Gemini CLI", source: "~/.gemini/tmp/<project>/chats/" },
];

const COMMANDS: { cmd: string; what: string }[] = [
  { cmd: "scan", what: "Import coding-agent session costs from disk into the requests DB." },
  { cmd: "start", what: "Start the BurnLens proxy server." },
  { cmd: "top", what: "Live API traffic viewer with auto-refresh." },
  { cmd: "ui", what: "Open the dashboard in the default browser." },
  { cmd: "report", what: "Generate and print (or email) a cost summary report." },
  { cmd: "analyze", what: "Run waste detectors and print findings." },
  { cmd: "findings", what: "Persisted waste findings and their lifecycle." },
  { cmd: "economics", what: "Top-line runtime economics: spend, waste rate, error spend, cost/outcome." },
  { cmd: "outcome", what: "Record business outcomes to get cost per accepted outcome." },
  { cmd: "runs", what: "Group spend into runs and their steps." },
  { cmd: "repos / prs / devs", what: "Top 20 repos, PRs, or developers by cost over the lookback window." },
  { cmd: "budgets", what: "Show per-team budget status for the current month." },
  { cmd: "customers", what: "Show per-customer spend and budget status for the current month." },
  { cmd: "key / keys", what: "Register API keys by label, and show today's spend against each daily cap." },
  { cmd: "vkey", what: "Issue virtual keys (gateway): per-team budget + model allowlist." },
  { cmd: "routing", what: "Show downgrade routing activity." },
  { cmd: "recommend", what: "Analyse usage patterns and suggest cheaper model alternatives." },
  { cmd: "pricing", what: "Show the bundled model pricing table ($/1M tokens), or export it as CSV." },
  { cmd: "export", what: "Export request data to CSV." },
  { cmd: "login / sync", what: "Authenticate with burnlens.app, then trigger cloud sync or check its status." },
  { cmd: "doctor", what: "Run system health checks on proxy, database, and providers." },
  { cmd: "check-otel", what: "Verify connectivity to the OpenTelemetry collector." },
  { cmd: "wal", what: "Manage the Write-Ahead Log (WAL) and Dead Letter Queue (DLQ)." },
  { cmd: "run", what: "Run a child command with auto-tagged git context." },
];

const CODE_BLOCK: React.CSSProperties = {
  background: "#0e1318",
  border: "1px solid #1e2830",
  padding: "1rem 1.25rem",
  borderRadius: 8,
  overflowX: "auto",
  fontSize: 13,
  lineHeight: 1.7,
};

function Code({ children }: { children: string }) {
  return (
    <pre style={CODE_BLOCK}>
      <code>{children}</code>
    </pre>
  );
}

export default function DocsPage() {
  return (
    <div className="legal-page">
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>BurnLens Documentation</h1>
        <p className="legal-updated">
          Everything below was checked against the source on 2026-08-16. If a command or
          config key here does not match what your install does, the install is older —
          check <code>pip show burnlens</code> before assuming the docs are wrong.
        </p>

        <section id="install">
          <h2>Install</h2>
          <p>
            BurnLens is a Python package. It needs Python 3.10 or newer, and it stores
            everything in a local SQLite database at <code>~/.burnlens/burnlens.db</code>.
            No account is required for anything on this page except cloud sync.
          </p>
          <Code>{`pip install burnlens`}</Code>
          <p>
            There are two independent ways to use it, and you do not need both. Scanning
            reads cost history your coding agents have <em>already</em> written to disk.
            The proxy sits in front of production API traffic and can refuse a call before
            it is billed.
          </p>
        </section>

        <section id="scan">
          <h2>Scan coding-agent spend</h2>
          <p>
            <code>burnlens scan</code> reads the session logs your coding agents write
            locally, deduplicates the turns, prices each call, and stores the result. It
            makes no network calls to BurnLens and needs no proxy, no code change, and no
            signup.
          </p>
          <Code>{`burnlens scan          # import every agent it can find
burnlens top           # live view of what is being spent
burnlens repos         # top repos by cost
burnlens prs           # top PRs by cost`}</Code>
          <table className="lp-compare-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Read from</th>
              </tr>
            </thead>
            <tbody>
              {AGENTS.map((a) => (
                <tr key={a.name}>
                  <td><strong>{a.name}</strong></td>
                  <td><code>{a.source}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            Scanned rows carry no prompt or response text — only model, token counts,
            timestamps, and the repo the session ran in. Cost is therefore attributed per
            repository, not per branch: agent logs record which repo a session ran in, and
            nothing more.{" "}
            <Link href="/scan">More about scanning</Link>.
          </p>
        </section>

        <section id="proxy">
          <h2>Proxy production API traffic</h2>
          <p>
            <code>burnlens start</code> runs a local proxy on{" "}
            <code>127.0.0.1:8420</code>. Point your SDK at the matching proxy path and
            your existing code routes through it unchanged — BurnLens forwards the request
            upstream, including streaming responses, and records what it cost.
          </p>
          <Code>{`burnlens start
export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai`}</Code>
          <table className="lp-compare-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Proxy path</th>
                <th>SDK environment variable</th>
              </tr>
            </thead>
            <tbody>
              {PROVIDERS.map((p) => (
                <tr key={p.name}>
                  <td><strong>{p.name}</strong></td>
                  <td><code>{p.path}</code></td>
                  <td>{p.env ? <code>{p.env}</code> : <em>none — see below</em>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            <strong>Google, Mistral and Together expose no base-URL environment variable.</strong>{" "}
            Their SDKs cannot be redirected by environment alone, so setting one does
            nothing. For Google, call the patch helper once at startup:
          </p>
          <Code>{`from burnlens.patch import patch_google
patch_google()`}</Code>
          <p>
            For Mistral and Together, pass the proxy path as the client&apos;s base URL
            where you construct the client. Provider-specific detail — including Azure
            deployment routing and Bedrock bearer-token auth — lives in{" "}
            <a href={`${GH}/blob/main/docs/PROVIDERS.md`} target="_blank" rel="noreferrer">
              PROVIDERS.md
            </a>.
          </p>
        </section>

        <section id="tags">
          <h2>Attribute spend with tags</h2>
          <p>
            Three request headers attribute any call to any dimension you care about.
            BurnLens strips them before the request reaches the provider.
          </p>
          <Code>{`X-BurnLens-Tag-Feature: checkout-summariser
X-BurnLens-Tag-Team: platform
X-BurnLens-Tag-Customer: acme-corp`}</Code>
          <p>
            If you enable cloud sync, tag <em>values</em> are uploaded alongside cost
            metadata. Prompt and response bodies are never uploaded — they go to your
            provider and nowhere else.
          </p>
        </section>

        <section id="budgets">
          <h2>Budgets and hard caps</h2>
          <p>
            Register a key by label, then give that label a daily dollar cap. At 100% of
            the cap the proxy returns <code>429</code> <em>before</em> forwarding the
            request upstream, so the call is never billed.
          </p>
          <Code>{`burnlens key register --label prod-openai --provider openai
burnlens keys          # today's spend per label, against its cap`}</Code>
          <p>
            Caps live in the YAML config, nested under <code>alerts:</code>. BurnLens
            looks for <code>BURNLENS_CONFIG_PATH</code>, then the current directory, then{" "}
            <code>~/.burnlens/config.yaml</code>.
          </p>
          <Code>{`alerts:
  api_key_budgets:
    reset_timezone: Asia/Kolkata   # IANA name; invalid values fall back to UTC
    prod-openai:
      daily_usd: 50.0
    default:                       # applies to registered labels with no override
      daily_usd: 5.0`}</Code>
          <p>
            One default worth knowing about: <code>block_unpriced_models</code> is{" "}
            <code>true</code>. A model with no pricing entry costs BurnLens $0, so its
            spend never advances a budget and a cap over it would enforce nothing. Rather
            than silently under-count, such a request is rejected with <code>403</code> —
            but only where a budget actually applies to it. Uncapped traffic on a new model
            is unaffected. Set it to <code>false</code> to prefer availability over
            enforcement. Exact behaviour under concurrency, streaming and retries is in{" "}
            <a href={`${GH}/blob/main/docs/BUDGET_ENFORCEMENT.md`} target="_blank" rel="noreferrer">
              BUDGET_ENFORCEMENT.md
            </a>.
          </p>
        </section>

        <section id="routing">
          <h2>Budget-aware model downgrade</h2>
          <p>
            Instead of hard-blocking, BurnLens can route a request to a cheaper model when
            a budget is nearly spent. <strong>This is on by default</strong>, and it only
            ever activates once you have set a budget — with no budget configured, nothing
            is ever downgraded.
          </p>
          <Code>{`routing:
  budget_downgrade: true        # default
  downgrade_threshold_pct: 20   # downgrade under 20% of budget remaining
  downgrade_threshold_usd: 5.0  # ...or under $5 remaining
  log_downgrades: true          # default`}</Code>
          <p>
            Every downgrade is recorded; <code>burnlens routing</code> shows the activity.
            Set <code>budget_downgrade: false</code> if you would rather always receive the
            model you asked for and take the 429.
          </p>
        </section>

        <section id="cloud">
          <h2>Cloud sync</h2>
          <p>
            Everything above works offline and forever free. Cloud sync is optional: it
            pushes cost metadata to your workspace so a team can share one dashboard.
          </p>
          <Code>{`burnlens login         # authenticate and enable cloud sync
burnlens sync --status # what has been pushed, and what has not`}</Code>
          <p>
            The free plan keeps 7 days of history, 10,000 records per month, one API key
            and one seat. Paid plans extend retention and seats — see{" "}
            <Link href="/#pricing">pricing</Link>. Cost metadata is uploaded; prompt and
            response bodies are not.{" "}
            <Link href="/security">How data is handled</Link>.
          </p>
        </section>

        <section id="cli">
          <h2>CLI reference</h2>
          <p>
            Every command takes <code>--help</code>. The list below is the top-level
            surface as of 2026-08-16.
          </p>
          <table className="lp-compare-table">
            <thead>
              <tr>
                <th>Command</th>
                <th>What it does</th>
              </tr>
            </thead>
            <tbody>
              {COMMANDS.map((c) => (
                <tr key={c.cmd}>
                  <td><code>burnlens {c.cmd}</code></td>
                  <td>{c.what}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section id="deeper">
          <h2>Going deeper</h2>
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
              — enforcement semantics, with the implementing function cited per claim.
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
          <p>
            Something here wrong or missing?{" "}
            <a href={`${GH}/issues`} target="_blank" rel="noreferrer">Open an issue</a> or
            email <a href="mailto:support@burnlens.app">support@burnlens.app</a>.
          </p>
        </section>
      </main>
    </div>
  );
}

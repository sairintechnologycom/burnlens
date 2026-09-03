import type { CSSProperties, ReactNode } from "react";

export const GH = "https://github.com/sairintechnologycom/burnlens";

const CODE_BLOCK: CSSProperties = {
  background: "#0e1318",
  border: "1px solid #1e2830",
  padding: "1rem 1.25rem",
  borderRadius: 8,
  overflowX: "auto",
  fontSize: 13,
  lineHeight: 1.7,
};

export function Code({ children }: { children: string }): ReactNode {
  return (
    <pre style={CODE_BLOCK}>
      <code>{children}</code>
    </pre>
  );
}

/** Every docs route, in reading order. Drives the sidebar and the hub index. */
export const DOCS_PAGES: { href: string; title: string; blurb: string }[] = [
  {
    href: "/docs",
    title: "Overview & install",
    blurb: "What BurnLens is, how to install it, and which of the two entry points you want.",
  },
  {
    href: "/docs/scan",
    title: "Scanning coding agents",
    blurb: "Import Claude Code, Cursor, Codex and Gemini CLI cost history from local logs.",
  },
  {
    href: "/docs/proxy",
    title: "Proxy & tagging",
    blurb: "Route production API traffic through the local proxy and attribute it with tags.",
  },
  {
    href: "/docs/budgets",
    title: "Budgets & hard caps",
    blurb: "Daily key caps, team and customer budgets, virtual keys, downgrade routing.",
  },
  {
    href: "/docs/evidence",
    title: "Cost evidence",
    blurb: "Cost Confidence, Outcome Coverage and Verified Savings — how much of a number BurnLens can prove.",
  },
  {
    href: "/docs/limitations",
    title: "Known limitations",
    blurb: "Where each figure stops being authoritative, stated plainly.",
  },
  {
    href: "/docs/cli",
    title: "CLI reference",
    blurb: "Every burnlens command, and where the config file and database live.",
  },
];

/**
 * Verified 2026-08-16 by dumping the live provider registry:
 *   import burnlens.proxy.server; from burnlens.providers.registry import all_providers
 *
 * A provider whose ProviderConfig.env_var is "" cannot be redirected by
 * environment alone. Inventing a plausible-looking variable name for those
 * fails silently — traffic goes straight to the provider while the user
 * believes it is being metered — so the docs must say "none" and mean it.
 */
export const PROVIDERS: { name: string; path: string; env: string | null }[] = [
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

/** `burnlens --help`, verbatim, as of 2026-08-16. */
export const COMMANDS: { cmd: string; what: string; group: string }[] = [
  { group: "Collect", cmd: "scan", what: "Import coding-agent session costs from disk, then derive merged-PR outcomes when gh is present." },
  { group: "Collect", cmd: "start", what: "Start the BurnLens proxy server." },
  { group: "Collect", cmd: "run", what: "Run a child command with auto-tagged git context." },
  { group: "Look at spend", cmd: "top", what: "Live API traffic viewer with auto-refresh." },
  { group: "Look at spend", cmd: "ui", what: "Open the dashboard in the default browser." },
  { group: "Look at spend", cmd: "report", what: "Generate and print (or email) a cost summary report." },
  { group: "Look at spend", cmd: "repos", what: "Show top 20 repos by cost over the lookback window." },
  { group: "Look at spend", cmd: "prs", what: "Show top 20 PRs by cost over the lookback window." },
  { group: "Look at spend", cmd: "devs", what: "Show top 20 developers by cost over the lookback window." },
  { group: "Look at spend", cmd: "runs", what: "Group spend into runs and their steps." },
  { group: "Look at spend", cmd: "export", what: "Export request data to CSV." },
  { group: "Find waste", cmd: "analyze", what: "Run waste detectors and print findings." },
  { group: "Find waste", cmd: "findings", what: "Persisted waste findings and their lifecycle." },
  { group: "Find waste", cmd: "economics", what: "Top-line runtime economics: spend, waste rate, error spend, cost/outcome." },
  { group: "Find waste", cmd: "outcome", what: "Record business outcomes to get cost per accepted outcome." },
  { group: "Find waste", cmd: "recommend", what: "Analyse usage patterns and suggest cheaper model alternatives." },
  { group: "Control spend", cmd: "budgets", what: "Show per-team budget status for the current month." },
  { group: "Control spend", cmd: "customers", what: "Show per-customer spend and budget status for the current month." },
  { group: "Control spend", cmd: "key", what: "Register API keys for per-key daily caps." },
  { group: "Control spend", cmd: "keys", what: "Show today's spend per API-key label against its daily cap." },
  { group: "Control spend", cmd: "vkey", what: "Issue virtual keys (gateway): per-team budget + model allowlist." },
  { group: "Control spend", cmd: "routing", what: "Show downgrade routing activity." },
  { group: "Operate", cmd: "login", what: "Authenticate with burnlens.app and enable cloud sync." },
  { group: "Operate", cmd: "sync", what: "Manually trigger cloud sync or check sync status." },
  { group: "Operate", cmd: "doctor", what: "Run system health checks on proxy, database, and providers." },
  { group: "Operate", cmd: "pricing", what: "Show the bundled model pricing table ($/1M tokens), or export it as CSV." },
  { group: "Operate", cmd: "check-otel", what: "Verify connectivity to the OpenTelemetry collector." },
  { group: "Operate", cmd: "wal", what: "Manage the Write-Ahead Log (WAL) and Dead Letter Queue (DLQ)." },
];

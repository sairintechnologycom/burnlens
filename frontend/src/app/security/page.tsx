import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Security & Privacy — what BurnLens sees, what it never sends · BurnLens",
  description:
    "BurnLens runs on your machine. Prompts, responses, and code never leave. Cloud sync uploads only anonymized token counts, costs, and SHA-256 hashes — never request or response bodies.",
  alternates: { canonical: "/security" },
  openGraph: {
    title: "Security & Privacy — what BurnLens sees, what it never sends",
    description:
      "Local-first by design. Prompts and responses stay on your machine. Cloud sync uploads anonymized counts and costs only — never bodies.",
    url: "https://burnlens.app/security",
    siteName: "BurnLens",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: "Security & Privacy — what BurnLens sees, what it never sends",
    description:
      "Local-first by design. Prompts and responses stay on your machine. Cloud sync uploads anonymized counts and costs only — never bodies.",
  },
};

const faqStructuredData = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Does BurnLens see my prompts?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "BurnLens runs locally on your machine and reads the request body to extract the model name and tag headers. Prompts and responses are written only to a local SQLite database at ~/.burnlens/burnlens.db. They never leave your machine. Cloud sync, if you enable it, uploads only anonymized token counts, costs, model names, and a SHA-256 hash of the system prompt — never the prompt text itself.",
      },
    },
    {
      "@type": "Question",
      name: "What does BurnLens send to the upstream AI provider?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Your original request, byte-for-byte, with BurnLens-specific headers stripped. Specifically, every header starting with X-BurnLens- (including tag headers like X-BurnLens-Tag-Feature) is removed before the request is forwarded to OpenAI, Anthropic, Google, or any other configured provider. Your auth header, body, and other headers pass through unchanged.",
      },
    },
    {
      "@type": "Question",
      name: "What exactly gets uploaded if I turn on cloud sync?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Per request: timestamp, provider, model, input/output/reasoning/cache token counts, USD cost, duration, HTTP status, optional tag values (feature/team/customer), and a SHA-256 hash of the system prompt for duplicate detection. There is no field in the payload for the prompt body, response body, tool calls, or any user-supplied content.",
      },
    },
    {
      "@type": "Question",
      name: "Is BurnLens open source?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. The proxy, CLI, dashboard, scan readers, and cost engine are Apache-2.0 licensed and live at github.com/sairintechnologycom/burnlens. You can audit the sync payload, run BurnLens entirely offline, or fork it. The cloud backend that receives sync batches is not open source; it is a managed service for the hosted dashboard.",
      },
    },
    {
      "@type": "Question",
      name: "Can I use BurnLens without any cloud component?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. Cloud sync is opt-in. If you never run burnlens login, no API key is configured, and no data is ever sent off-machine. The local proxy, dashboard at localhost:8420/ui, CLI commands (top, report, scan, analyze), and SQLite database all work without an internet connection to BurnLens.",
      },
    },
  ],
};

const SENT_FIELDS = [
  { field: "timestamp", purpose: "Order requests on the timeline" },
  { field: "provider", purpose: "openai / anthropic / google / etc." },
  { field: "model", purpose: "Price lookup and per-model rollups" },
  { field: "input_tokens / output_tokens / reasoning_tokens", purpose: "Cost math" },
  { field: "cache_read_tokens / cache_write_tokens", purpose: "Cache efficiency rollups" },
  { field: "cost_usd", purpose: "Already-computed cost (you don't have to trust ours)" },
  { field: "duration_ms", purpose: "Latency rollups" },
  { field: "status_code", purpose: "Error-rate rollups" },
  { field: "system_prompt_hash (SHA-256)", purpose: "Duplicate-system-prompt detection" },
  { field: "tag_feature / tag_team / tag_customer", purpose: "Optional rollup dimensions you opted into" },
];

const NEVER_SENT = [
  "Request body (prompts, messages, tool definitions, attachments)",
  "Response body (model output, tool calls, citations)",
  "Streaming chunks",
  "Provider API keys or auth headers",
  "File paths, repo names, branch names — unless you explicitly pass them as tag values",
  "Local environment variables outside of BURNLENS_TAG_* opt-ins",
];

export default function SecurityPage() {
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
            color: "var(--cyan, #00e5c8)",
            marginBottom: 8,
          }}
        >
          security · privacy · data flow
        </p>
        <h1>What BurnLens sees, what it never sends</h1>
        <p className="legal-updated">
          Local-first by design · Apache-2.0 · cloud sync is opt-in and body-free
        </p>

        <section>
          <h2>The short version</h2>
          <p>
            BurnLens is a proxy that runs on <strong>your</strong> machine. Your AI SDK talks to{" "}
            <code>localhost:8420</code>; BurnLens forwards the call to OpenAI, Anthropic, or Google;
            the response comes back unmodified. Cost calculation and logging happen locally, against
            a SQLite database at <code>~/.burnlens/burnlens.db</code>.
          </p>
          <p>
            <strong>Prompts and responses never leave your machine.</strong> If you choose to enable
            cloud sync for a team dashboard, BurnLens uploads only anonymized counts, costs, and
            hashes — never the bodies of requests or responses.
          </p>
        </section>

        <section>
          <h2>What stays on your machine, always</h2>
          <ul>
            <li>
              The full request body sent to the upstream provider (prompts, messages, tool
              definitions, attachments)
            </li>
            <li>The full response body returned by the provider (model output, tool calls)</li>
            <li>Your provider API keys — BurnLens passes them through; it does not store them</li>
            <li>
              SQLite database at <code>~/.burnlens/burnlens.db</code> (rows include token counts,
              cost, model, tags, and a SHA-256 hash of the system prompt; not the prompt text)
            </li>
            <li>
              Any data <code>burnlens scan</code> reads from your local coding-agent log
              directories (<code>~/.claude/projects/</code>, Cursor bubble DB, Codex SQLite,{" "}
              <code>~/.gemini/tmp/</code>)
            </li>
          </ul>
        </section>

        <section>
          <h2>What BurnLens strips before forwarding to the provider</h2>
          <p>
            Every request header starting with <code>X-BurnLens-</code> is removed before BurnLens
            forwards the call upstream. That means tag headers like{" "}
            <code>X-BurnLens-Tag-Feature: checkout</code> are visible to your local BurnLens
            instance but never sent to OpenAI / Anthropic / Google. Your{" "}
            <code>Authorization</code> header and request body pass through byte-for-byte.
          </p>
          <p>
            Source:{" "}
            <a
              href="https://github.com/sairintechnologycom/burnlens/blob/main/burnlens/proxy/interceptor.py"
              target="_blank"
              rel="noopener noreferrer"
            >
              burnlens/proxy/interceptor.py
            </a>{" "}
            (<code>_clean_request_headers</code>).
          </p>
        </section>

        <section>
          <h2>What cloud sync uploads (opt-in)</h2>
          <p>
            If — and only if — you run <code>burnlens login</code> and configure a{" "}
            <code>bl_live_xxx</code> API key, the background sync client batches local cost rows and
            posts them to <code>api.burnlens.app/v1/ingest</code> every 60 seconds. Each row in the
            batch is exactly these fields:
          </p>
          <table className="lp-compare-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Why we need it</th>
              </tr>
            </thead>
            <tbody>
              {SENT_FIELDS.map((f) => (
                <tr key={f.field}>
                  <td><code>{f.field}</code></td>
                  <td>{f.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            Source:{" "}
            <a
              href="https://github.com/sairintechnologycom/burnlens/blob/main/burnlens/cloud/sync.py"
              target="_blank"
              rel="noopener noreferrer"
            >
              burnlens/cloud/sync.py
            </a>{" "}
            (<code>_row_to_payload</code>) — this is the entire upload schema. There is no other
            code path that ships data to the cloud backend.
          </p>
        </section>

        <section>
          <h2>What cloud sync never uploads</h2>
          <ul>
            {NEVER_SENT.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p>
            The sync function has no parameter for them. To send a prompt body to the cloud, you
            would have to fork BurnLens and add a field — which is to say, the privacy guarantee is
            a structural property of the code, not a policy promise.
          </p>
        </section>

        <section>
          <h2>Tags: what you choose to attach</h2>
          <p>
            Tag values you set (via <code>X-BurnLens-Tag-Feature: checkout</code> or{" "}
            <code>BURNLENS_TAG_TEAM=payments</code>) <em>are</em> uploaded by cloud sync — they are
            the rollup dimensions for the team dashboard. Treat tag values like log labels: don&apos;t
            put PII or secrets in them. The supported tag keys are <code>feature</code>,{" "}
            <code>team</code>, and <code>customer</code>; everything else stays in the local
            database but is not forwarded to the cloud.
          </p>
        </section>

        <section>
          <h2>Running entirely offline</h2>
          <p>
            Cloud sync is opt-in. If you never run <code>burnlens login</code>:
          </p>
          <ul>
            <li>No API key is configured</li>
            <li>The sync background task never starts</li>
            <li>No outbound connection to <code>api.burnlens.app</code> is ever opened</li>
            <li>
              The local dashboard at <code>localhost:8420/ui</code>, CLI commands (
              <code>top</code>, <code>report</code>, <code>scan</code>, <code>analyze</code>), and
              SQLite database all work normally
            </li>
          </ul>
        </section>

        <section>
          <h2>License and source</h2>
          <p>
            The proxy, CLI, dashboard, scan readers, and cost engine are{" "}
            <a
              href="https://github.com/sairintechnologycom/burnlens/blob/main/LICENSE"
              target="_blank"
              rel="noopener noreferrer"
            >
              Apache-2.0
            </a>
            . You can audit, fork, self-host, or run BurnLens entirely offline. Source on{" "}
            <a
              href="https://github.com/sairintechnologycom/burnlens"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub
            </a>
            . The cloud ingest backend that receives opt-in sync batches is not open source — it is
            a managed service for the hosted dashboard at <code>burnlens.app</code>.
          </p>
        </section>

        <section>
          <h2>Reporting a vulnerability</h2>
          <p>
            Please email <a href="mailto:security@burnlens.app">security@burnlens.app</a> with
            details and a proof of concept. We aim to acknowledge within 2 business days. Please do
            not file public GitHub issues for security reports.
          </p>
        </section>

        <section>
          <h2>FAQ</h2>
          <p>
            <strong>Does BurnLens see my prompts?</strong> BurnLens reads the request body locally
            to extract the model name and to forward it to the provider. Prompt content is written
            only to the local SQLite database. Cloud sync, if enabled, uploads counts and hashes —
            never prompt text.
          </p>
          <p>
            <strong>Can the BurnLens cloud see who my customers are?</strong> Only if you put
            customer identifiers into the <code>X-BurnLens-Tag-Customer</code> header. By default,
            no customer data is in any field that gets uploaded.
          </p>
          <p>
            <strong>What about provider API keys?</strong> They live in your environment and are
            forwarded in the <code>Authorization</code> header upstream. BurnLens does not log,
            persist, or upload them.
          </p>
          <p>
            <strong>Is BurnLens SOC 2 / HIPAA / ISO 27001 certified?</strong> Not today. The
            hosted backend follows standard cloud-security practices (encrypted transport,
            scoped API keys, principle of least privilege). For regulated workloads, run BurnLens
            self-hosted with cloud sync disabled — that keeps every byte of LLM traffic inside your
            own infrastructure.
          </p>
        </section>

        <section>
          <h2>Related</h2>
          <p>
            <Link href="/privacy" className="legal-nav-link">Privacy Policy</Link>
            {" · "}
            <Link href="/terms" className="legal-nav-link">Terms &amp; Conditions</Link>
            {" · "}
            <Link href="/scan" className="legal-nav-link">burnlens scan</Link>
            {" · "}
            <Link href="/" className="legal-nav-link">Back to homepage</Link>
          </p>
        </section>
      </main>
    </div>
  );
}

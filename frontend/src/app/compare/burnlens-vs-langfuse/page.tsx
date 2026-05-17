import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "BurnLens vs Langfuse — LLM Cost Tracking with Hard-Cap Budgets (2026)",
  description: "Langfuse reports LLM cost. BurnLens enforces it — open-source proxy that returns HTTP 429 before the upstream call when your daily budget is hit.",
  alternates: { canonical: "/compare/burnlens-vs-langfuse" },
  openGraph: {
    title: "BurnLens vs Langfuse — LLM Cost Tracking with Hard Caps",
    description: "Langfuse reports cost. BurnLens enforces cost. Use them together, or use BurnLens alone.",
    url: "https://burnlens.app/compare/burnlens-vs-langfuse",
    siteName: "BurnLens",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: "BurnLens vs Langfuse",
    description: "Observability vs enforcement — they solve different halves of LLM cost control.",
  },
};

const faqStructuredData = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Is BurnLens a replacement for Langfuse?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Not entirely. Langfuse is a full LLM observability platform — tracing, evaluations, prompt management, and cost reporting. BurnLens is focused on FinOps: tracking and enforcing AI spend. Many teams use both; Langfuse for trace and quality, BurnLens for budget enforcement.",
      },
    },
    {
      "@type": "Question",
      name: "Can Langfuse stop a runaway agent from spending $10,000?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. Langfuse is post-hoc — it tracks costs after each request and can alert you, but it does not sit in the request path and cannot block calls. BurnLens runs as a proxy and returns HTTP 429 before the upstream call when a daily cap is hit.",
      },
    },
    {
      "@type": "Question",
      name: "Does BurnLens do tracing like Langfuse?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "BurnLens captures per-request metadata — model, tokens, cost, latency, tags — but does not build multi-step trace trees, manage prompts, or run evaluations. For application-level tracing and eval, pair BurnLens with Langfuse or use Langfuse alone.",
      },
    },
    {
      "@type": "Question",
      name: "Can I use BurnLens and Langfuse together?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. Point your SDK at BurnLens (localhost:8420) for cost enforcement, and instrument your app with Langfuse SDK for tracing. The two run in parallel without conflict.",
      },
    },
  ],
};

export default function CompareLangfuse() {
  return (
    <div className="legal-page">
      <script type="application/ld+json">{JSON.stringify(faqStructuredData)}</script>

      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>BurnLens vs Langfuse</h1>
        <p className="legal-updated">Observability vs FinOps enforcement · Updated May 2026</p>

        <section>
          <h2>TL;DR</h2>
          <p>
            <strong>Langfuse</strong> is an LLM observability platform: tracing, prompt versioning, evaluations, and
            cost reporting at the observability layer.
            <strong> BurnLens</strong> is a FinOps proxy: cost tracking and hard-cap budgets enforced at the
            infrastructure layer. Langfuse tells you what you spent. BurnLens controls what you <em>can</em> spend.
            They are complements more than competitors.
          </p>
        </section>

        <section>
          <h2>Feature comparison</h2>
          <table className="lp-compare-table">
            <thead>
              <tr><th></th><th>BurnLens</th><th>Langfuse</th></tr>
            </thead>
            <tbody>
              <tr><td>Sits in the request path</td><td>Yes — HTTP proxy</td><td>No — SDK observer</td></tr>
              <tr><td>Hard-cap budgets (blocks upstream call)</td><td>Yes — HTTP 429</td><td>No — reports and alerts only</td></tr>
              <tr><td>Install method</td><td><code>pip install burnlens</code>, one env var</td><td>SDK integration in every call site</td></tr>
              <tr><td>Cost attribution</td><td>Per request via headers</td><td>Per trace via SDK metadata</td></tr>
              <tr><td>Trace tree visualization</td><td>No</td><td>Yes — full nested trace</td></tr>
              <tr><td>Prompt management</td><td>No</td><td>Yes — versioned prompts</td></tr>
              <tr><td>LLM-as-judge evaluations</td><td>No</td><td>Yes</td></tr>
              <tr><td>Local-first storage</td><td>Yes — SQLite</td><td>Requires Postgres + ClickHouse</td></tr>
              <tr><td>Self-hosted complexity</td><td>One pip install</td><td>Docker Compose with 4 services</td></tr>
            </tbody>
          </table>
        </section>

        <section>
          <h2>When to pick BurnLens</h2>
          <p><strong>You need to stop spend, not just measure it.</strong> Langfuse&apos;s cost analytics are
          comprehensive, but they observe — they do not enforce. If a customer&apos;s API key triggers a loop that
          burns $5,000 overnight, Langfuse will show you the spike the next morning. BurnLens returns 429 at
          $50.01 if the daily cap is $50.</p>

          <p><strong>You want zero code changes.</strong> Langfuse requires wrapping every LLM call with its SDK or
          using its OpenTelemetry instrumentation. BurnLens needs one environment variable; your existing SDK code
          is untouched.</p>

          <p><strong>You don&apos;t want to operate Postgres + ClickHouse.</strong> Langfuse self-hosting requires
          a real database stack. BurnLens runs on local SQLite; the optional cloud sync is a single Railway service.</p>
        </section>

        <section>
          <h2>When to pick Langfuse</h2>
          <p><strong>You need application-level tracing.</strong> Multi-step agents, RAG pipelines, and tool-using
          workflows benefit from Langfuse&apos;s trace trees. BurnLens sees individual HTTP requests, not the
          parent-child structure of an agent step graph.</p>

          <p><strong>You need prompt and evaluation tooling.</strong> Versioned prompts, A/B tests, LLM-as-judge
          scoring, dataset management — Langfuse handles these. BurnLens does not.</p>
        </section>

        <section>
          <h2>Use them together</h2>
          <p>The two tools compose cleanly:</p>
          <pre style={{ background: "var(--surface-2, #111)", padding: "1rem", borderRadius: 8, overflowX: "auto" }}>
            <code>{`# 1. BurnLens enforces the budget
pip install burnlens
burnlens start
export OPENAI_BASE_URL=http://localhost:8420/proxy/openai/v1

# 2. Langfuse instruments the app
pip install langfuse
# wrap your LLM calls with @observe() — they route through BurnLens automatically`}</code>
          </pre>
          <p>Each LLM call passes through BurnLens (cost tracked + capped) and is observed by Langfuse (traced +
          evaluated). No coupling between the two tools; either can be removed without affecting the other.</p>
        </section>

        <section>
          <h2>Get started</h2>
          <p>
            <Link href="/setup?intent=register" className="legal-nav-link">Start the free trial</Link>
            {" · "}
            <a href="https://github.com/sairintechnologycom/burnlens" target="_blank" rel="noopener noreferrer" className="legal-nav-link">Star on GitHub</a>
            {" · "}
            <Link href="/compare/burnlens-vs-helicone" className="legal-nav-link">Compare to Helicone</Link>
            {" · "}
            <Link href="/compare/burnlens-vs-litellm" className="legal-nav-link">Compare to LiteLLM</Link>
            {" · "}
            <Link href="/" className="legal-nav-link">Back to homepage</Link>
          </p>
        </section>
      </main>
    </div>
  );
}

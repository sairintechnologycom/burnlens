import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "BurnLens vs LiteLLM — Simpler LLM Cost Tracking Alternative (2026)",
  description: "LiteLLM is a full LLM gateway with YAML config and request rewriting. BurnLens is a transparent FinOps proxy: one env var, zero payload modification, and hard-cap budgets that return 429 before the upstream call. Compared on install, latency, and cost control.",
  alternates: { canonical: "/compare/burnlens-vs-litellm" },
  openGraph: {
    title: "BurnLens vs LiteLLM — Simpler LLM Cost Tracking Alternative",
    description: "LiteLLM rewrites requests through a gateway. BurnLens is a transparent proxy with zero payload modification and hard-cap budgets.",
    url: "https://burnlens.app/compare/burnlens-vs-litellm",
    siteName: "BurnLens",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: "BurnLens vs LiteLLM — Simpler Alternative",
    description: "Transparent proxy, zero payload rewrites, hard-cap budgets per API key.",
  },
};

const faqStructuredData = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What is the difference between BurnLens and LiteLLM?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "LiteLLM is a unified LLM gateway that rewrites requests into a single OpenAI-compatible format. BurnLens is a transparent FinOps proxy that forwards requests unmodified and only logs cost. Different design philosophies: LiteLLM normalizes; BurnLens observes.",
      },
    },
    {
      "@type": "Question",
      name: "Does BurnLens require config files like LiteLLM?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. BurnLens works with one environment variable per provider. No YAML, no model aliases, no router config. Your existing SDK code routes through automatically.",
      },
    },
    {
      "@type": "Question",
      name: "Can BurnLens enforce per-user or per-customer budgets like LiteLLM?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes — and at the API-key level too. BurnLens issues per-key daily dollar caps that return HTTP 429 before the upstream call. LiteLLM's budget controls live in its hosted database tier; BurnLens enforcement runs locally with no external dependency.",
      },
    },
    {
      "@type": "Question",
      name: "Which has lower proxy overhead, BurnLens or LiteLLM?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "BurnLens targets under 20ms overhead because it does not deserialize or rewrite request bodies — it forwards bytes and logs the usage block from the response. LiteLLM's normalization layer adds more processing on every call.",
      },
    },
  ],
};

export default function CompareLiteLLM() {
  return (
    <div className="legal-page">
      <script type="application/ld+json">{JSON.stringify(faqStructuredData)}</script>

      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>BurnLens vs LiteLLM</h1>
        <p className="legal-updated">A simpler LLM cost tracking alternative · Updated May 2026</p>

        <section>
          <h2>TL;DR</h2>
          <p>
            LiteLLM and BurnLens both sit between your app and AI providers, but they solve different problems.
            <strong> LiteLLM is a gateway</strong> — it normalizes every provider into one OpenAI-compatible API,
            with YAML config, model routing, and request rewriting.
            <strong> BurnLens is a FinOps proxy</strong> — it forwards your requests unmodified and only watches
            cost. If you already use the OpenAI, Anthropic, and Google SDKs directly and just want to see and cap
            spend, BurnLens is the simpler choice.
          </p>
        </section>

        <section>
          <h2>Feature comparison</h2>
          <table className="lp-compare-table">
            <thead>
              <tr><th></th><th>BurnLens</th><th>LiteLLM</th></tr>
            </thead>
            <tbody>
              <tr><td>Primary purpose</td><td>Cost tracking + budgets</td><td>Provider normalization gateway</td></tr>
              <tr><td>Config required</td><td>None — one env var</td><td>YAML / Python config</td></tr>
              <tr><td>Payload modification</td><td>None — transparent passthrough</td><td>Rewrites requests into OpenAI format</td></tr>
              <tr><td>Proxy overhead target</td><td>&lt; 20ms</td><td>~40-100ms with router</td></tr>
              <tr><td>Hard caps before upstream call</td><td>Yes — HTTP 429 at limit</td><td>Hosted tier only</td></tr>
              <tr><td>Multi-provider</td><td>OpenAI, Anthropic, Google, Azure, Bedrock, Groq</td><td>100+ providers</td></tr>
              <tr><td>Streaming passthrough (SSE chunks unbuffered)</td><td>Yes</td><td>Yes, with re-serialization</td></tr>
              <tr><td>Local SQLite, no external DB</td><td>Yes</td><td>Requires Postgres for spend tracking</td></tr>
              <tr><td>Per-customer attribution via headers</td><td>Yes — <code>X-BurnLens-Tag-*</code></td><td>Yes — virtual keys</td></tr>
              <tr><td>Free self-hosted</td><td>Unlimited</td><td>Unlimited (OSS tier)</td></tr>
            </tbody>
          </table>
        </section>

        <section>
          <h2>When BurnLens is the right choice</h2>
          <p><strong>1. You don&apos;t want a gateway.</strong> Your code already uses the OpenAI SDK for OpenAI and
          the Anthropic SDK for Claude. You don&apos;t want to rewrite call sites to a unified <code>completion()</code>
          function. BurnLens lets you keep your existing code and just observe cost.</p>

          <p><strong>2. Latency matters.</strong> BurnLens does not parse, normalize, or re-serialize request bodies.
          It forwards bytes directly and reads the <code>usage</code> field from the response only. Measured overhead
          stays under 20ms on the critical path.</p>

          <p><strong>3. You need hard caps without operational overhead.</strong> Set a daily dollar cap per API key
          in <code>burnlens.yaml</code> or via CLI. At 100% of cap, the proxy returns HTTP 429 <em>before</em> the
          request reaches the provider. No Postgres, no hosted control plane, no extra service to monitor.</p>

          <p><strong>4. Prompts must not leave your machine.</strong> Compliance teams reject any architecture that
          routes prompts through a third party. BurnLens runs on <code>localhost:8420</code> and stores in local
          SQLite by default; cloud sync is opt-in and only ships anonymized token counts.</p>
        </section>

        <section>
          <h2>When LiteLLM is the right choice</h2>
          <p>If you need to swap models across 100+ providers at runtime, do prompt-level fallbacks, or unify your
          codebase around one <code>completion()</code> call — LiteLLM&apos;s router is built for that and BurnLens
          is not. The two tools also compose: run BurnLens on <code>localhost:8420</code> as the egress proxy,
          and point LiteLLM&apos;s provider base URLs at it. You get LiteLLM&apos;s routing logic with BurnLens&apos;s
          cost enforcement.</p>
        </section>

        <section>
          <h2>Migration path: LiteLLM → BurnLens</h2>
          <p>If you only used LiteLLM for cost tracking and not for routing, the migration is three commands:</p>
          <pre style={{ background: "var(--surface-2, #111)", padding: "1rem", borderRadius: 8, overflowX: "auto" }}>
            <code>{`pip install burnlens
burnlens start
# Point your existing SDK back at the provider's URL, via BurnLens:
export OPENAI_BASE_URL=http://localhost:8420/proxy/openai/v1
export ANTHROPIC_BASE_URL=http://localhost:8420/proxy/anthropic`}</code>
          </pre>
          <p>You can deprecate the LiteLLM YAML and Postgres deployment. Tag attribution moves from LiteLLM virtual
          keys to BurnLens <code>X-BurnLens-Tag-Feature</code> / <code>-Team</code> / <code>-Customer</code> headers.</p>
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
            <Link href="/" className="legal-nav-link">Back to homepage</Link>
          </p>
        </section>
      </main>
    </div>
  );
}

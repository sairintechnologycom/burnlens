import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "BurnLens vs Helicone — Open-Source LLM Cost Tracking Alternative (2026)",
  description: "Helicone entered maintenance mode in 2025. BurnLens is the actively maintained open-source LLM cost tracking proxy with hard-cap budgets, local-first storage, and multi-provider support across OpenAI, Anthropic, Google, Azure, Bedrock, and Groq.",
  alternates: { canonical: "/compare/burnlens-vs-helicone" },
  openGraph: {
    title: "BurnLens vs Helicone — Open-Source LLM Cost Tracking Alternative",
    description: "Helicone is in maintenance mode. BurnLens is the actively maintained alternative with hard-cap budgets and local-first storage.",
    url: "https://burnlens.app/compare/burnlens-vs-helicone",
    siteName: "BurnLens",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: "BurnLens vs Helicone — Open-Source Alternative",
    description: "Helicone is in maintenance mode. BurnLens is the actively maintained, local-first LLM cost tracking proxy.",
  },
};

const faqStructuredData = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Is Helicone still actively maintained?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Helicone announced it entered maintenance mode in 2025. New features and provider integrations are no longer being added. For teams starting fresh, an actively maintained alternative like BurnLens is recommended.",
      },
    },
    {
      "@type": "Question",
      name: "What is the best open-source alternative to Helicone?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "BurnLens is the closest one-line drop-in alternative. Install with pip, set one environment variable, and every OpenAI, Anthropic, Google, Azure, Bedrock, and Groq call is tracked with cost attribution and hard-cap budget enforcement.",
      },
    },
    {
      "@type": "Question",
      name: "Can I migrate my Helicone integration to BurnLens?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. Both tools work via base URL redirection. Replace your Helicone proxy URL with localhost:8420 and your existing SDK code continues to work unchanged.",
      },
    },
    {
      "@type": "Question",
      name: "Does BurnLens send my prompts to a third party?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. BurnLens is local-first. Prompts and responses pass through your machine to the AI provider directly. Only anonymized token counts and costs are optionally synced to the cloud dashboard.",
      },
    },
  ],
};

export default function CompareHelicone() {
  return (
    <div className="legal-page">
      <script type="application/ld+json">{JSON.stringify(faqStructuredData)}</script>

      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>BurnLens vs Helicone</h1>
        <p className="legal-updated">An open-source LLM cost tracking alternative · Updated May 2026</p>

        <section>
          <h2>TL;DR</h2>
          <p>
            <strong>Helicone entered maintenance mode in 2025</strong> — new features and integrations are paused.
            If you are evaluating an LLM observability proxy in 2026, you want a tool that is still being shipped.
            <strong> BurnLens</strong> is the closest drop-in alternative: open-source, one-env-var install,
            and adds two capabilities Helicone never had — <em>hard-cap budget enforcement before the upstream call</em>
            and <em>local-first storage</em> so prompts never leave your machine.
          </p>
        </section>

        <section>
          <h2>Feature comparison</h2>
          <table className="lp-compare-table">
            <thead>
              <tr><th></th><th>BurnLens</th><th>Helicone</th></tr>
            </thead>
            <tbody>
              <tr><td>Actively maintained (2026)</td><td>Yes</td><td>Maintenance mode</td></tr>
              <tr><td>Open source license</td><td>Apache 2.0</td><td>Apache 2.0 (frozen)</td></tr>
              <tr><td>Install method</td><td><code>pip install burnlens</code></td><td>Docker / hosted proxy</td></tr>
              <tr><td>Local-first (prompts never leave machine)</td><td>Yes</td><td>No — proxies through Helicone Cloud by default</td></tr>
              <tr><td>Hard-cap budgets (returns 429 before upstream call)</td><td>Yes</td><td>No — alerts only, post-call</td></tr>
              <tr><td>Per-customer cost attribution via headers</td><td>Yes</td><td>Yes</td></tr>
              <tr><td>Multi-provider (OpenAI, Anthropic, Google, Azure, Bedrock, Groq)</td><td>Yes</td><td>Partial</td></tr>
              <tr><td>Local CLI dashboard, no signup required</td><td>Yes</td><td>No</td></tr>
              <tr><td>Free tier</td><td>Unlimited self-hosted</td><td>10K requests/mo on hosted</td></tr>
            </tbody>
          </table>
        </section>

        <section>
          <h2>Why teams migrate from Helicone to BurnLens</h2>
          <p><strong>1. Hard caps actually stop spend.</strong> Helicone alerts you after a runaway loop has already cost
          $4,000. BurnLens registers a daily dollar limit per API key and returns HTTP 429 <em>before</em> the request
          is forwarded upstream — your bill literally cannot exceed the cap.</p>

          <p><strong>2. Prompts stay on your machine.</strong> Helicone&apos;s default deployment proxies your traffic
          through their cloud. BurnLens runs on <code>localhost:8420</code>. The full request body never leaves your
          infrastructure; only anonymized usage counts sync to the optional cloud dashboard.</p>

          <p><strong>3. New providers ship in days, not never.</strong> Adding a provider to BurnLens is one new file
          in <code>burnlens/providers/</code> plus a pricing JSON — Groq, Bedrock, and Azure all shipped this way.
          Helicone&apos;s frozen integration list has not expanded since maintenance mode began.</p>

          <p><strong>4. CLI-native workflow.</strong> <code>burnlens top</code> shows live spend in your terminal.
          <code>burnlens report</code> reconciles against your provider invoice. <code>burnlens analyze</code> finds
          waste — prompt bloat, duplicate calls, over-spec models. None of this requires a web login.</p>
        </section>

        <section>
          <h2>How to migrate from Helicone in 3 commands</h2>
          <pre style={{ background: "var(--surface-2, #111)", padding: "1rem", borderRadius: 8, overflowX: "auto" }}>
            <code>{`pip install burnlens
burnlens start
export OPENAI_BASE_URL=http://localhost:8420/proxy/openai/v1`}</code>
          </pre>
          <p>Your existing OpenAI SDK code now routes through BurnLens. Repeat with
          <code> ANTHROPIC_BASE_URL</code> for Claude, or use <code>burnlens.patch()</code> for Google AI.
          See the <a href="https://github.com/sairintechnologycom/burnlens#readme" target="_blank" rel="noopener noreferrer">install guide</a> for full provider coverage.</p>
        </section>

        <section>
          <h2>When Helicone is still the right choice</h2>
          <p>Helicone&apos;s hosted dashboard is more mature for read-only observability across very large teams that
          already invested in its custom properties API. If you have an existing Helicone deployment that does not
          need new features, there is no urgency to migrate. For new projects in 2026, BurnLens is the safer bet.</p>
        </section>

        <section>
          <h2>Get started</h2>
          <p>
            <Link href="/setup?intent=register" className="legal-nav-link">Start the free trial</Link>
            {" · "}
            <a href="https://github.com/sairintechnologycom/burnlens" target="_blank" rel="noopener noreferrer" className="legal-nav-link">Star on GitHub</a>
            {" · "}
            <Link href="/" className="legal-nav-link">Back to homepage</Link>
          </p>
        </section>
      </main>
    </div>
  );
}

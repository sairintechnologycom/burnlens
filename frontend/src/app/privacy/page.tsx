import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy — BurnLens",
  description: "How BurnLens and Sairin Technology handle your data.",
  alternates: { canonical: "/privacy" },
  openGraph: {
    title: "Privacy Policy — BurnLens",
    description: "How BurnLens and Sairin Technology handle your data.",
    url: "https://burnlens.app/privacy",
    siteName: "BurnLens",
    type: "article",
  },
};

export default function PrivacyPage() {
  return (
    <div className="legal-page">
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>Privacy Policy</h1>
        <p className="legal-updated">Last updated: April 17, 2026</p>

        <section>
          <h2>1. Who We Are</h2>
          <p>
            BurnLens is operated by <strong>Sairin Technology</strong> (<a href="https://sairintechnology.com" target="_blank" rel="noopener noreferrer">sairintechnology.com</a>).
            This policy explains what data we collect, how we use it, and your rights.
          </p>
        </section>

        <section>
          <h2>2. Data We Do NOT Collect</h2>
          <p>We are designed to be privacy-first. We never collect or store:</p>
          <ul>
            <li>Your LLM prompts or completions</li>
            <li>Your application code or business logic</li>
            <li>Your AI provider API keys (these pass through the local proxy and are never sent to our servers)</li>
            <li>PII from request or response bodies</li>
          </ul>
        </section>

        <section>
          <h2>3. Local Proxy Data (Your Machine Only)</h2>
          <p>
            The open-source BurnLens proxy stores the following data locally in SQLite at{" "}
            <code>~/.burnlens/burnlens.db</code>. This data never leaves your machine unless you
            explicitly enable cloud sync:
          </p>
          <ul>
            <li>Model name, provider, timestamp</li>
            <li>Token counts (input, output, cached)</li>
            <li>Calculated cost in USD</li>
            <li>SHA-256 hash of system prompt (for duplicate detection — hash only, not content)</li>
            <li>Custom tags you add via <code>X-BurnLens-Tag-*</code> headers</li>
          </ul>
        </section>

        <section>
          <h2>4. Cloud Sync Data (Sent to Our Servers)</h2>
          <p>
            When cloud sync is enabled, BurnLens sends pseudonymous metadata batches every 60 seconds to our
            Railway backend at <code>api.burnlens.app</code>. Each record contains:
          </p>
          <ul>
            <li>Workspace API key in the authenticated request header (for routing to your workspace)</li>
            <li>Provider, model, timestamp</li>
            <li>Token counts and cost in USD</li>
            <li>Tag values you provided for feature, team, customer, and key label</li>
            <li>Workspace-keyed HMAC-SHA256 prompt fingerprint</li>
          </ul>
          <p>Prompt content, completion content, and raw request/response bodies are never synced.</p>
        </section>

        <section>
          <h2>5. Account Data</h2>
          <p>
            When you create a cloud account at burnlens.app, we store:
          </p>
          <ul>
            <li>Email address</li>
            <li>Hashed password (bcrypt)</li>
            <li>Workspace name, API-key hashes, and key suffixes used for identification</li>
            <li>Paddle customer ID (for billing)</li>
            <li>Plan and subscription status</li>
          </ul>
        </section>

        <section>
          <h2>6. Payment Data</h2>
          <p>
            Payments are processed by <strong>Paddle</strong>. We do not store credit card numbers
            or full payment details. Paddle shares billing identifiers, transaction details, and subscription status with us.
            Sairin Technology (<a href="https://sairintechnology.com" target="_blank" rel="noopener noreferrer">sairintechnology.com</a>) appears
            as the merchant on your statement.
          </p>
        </section>

        <section>
          <h2>7. Cookies &amp; Tracking</h2>
          <p>
            The cloud dashboard uses session cookies for authentication and Plausible for
            privacy-focused product analytics. We do not use third-party advertising trackers or fingerprinting.
          </p>
        </section>

        <section>
          <h2>8. Service Providers</h2>
          <p>
            We use Vercel for the website, Railway for hosted application infrastructure,
            Paddle for billing, SendGrid for transactional email, and Plausible for product analytics.
            These providers process only the data required to deliver their service.
          </p>
        </section>

        <section>
          <h2>9. Data Retention</h2>
          <ul>
            <li><strong>Free plan:</strong> 7 days of cloud sync history</li>
            <li><strong>Cloud plan:</strong> 90 days</li>
            <li><strong>Teams plan:</strong> 365 days</li>
            <li><strong>Enterprise:</strong> Up to 10 years</li>
          </ul>
          <p>On account deletion, all cloud data is purged within 30 days.</p>
        </section>

        <section>
          <h2>10. Your Rights</h2>
          <p>You may at any time:</p>
          <ul>
            <li>Request a copy of your stored data</li>
            <li>Request deletion of your account and associated data</li>
            <li>Disable cloud sync (your local data is unaffected)</li>
            <li>Export your data from the dashboard</li>
          </ul>
        </section>

        <section>
          <h2>11. Contact</h2>
          <p>
            Privacy questions:{" "}
            <a href="mailto:contact@sairintechnology.com">contact@sairintechnology.com</a>.
          </p>
        </section>
      </main>

      <footer className="legal-footer">
        <Link href="/terms">Terms &amp; Conditions</Link>
        <span>·</span>
        <Link href="/refund">Refund Policy</Link>
        <span>·</span>
        <Link href="/">Home</Link>
        <div className="legal-footer-company">
          © 2026 Sairin Technology · <a href="https://sairintechnology.com" target="_blank" rel="noopener noreferrer">sairintechnology.com</a>
        </div>
      </footer>
    </div>
  );
}

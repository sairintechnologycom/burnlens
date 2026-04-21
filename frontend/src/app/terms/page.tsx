import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms & Conditions — BurnLens",
  description: "Terms and conditions for using BurnLens and burnlens.app.",
  alternates: { canonical: "/terms" },
  openGraph: {
    title: "Terms & Conditions — BurnLens",
    description: "Terms and conditions for using BurnLens and burnlens.app.",
    url: "https://burnlens.app/terms",
    siteName: "BurnLens",
    type: "article",
  },
};

export default function TermsPage() {
  return (
    <div className="legal-page">
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>Terms &amp; Conditions</h1>
        <p className="legal-updated">Last updated: April 17, 2026</p>

        <section>
          <h2>1. About Us</h2>
          <p>
            BurnLens is a product of <strong>Sairin Technology</strong> (<a href="https://sairintechnology.com" target="_blank" rel="noopener noreferrer">sairintechnology.com</a>).
            By using burnlens.app or any associated services, you agree to these Terms &amp; Conditions.
          </p>
        </section>

        <section>
          <h2>2. Services</h2>
          <p>
            BurnLens provides an open-source LLM cost monitoring proxy and a cloud dashboard service
            at <a href="https://burnlens.app">burnlens.app</a>. The open-source proxy is free to use
            under the MIT License. Cloud features require a paid subscription.
          </p>
        </section>

        <section>
          <h2>3. User Accounts</h2>
          <p>
            You are responsible for maintaining the confidentiality of your account credentials and API keys.
            You agree not to share your <code>bl_live_xxx</code> API key with unauthorized parties.
            Sairin Technology is not liable for unauthorized access resulting from your failure to secure your credentials.
          </p>
        </section>

        <section>
          <h2>4. Acceptable Use</h2>
          <p>You agree not to:</p>
          <ul>
            <li>Reverse-engineer or resell BurnLens cloud services</li>
            <li>Use the service to monitor AI calls on behalf of third parties without their consent</li>
            <li>Attempt to circumvent plan limits or billing controls</li>
            <li>Transmit malicious content through the proxy</li>
          </ul>
        </section>

        <section>
          <h2>5. Data &amp; Privacy</h2>
          <p>
            The local proxy stores data exclusively on your machine. Cloud sync transmits anonymised
            metadata only (token counts, cost, model, tags) — never prompt content or completions.
            See our <Link href="/privacy">Privacy Policy</Link> for full details.
          </p>
        </section>

        <section>
          <h2>6. Subscriptions &amp; Billing</h2>
          <p>
            Paid plans are billed monthly via Stripe. Sairin Technology (sairintechnology.com) will
            appear as the merchant on your bank or card statement. Prices are listed in USD.
            See our <Link href="/refund">Refund Policy</Link> for cancellation and refund terms.
          </p>
        </section>

        <section>
          <h2>7. Service Availability</h2>
          <p>
            We aim for high availability but do not guarantee uninterrupted access to cloud services.
            Planned maintenance will be announced in advance where possible. The open-source proxy
            operates independently and is not affected by cloud service outages.
          </p>
        </section>

        <section>
          <h2>8. Limitation of Liability</h2>
          <p>
            To the maximum extent permitted by law, Sairin Technology shall not be liable for any
            indirect, incidental, or consequential damages arising from your use of BurnLens,
            including but not limited to lost revenue or data loss. Our total liability shall not
            exceed the amount you paid us in the 30 days preceding the claim.
          </p>
        </section>

        <section>
          <h2>9. Intellectual Property</h2>
          <p>
            The open-source BurnLens proxy is MIT-licensed. The BurnLens name, logo, and cloud
            dashboard UI are the intellectual property of Sairin Technology and may not be reproduced
            without written permission.
          </p>
        </section>

        <section>
          <h2>10. Changes to Terms</h2>
          <p>
            We may update these Terms at any time. Continued use of the service after changes are
            posted constitutes acceptance. We will notify active subscribers of material changes
            via email.
          </p>
        </section>

        <section>
          <h2>11. Governing Law</h2>
          <p>
            These Terms are governed by the laws of the jurisdiction in which Sairin Technology is
            registered. Any disputes shall be resolved through binding arbitration before resorting
            to litigation.
          </p>
        </section>

        <section>
          <h2>12. Contact</h2>
          <p>
            For questions about these Terms, contact us at{" "}
            <a href="mailto:contact@sairintechnology.com">contact@sairintechnology.com</a>.
          </p>
        </section>
      </main>

      <footer className="legal-footer">
        <Link href="/privacy">Privacy Policy</Link>
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

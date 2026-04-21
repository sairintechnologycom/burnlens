import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Refund Policy — BurnLens",
  description: "BurnLens refund and cancellation policy.",
  alternates: { canonical: "/refund" },
  openGraph: {
    title: "Refund Policy — BurnLens",
    description: "BurnLens refund and cancellation policy.",
    url: "https://burnlens.app/refund",
    siteName: "BurnLens",
    type: "article",
  },
};

export default function RefundPage() {
  return (
    <div className="legal-page">
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>Refund Policy</h1>
        <p className="legal-updated">Last updated: April 17, 2026</p>

        <section>
          <h2>1. Overview</h2>
          <p>
            BurnLens is operated by <strong>Sairin Technology</strong> (
            <a href="https://sairintechnology.com" target="_blank" rel="noopener noreferrer">sairintechnology.com</a>).
            We want you to be satisfied with your subscription. This policy explains when refunds
            are available and how to request them.
          </p>
        </section>

        <section>
          <h2>2. Free Trial</h2>
          <p>
            Cloud and Teams plans include a free trial period. You will not be charged until the
            trial ends. You may cancel at any time during the trial with no charge.
          </p>
        </section>

        <section>
          <h2>3. Cancellation</h2>
          <p>
            You may cancel your subscription at any time from the billing portal in your dashboard
            settings. Cancellation takes effect at the end of the current billing period — you
            retain access to paid features until then. We do not offer prorated refunds for unused
            days in a billing period.
          </p>
        </section>

        <section>
          <h2>4. Refund Eligibility</h2>
          <p>Refunds are available in the following circumstances:</p>
          <ul>
            <li>
              <strong>Within 7 days of first charge:</strong> If you are unsatisfied with the
              service after your trial converts to a paid plan, contact us within 7 days of the
              first charge for a full refund.
            </li>
            <li>
              <strong>Service outage:</strong> If BurnLens cloud services are unavailable for more
              than 72 consecutive hours in a billing period, you are eligible for a prorated credit
              for the affected days.
            </li>
            <li>
              <strong>Duplicate charge:</strong> If you are charged more than once for the same
              billing period due to a system error, contact us and we will refund the duplicate
              charge immediately.
            </li>
          </ul>
        </section>

        <section>
          <h2>5. Non-Refundable Circumstances</h2>
          <p>Refunds are not available for:</p>
          <ul>
            <li>Unused subscription days after cancellation (unless within the 7-day window)</li>
            <li>Downgrading from a higher plan to a lower plan mid-cycle</li>
            <li>Account suspension due to violation of our Terms &amp; Conditions</li>
            <li>Changes in your business needs or usage patterns</li>
          </ul>
        </section>

        <section>
          <h2>6. How to Request a Refund</h2>
          <p>To request a refund:</p>
          <ol>
            <li>Email <a href="mailto:contact@sairintechnology.com">contact@sairintechnology.com</a></li>
            <li>Include your account email and the reason for the refund request</li>
            <li>We will respond within 2 business days</li>
            <li>Approved refunds are processed via Stripe and typically appear within 5–10 business days</li>
          </ol>
        </section>

        <section>
          <h2>7. Digital Product Notice</h2>
          <p>
            BurnLens cloud plans are digital subscription services. Access to the service begins
            immediately upon payment. By subscribing, you acknowledge that the right of withdrawal
            for digital content may not apply once the service has been accessed, subject to
            applicable consumer protection laws in your jurisdiction.
          </p>
        </section>

        <section>
          <h2>8. Enterprise Plans</h2>
          <p>
            Enterprise plan refund terms are governed by your individual service agreement with
            Sairin Technology. Contact <a href="mailto:contact@sairintechnology.com">contact@sairintechnology.com</a> for details.
          </p>
        </section>

        <section>
          <h2>9. Contact</h2>
          <p>
            Billing questions:{" "}
            <a href="mailto:contact@sairintechnology.com">contact@sairintechnology.com</a>.
          </p>
        </section>
      </main>

      <footer className="legal-footer">
        <Link href="/terms">Terms &amp; Conditions</Link>
        <span>·</span>
        <Link href="/privacy">Privacy Policy</Link>
        <span>·</span>
        <Link href="/">Home</Link>
        <div className="legal-footer-company">
          © 2026 Sairin Technology · <a href="https://sairintechnology.com" target="_blank" rel="noopener noreferrer">sairintechnology.com</a>
        </div>
      </footer>
    </div>
  );
}

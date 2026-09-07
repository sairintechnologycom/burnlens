import Link from "next/link";
import type { Metadata } from "next";
import { FunnelPageview } from "@/components/FunnelPageview";
import { FUNNEL } from "@/lib/analytics";
import { PRODUCT_CONTRACT as C } from "@/lib/productContract";

export const metadata: Metadata = {
  title: "AI project economics for software agencies · BurnLens",
  description:
    "Know what each AI-powered client project actually costs. Spend, accepted outcomes, and missing attribution — locally first, then shared with the team.",
  alternates: { canonical: "/for/agencies" },
  openGraph: {
    title: "Know what each AI-powered client project actually costs",
    description:
      "BurnLens shows agency AI spend by client and project, with cost per accepted outcome. Prompts stay on the laptop.",
    url: "https://burnlens.app/for/agencies",
    siteName: "BurnLens",
    type: "article",
  },
};

const CLIENTS = [
  { name: "Client A", spend: 428, pct: 51 },
  { name: "Client B", spend: 267, pct: 32 },
  { name: "Internal", spend: 91, pct: 11 },
  { name: "Unallocated", spend: 48, pct: 6 },
];

export default function AgenciesPage() {
  return (
    <div className="legal-page">
      <FunnelPageview event={FUNNEL.AGENCY_LANDING_VIEW} />
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/scan" className="legal-nav-link">Scan</Link>
        <Link href="/demo" className="legal-nav-link">Sample demo</Link>
        <Link href="/setup?intent=register" className="legal-nav-link">Create workspace</Link>
      </nav>

      <main className="legal-content">
        <p
          style={{
            fontFamily: "var(--font-mono), monospace",
            fontSize: 11,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--cyan, #e07840)",
            marginBottom: 8,
          }}
        >
          For software and AI agencies
        </p>
        <h1>Know what each AI-powered client project actually costs.</h1>
        <p className="legal-updated">
          Developers scan locally. The agency sees persistent project economics.
          Prompt bodies never reach BurnLens Cloud.
        </p>

        <div className="lp-econ-card" style={{ opacity: 1, animation: "none", maxWidth: 520, margin: "24px 0" }}>
          <div className="lp-econ-kicker">
            <span>Sample allocation</span>
            <span>fixture — tagged proxy traffic</span>
          </div>
          <ul className="lp-ladder">
            {CLIENTS.map((c) => (
              <li key={c.name}>
                <span>{c.name}</span>
                <span>${c.spend}</span>
                <span className="lp-alloc">
                  <span className="lp-alloc-bar" style={{ width: `${c.pct}px` }} />
                  {c.pct}%
                </span>
              </li>
            ))}
          </ul>
          <p style={{ margin: "12px 0 0", fontSize: 12, color: "var(--muted)" }}>
            Client grain needs <code>X-BurnLens-Tag-Customer</code> on proxy
            traffic. A laptop scan attributes by repository locally;
            repository names are not uploaded to BurnLens Cloud.
          </p>
        </div>

        <div className="lp-econ-card" style={{ opacity: 1, animation: "none", maxWidth: 520, margin: "0 0 32px" }}>
          <div className="lp-econ-kicker">
            <span>Project Alpha</span>
            <span>sample</span>
          </div>
          <dl className="lp-econ-meta" style={{ borderTop: "none", paddingTop: 0 }}>
            <div>
              <dt>AI spend</dt>
              <dd>$428</dd>
            </div>
            <div>
              <dt>Accepted outcomes</dt>
              <dd>36</dd>
            </div>
            <div>
              <dt>Cost / accepted outcome</dt>
              <dd>$11.89</dd>
            </div>
            <div>
              <dt>{C.savings_projected} saving</dt>
              <dd>$74</dd>
            </div>
            <div>
              <dt>{C.savings_verified} saving</dt>
              <dd>$21</dd>
            </div>
          </dl>
          <p style={{ margin: "12px 0 0", fontSize: 12, color: "var(--muted)" }}>
            Projected and verified are reported separately. Unpriced models
            render as $ unknown.
          </p>
        </div>

        <section>
          <h2>How agencies buy BurnLens</h2>
          <ol>
            <li>
              <strong>Free.</strong> An individual developer runs{" "}
              <code>{C.first_command}</code> and <code>{C.repo_economics_command}</code>{" "}
              on their laptop. They see which repos burned the money.
            </li>
            <li>
              <strong>Cloud — $29/month.</strong> Persistent
              tagged economics (customer, feature, team) across developers.
              Self-service is a 7-day trial, card required. Not a 14-day public SKU.
            </li>
            <li>
              <strong>Teams.</strong> Owner plus engineering share reporting, history,
              permissions, and controls.
            </li>
          </ol>
          <p>
            Qualified agency evaluations can be a 14-day guided review of two active
            client projects. That converts to ordinary Cloud or Teams. It is not a
            separate product.
          </p>
        </section>

        <section>
          <h2>What we help you see</h2>
          <p>
            Unallocated spend is the usual leak: coding-agent sessions that never
            got a client or project tag. A review of two live projects is enough
            to show where attribution is missing — that is the conversation,
            not a feature tour.
          </p>
        </section>

        <section>
          <h2>Get started</h2>
          <p>
            <Link href="/scan" className="legal-nav-link">Scan local usage — free</Link>
            {" · "}
            <Link href="/setup?intent=register" className="legal-nav-link">
              {C.cloud_trial.cta}
            </Link>
            {" · "}
            <a href="mailto:contact@sairintechnology.com?subject=BurnLens%20agency%20evaluation">
              Ask for a guided project-cost review
            </a>
          </p>
          <p className="legal-updated">
            {C.cloud_trial.disclaimer} Teams is $99/month.
          </p>
        </section>
      </main>
    </div>
  );
}

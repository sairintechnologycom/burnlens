"use client";

import Link from "next/link";

/** Labeled fixture — not public telemetry, not a live workspace. */
const DATA_CLASS = "DETERMINISTIC_DEMO_FIXTURE" as const;

const HERO = {
  spend: 1842.4,
  requests: 9124,
  accepted: 48,
  perAccepted: 38.38,
  confidencePct: 91,
  coveragePct: 74,
};

const WORKFLOWS = [
  { name: "repo:checkout-service", spend: 612.18, accepted: 14, per: 43.73, coverage: 88, confidence: "estimated" },
  { name: "repo:billing-api", spend: 428.9, accepted: 11, per: 38.99, coverage: 81, confidence: "estimated" },
  { name: "support-triage", spend: 301.44, accepted: 16, per: 18.84, coverage: 64, confidence: "calculated" },
  { name: "(untagged)", spend: 499.88, accepted: 0, per: null, coverage: 0, confidence: "calculated" },
];

const FINDINGS = [
  {
    finding: "Over-specified model on short-output classify",
    why: "support-triage uses gpt-5.6-sol for replies under 80 output tokens.",
    projected: 86.4,
    evidence: "312 requests · avg 54 output tokens · high confidence",
  },
  {
    finding: "History bloat on checkout-service agent sessions",
    why: "Repeated tool transcripts are re-sent; scan rows have no prompt segments.",
    projected: 41.2,
    evidence: "Estimated from token totals · overlapping detectors are not summed",
  },
];

const VERIFICATION = {
  projected: 127.6,
  verified: null as number | null,
  missed: 0,
  verifying: 41.2,
  realisation: null as number | null,
};

function fmt(n: number, decimals = 2) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export default function DemoPage() {
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <div
        style={{
          borderBottom: "1px solid var(--border)",
          padding: "10px 20px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span
            style={{
              background: "var(--bg3)",
              color: "var(--text)",
              fontFamily: "var(--font-mono), monospace",
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.08em",
              padding: "3px 8px",
              borderRadius: 4,
            }}
          >
            {DATA_CLASS}
          </span>
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            Seeded walkthrough of the BurnLens economic loop — not live telemetry.
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href="/scan" style={{ color: "var(--cyan)", fontSize: 12, textDecoration: "none" }}>
            Scan local logs
          </Link>
          <Link href="/" style={{ color: "var(--muted)", fontSize: 12, textDecoration: "none" }}>
            Home
          </Link>
        </div>
      </div>

      <div style={{ padding: "8px 20px 0", fontSize: 12, color: "var(--muted)" }}>
        What is BurnLens? An AI Economics control plane: observe spend, attribute it to
        outcomes, show how much of the number you can trust, recommend an explicit change,
        and verify whether the change saved money.
      </div>

      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">AI Economics</span>
          <span className="section-header-action">fixture · 30d</span>
        </div>
        <div className="stat-strip" style={{ gridTemplateColumns: "repeat(3, 1fr)", borderBottom: "1px solid var(--border)" }}>
          <div className="stat-cell">
            <div className="stat-label">AI Spend</div>
            <div className="stat-value">${fmt(HERO.spend)}</div>
            <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
              {HERO.requests.toLocaleString()} requests
            </div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Accepted outcomes</div>
            <div className="stat-value">{HERO.accepted}</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Cost / accepted outcome</div>
            <div className="stat-value">${fmt(HERO.perAccepted)}</div>
          </div>
        </div>
        <div className="stat-strip" style={{ gridTemplateColumns: "repeat(3, 1fr)", borderBottom: "none" }}>
          <div className="stat-cell">
            <div className="stat-label">Cost Confidence</div>
            <div className="stat-value">{HERO.confidencePct}%</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Outcome Coverage</div>
            <div className="stat-value">{HERO.coveragePct}%</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Provider Reconciliation</div>
            <div className="stat-value" style={{ color: "var(--dim)" }}>
              Not reconciled yet
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Where is AI spend creating expensive outcomes?</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Repository / Workflow</th>
              <th>Spend</th>
              <th>Accepted</th>
              <th>Cost / outcome</th>
              <th>Coverage</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {WORKFLOWS.map((w) => (
              <tr key={w.name}>
                <td>{w.name}</td>
                <td>${fmt(w.spend)}</td>
                <td>{w.accepted || "—"}</td>
                <td>{w.per == null ? <span style={{ color: "var(--dim)" }}>Not enough outcome data</span> : `$${fmt(w.per)}`}</td>
                <td>{w.coverage}%</td>
                <td>{w.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">What should change?</span>
          <span className="section-header-action">${fmt(VERIFICATION.projected)} projected / mo</span>
        </div>
        {FINDINGS.map((f) => (
          <div key={f.finding} style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
            <div style={{ fontWeight: 600 }}>{f.finding}</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>{f.why}</div>
            <div style={{ fontSize: 12, marginTop: 8 }}>
              Projected monthly saving <strong>${fmt(f.projected)}</strong>
              <span style={{ color: "var(--dim)" }}> · {f.evidence}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Did it work?</span>
          <span className="section-header-action">projected is not verified</span>
        </div>
        <div className="stat-strip" style={{ borderBottom: "none", gridTemplateColumns: "repeat(5, 1fr)" }}>
          <div className="stat-cell">
            <div className="stat-label">Projected</div>
            <div className="stat-value">${fmt(VERIFICATION.projected)}</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Verified Savings</div>
            <div className="stat-value" style={{ color: "var(--dim)" }}>No verified changes yet</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Missed</div>
            <div className="stat-value" style={{ color: "var(--dim)" }}>—</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Still verifying</div>
            <div className="stat-value">${fmt(VERIFICATION.verifying)}</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Realisation %</div>
            <div className="stat-value" style={{ color: "var(--dim)" }}>—</div>
          </div>
        </div>
      </div>

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Controls</span>
          <span className="section-header-action">runtime modification is opt-in</span>
        </div>
        <div style={{ padding: 16, fontSize: 13, lineHeight: 1.6, color: "var(--muted)" }}>
          <p>
            <strong style={{ color: "var(--text)" }}>Alert</strong> — Slack or email at 50% and 80% of a
            configured budget. Observation only.
          </p>
          <p>
            <strong style={{ color: "var(--text)" }}>Hard cap</strong> — a per-key daily dollar limit
            returns HTTP 429 before the upstream call. Off until you set a cap.
          </p>
          <p>
            <strong style={{ color: "var(--text)" }}>Explicit model downgrade</strong> —{" "}
            This policy can change the model sent upstream. Enable with{" "}
            <code>routing.budget_downgrade: true</code>. Default is <code>false</code>.
            A budget alone never rewrites the request.
          </p>
        </div>
      </div>

      <div style={{ margin: "24px 16px 64px", textAlign: "center" }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Run the same loop on your machine. No account.
        </div>
        <div
          style={{
            display: "inline-block",
            padding: "10px 16px",
            background: "var(--bg2)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            fontFamily: "var(--font-mono), monospace",
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          <span style={{ color: "var(--muted)" }}>$ </span>pip install burnlens && burnlens scan && burnlens repos
        </div>
        <div>
          <Link href="/scan" className="upgrade-btn" style={{ textDecoration: "none" }}>
            Scan guide
          </Link>
        </div>
      </div>
    </div>
  );
}

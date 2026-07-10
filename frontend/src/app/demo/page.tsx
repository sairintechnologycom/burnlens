/* eslint-disable react-hooks/purity */
"use client";
 


import Link from "next/link";
import BarChart from "@/components/charts/BarChart";
import HorizontalBar from "@/components/charts/HorizontalBar";

// Seeded data for a fictional 50-person AI startup ("Acme AI Co") so visitors
// see what their own dashboard will look like with real spend flowing through.
// The story: 14 days of normal spend, a runaway claude-opus incident on day 12
// caught by a per-key budget cap, one whale customer dominating.

const DAILY_SPEND = [
  18.42, 21.05, 19.88, 24.13, 22.71, 26.04, 23.59,
  25.81, 27.22, 24.96, 29.31, 47.18 /* spike */, 31.47, 28.96,
];
const SPIKE_INDICES = [11];
const DAY_LABELS = (() => {
  const out: string[] = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    out.push(d.toLocaleDateString("en-US", { month: "short", day: "numeric" }));
  }
  return out;
})();

const BY_MODEL = [
  { name: "claude-sonnet-4",    cost: 142.18, calls: 18421 },
  { name: "gpt-4o",             cost:  92.04, calls:  9112 },
  { name: "gemini-2.0-flash",   cost:  38.71, calls: 14208 },
  { name: "gpt-4o-mini",        cost:  21.94, calls: 21340 },
  { name: "claude-haiku-4-5",   cost:  18.62, calls: 12041 },
  { name: "claude-opus-4-7",    cost:  17.24, calls:    81 },
];

const BY_CUSTOMER = [
  { name: "acme-co-prod",       cost:  98.41 },
  { name: "northwind-trial",    cost:  54.22 },
  { name: "globex-prod",        cost:  41.18 },
  { name: "initech-prod",       cost:  32.74 },
  { name: "umbrella-trial",     cost:  28.96 },
  { name: "wonka-prod",         cost:  21.43 },
  { name: "soylent-prod",       cost:  18.71 },
  { name: "(untagged)",         cost:  35.08 },
];

const BY_FEATURE = [
  { name: "chat-assistant",     cost: 121.84 },
  { name: "doc-search",         cost:  68.92 },
  { name: "code-review",        cost:  44.18 },
  { name: "summary-job",        cost:  31.07 },
  { name: "embeddings-batch",   cost:  22.41 },
  { name: "(untagged)",         cost:  42.31 },
];

const BY_TEAM = [
  { name: "platform",  cost: 138.41 },
  { name: "ai-eng",    cost:  92.18 },
  { name: "growth",    cost:  54.07 },
  { name: "support",   cost:  31.94 },
  { name: "(untagged)",cost:  14.13 },
];

interface DemoRequest {
  time: string;
  model: string;
  feature: string;
  customer: string;
  cost: number;
  ms: number;
  flag?: "spike" | "429";
}

const RECENT_REQUESTS: DemoRequest[] = [
  { time: "14:02:11", model: "claude-sonnet-4",  feature: "chat-assistant",  customer: "acme-co-prod",    cost: 0.0214, ms: 1820 },
  { time: "14:02:08", model: "gemini-2.0-flash", feature: "embeddings-batch",customer: "northwind-trial", cost: 0.0008, ms:  340 },
  { time: "14:02:04", model: "gpt-4o",           feature: "code-review",     customer: "globex-prod",     cost: 0.0418, ms: 2940 },
  { time: "14:01:59", model: "claude-opus-4-7",  feature: "doc-search",      customer: "acme-co-prod",    cost: 4.1842, ms: 9120, flag: "spike" },
  { time: "14:01:54", model: "—",                feature: "doc-search",      customer: "acme-co-prod",    cost: 0.0000, ms:    0, flag: "429" },
  { time: "14:01:52", model: "claude-sonnet-4",  feature: "chat-assistant",  customer: "initech-prod",    cost: 0.0182, ms: 1644 },
  { time: "14:01:48", model: "gpt-4o-mini",      feature: "summary-job",     customer: "wonka-prod",      cost: 0.0021, ms:  410 },
  { time: "14:01:43", model: "claude-haiku-4-5", feature: "chat-assistant",  customer: "umbrella-trial",  cost: 0.0034, ms:  812 },
  { time: "14:01:39", model: "gpt-4o",           feature: "doc-search",      customer: "soylent-prod",    cost: 0.0291, ms: 2114 },
  { time: "14:01:34", model: "gemini-2.0-flash", feature: "embeddings-batch",customer: "globex-prod",     cost: 0.0007, ms:  298 },
];

const TOTAL_SPEND = 330.73;
const TOTAL_REQUESTS = 75203;
const AVG_PER_REQ = TOTAL_SPEND / TOTAL_REQUESTS;
const WASTE = 24.91;

function fmt(n: number, decimals = 2) {
  return n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function latencyClass(ms: number) {
  if (ms === 0) return "";
  if (ms < 1000) return "latency-fast";
  if (ms <= 3000) return "latency-mid";
  return "latency-slow";
}

export default function DemoPage() {
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      {/* Demo banner */}
      <div
        style={{
          background: "linear-gradient(90deg, rgba(224,120,64,0.10), rgba(224,120,64,0.02))",
          borderBottom: "1px solid #1e2830",
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
              background: "#e07840",
              color: "#080c10",
              fontFamily: "var(--font-mono), monospace",
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.12em",
              padding: "3px 8px",
              borderRadius: 4,
            }}
          >
            LIVE DEMO
          </span>
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            Seeded data for <strong style={{ color: "var(--text)" }}>Acme AI Co</strong> · 14-day window · this is the
            view you get on your own machine.
          </span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link
            href="/setup?intent=register"
            className="plausible-event-name=Demo+Get+Started plausible-event-position=Header"
            style={{
              background: "#e07840",
              color: "#080c10",
              fontFamily: "var(--font-mono), monospace",
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.04em",
              padding: "6px 14px",
              borderRadius: 4,
              textDecoration: "none",
            }}
          >
            Get yours →
          </Link>
          <Link
            href="/"
            style={{
              color: "var(--muted)",
              fontFamily: "var(--font-mono), monospace",
              fontSize: 11,
              padding: "6px 14px",
              textDecoration: "none",
            }}
          >
            Home
          </Link>
        </div>
      </div>

      {/* Dashboard chrome — mimics Topbar without auth */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 20px",
          borderBottom: "1px solid #1e2830",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <svg width="18" height="18" viewBox="0 0 26 26" fill="none">
            <circle cx="13" cy="13" r="11.5" stroke="#2a3540" strokeWidth="1" />
            <path d="M13 1.5 A11.5 11.5 0 0 1 24 8" stroke="#f0a928" strokeWidth="1.5" strokeLinecap="round" fill="none" />
            <circle cx="13" cy="13" r="7.5" stroke="#1e2830" strokeWidth="1" />
            <circle cx="13" cy="13" r="2" fill="#e07840" />
          </svg>
          <span
            style={{
              fontFamily: "var(--font-sans), system-ui",
              fontWeight: 800,
              fontSize: 13,
              letterSpacing: "0.08em",
              color: "var(--text)",
            }}
          >
            BURNLENS
          </span>
          <span
            style={{
              marginLeft: 12,
              fontFamily: "var(--font-mono), monospace",
              fontSize: 11,
              color: "var(--muted)",
            }}
          >
            acme-ai-co · workspace
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <span
            style={{
              fontFamily: "var(--font-mono), monospace",
              fontSize: 10,
              letterSpacing: "0.08em",
              color: "#f0a928",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "#f0a928",
                boxShadow: "0 0 8px #f0a928",
              }}
            />
            LIVE
          </span>
          <span style={{ fontFamily: "var(--font-mono), monospace", fontSize: 11, color: "var(--muted)" }}>14d</span>
        </div>
      </div>

      {/* Stat strip */}
      <div className="stat-strip">
        <div className="stat-cell">
          <div className="stat-label">Total spend</div>
          <div className="stat-value cyan">${fmt(TOTAL_SPEND)}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Requests</div>
          <div className="stat-value">{TOTAL_REQUESTS.toLocaleString()}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Avg / req</div>
          <div className="stat-value">${fmt(AVG_PER_REQ, 4)}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Waste detected</div>
          <div className="stat-value amber">${fmt(WASTE)}</div>
        </div>
      </div>

      {/* Daily spend chart */}
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Daily spend</span>
          <span className="section-header-action">14d · 1 spike flagged</span>
        </div>
        <BarChart labels={DAY_LABELS} data={DAILY_SPEND} spikeIndices={SPIKE_INDICES} height={180} />
        <div
          style={{
            padding: "8px 16px 14px",
            fontFamily: "var(--font-mono), monospace",
            fontSize: 11,
            color: "var(--amber)",
          }}
        >
          ↑ Spike on{" "}
          {new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}{" "}
          — claude-opus runaway from <code>acme-co-prod</code>; hard cap stopped it at $47.18.
        </div>
      </div>

      {/* Two-up: by model + by customer */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))",
          gap: 16,
          padding: 16,
          paddingBottom: 0,
        }}
      >
        <div className="card" style={{ margin: 0 }}>
          <div className="section-header">
            <span className="section-header-title">By model</span>
            <span className="section-header-action">{BY_MODEL.length} models</span>
          </div>
          <HorizontalBar labels={BY_MODEL.map((m) => m.name)} data={BY_MODEL.map((m) => m.cost)} height={240} />
        </div>

        <div className="card" style={{ margin: 0 }}>
          <div className="section-header">
            <span className="section-header-title">By customer</span>
            <span className="section-header-action">top customer = 30% of spend</span>
          </div>
          <HorizontalBar
            labels={BY_CUSTOMER.map((c) => c.name)}
            data={BY_CUSTOMER.map((c) => c.cost)}
            flaggedIndices={[0]}
            height={240}
          />
        </div>
      </div>

      {/* Two-up: by feature + by team */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))",
          gap: 16,
          padding: 16,
          paddingBottom: 0,
        }}
      >
        <div className="card" style={{ margin: 0 }}>
          <div className="section-header">
            <span className="section-header-title">By feature</span>
          </div>
          <HorizontalBar labels={BY_FEATURE.map((f) => f.name)} data={BY_FEATURE.map((f) => f.cost)} height={200} />
        </div>

        <div className="card" style={{ margin: 0 }}>
          <div className="section-header">
            <span className="section-header-title">By team</span>
          </div>
          <HorizontalBar labels={BY_TEAM.map((t) => t.name)} data={BY_TEAM.map((t) => t.cost)} height={200} />
        </div>
      </div>

      {/* Recent requests with runaway + 429 highlights */}
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Recent requests</span>
          <span className="section-header-action">runaway + 429 event highlighted</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Model</th>
              <th>Feature</th>
              <th>Customer</th>
              <th>Cost</th>
              <th>ms</th>
            </tr>
          </thead>
          <tbody>
            {RECENT_REQUESTS.map((r, i) => {
              const isSpike = r.flag === "spike";
              const is429 = r.flag === "429";
              const rowStyle = isSpike
                ? { background: "rgba(240,169,40,0.08)" }
                : is429
                ? { background: "rgba(240,64,96,0.08)" }
                : undefined;
              return (
                <tr key={i} style={rowStyle}>
                  <td style={{ fontFamily: "var(--font-mono), monospace" }}>{r.time}</td>
                  <td>
                    {is429 ? (
                      <span
                        style={{
                          fontFamily: "var(--font-mono), monospace",
                          fontSize: 10,
                          fontWeight: 700,
                          color: "#f04060",
                          background: "rgba(240,64,96,0.12)",
                          padding: "2px 6px",
                          borderRadius: 3,
                          letterSpacing: "0.04em",
                        }}
                      >
                        HTTP 429 · cap hit
                      </span>
                    ) : (
                      r.model
                    )}
                  </td>
                  <td>
                    <span className="tag tag-feature">{r.feature}</span>
                  </td>
                  <td>{r.customer}</td>
                  <td
                    style={{
                      color: isSpike ? "#f0a928" : r.cost > 0.05 ? "var(--amber)" : undefined,
                      fontWeight: isSpike ? 600 : undefined,
                    }}
                  >
                    {is429 ? "—" : `$${r.cost.toFixed(4)}`}
                  </td>
                  <td className={latencyClass(r.ms)}>{r.ms === 0 ? "—" : r.ms}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div
          style={{
            padding: "10px 16px 14px",
            fontFamily: "var(--font-mono), monospace",
            fontSize: 11,
            color: "var(--muted)",
            borderTop: "1px solid #1e2830",
          }}
        >
          14:01:54 — <code>acme-co-prod</code> hit its daily $50 cap on the <code>doc-search</code> key.
          BurnLens returned <code>HTTP 429</code> before the upstream Anthropic call. The previous turn
          (14:01:59, $4.18 claude-opus call) is what tipped it over.
        </div>
      </div>

      {/* CTA footer */}
      <div
        style={{
          margin: "32px 16px 64px",
          padding: "32px 24px",
          border: "1px solid #1e2830",
          borderRadius: 8,
          background: "#0e1318",
          textAlign: "center",
        }}
      >
        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text)", marginBottom: 6 }}>
          This is the dashboard you get for your own stack.
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 18 }}>
          Install BurnLens locally — your data never leaves your machine.
        </div>
        <div
          style={{
            display: "inline-block",
            padding: "10px 16px",
            background: "#080c10",
            border: "1px solid #1e2830",
            borderRadius: 6,
            fontFamily: "var(--font-mono), monospace",
            fontSize: 13,
            color: "#e07840",
            marginBottom: 18,
          }}
        >
          <span style={{ color: "var(--muted)" }}>$ </span>pip install burnlens &amp;&amp; burnlens start
        </div>
        <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
          <Link
            href="/setup?intent=register"
            className="plausible-event-name=Demo+Get+Started plausible-event-position=Footer"
            style={{
              background: "#e07840",
              color: "#080c10",
              fontWeight: 600,
              fontSize: 13,
              padding: "10px 18px",
              borderRadius: 6,
              textDecoration: "none",
            }}
          >
            Start free trial
          </Link>
          <a
            href="https://github.com/sairintechnologycom/burnlens"
            target="_blank"
            rel="noopener noreferrer"
            className="plausible-event-name=Demo+GitHub+Click"
            style={{
              background: "transparent",
              color: "var(--text)",
              border: "1px solid #1e2830",
              fontWeight: 500,
              fontSize: 13,
              padding: "10px 18px",
              borderRadius: 6,
              textDecoration: "none",
            }}
          >
            View on GitHub
          </a>
        </div>
      </div>
    </div>
  );
}

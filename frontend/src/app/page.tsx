"use client";
/* eslint-disable react-hooks/exhaustive-deps */


import Link from "next/link";
import { useEffect, useRef, useState } from "react";

const TERMINAL_LINES = [
  { prompt: true,  text: "pip install burnlens", delay: 0 },
  { prompt: false, text: "Collecting burnlens", delay: 800 },
  { prompt: false, text: "  Downloading burnlens-1.6.2-py3-none-any.whl", delay: 1200 },
  { prompt: false, text: "Successfully installed burnlens-1.6.2", delay: 1800 },
  { prompt: true,  text: "burnlens start", delay: 2400 },
  { prompt: false, text: "BurnLens v1.6.2 \u2022 proxy on :8420 \u2022 dashboard on :8420/ui", delay: 3000, highlight: true },
  { prompt: false, text: "Intercepting: OpenAI, Anthropic, Google, Groq, Mistral, Together, Azure", delay: 3400 },
  { prompt: false, text: "Ready. Waiting for requests...", delay: 3800, highlight: true },
];

const MOCK_MODELS = [
  { name: "claude-sonnet-5", cost: 12.47, pct: 100, calls: 1243 },
  { name: "gpt-5.6-sol", cost: 8.92, pct: 71, calls: 891 },
  { name: "gemini-3.1-flash-lite", cost: 3.21, pct: 26, calls: 2104 },
  { name: "gpt-5-mini", cost: 1.84, pct: 15, calls: 3421 },
];

const MOCK_DAILY = [0.8, 1.2, 2.1, 1.6, 3.4, 2.8, 4.1, 3.2, 2.9, 3.8, 4.6, 3.1, 5.2, 4.8];

const HEATBAR_ROWS = [
  { model: "gpt-5.6-sol",     value: 342, pct: 100, tier: "hot"   },
  { model: "claude-sonnet-5", value: 218, pct: 64,  tier: "warm"  },
  { model: "gpt-5-mini",      value: 94,  pct: 27,  tier: "mid"   },
  { model: "haiku-4.5",       value: 41,  pct: 12,  tier: "muted" },
  { model: "gemini-3.1",      value: 22,  pct: 6,   tier: "muted" },
] as const;

function HeatBars() {
  return (
    <div
      className="lp-heatbars"
      role="img"
      aria-label="Example dashboard: gpt-5.6-sol burning $342 of the $1,000 daily cap, total $717 used."
    >
      <div className="lp-heatbars-head">
        <span>Spend by model</span>
        <span className="lp-heatbars-period">past 24h</span>
      </div>
      <div className="lp-heatbars-rows">
        {HEATBAR_ROWS.map((r, i) => (
          <div
            key={r.model}
            className={`lp-heatbars-row tier-${r.tier}`}
            style={{ animationDelay: `${i * 70 + 200}ms` }}
          >
            <span className="lp-heatbars-model">{r.model}</span>
            <div className="lp-heatbars-track">
              <div
                className="lp-heatbars-fill"
                style={{
                  ["--lp-fill" as never]: `${r.pct}%`,
                  animationDelay: `${i * 70 + 280}ms`,
                }}
              />
            </div>
            <span className="lp-heatbars-value">${r.value}</span>
          </div>
        ))}
        <div className="lp-heatbars-row tier-faded" style={{ animationDelay: "660ms" }}>
          <span className="lp-heatbars-model">tail of 18</span>
          <div className="lp-heatbars-track">
            <div
              className="lp-heatbars-fill"
              style={{
                ["--lp-fill" as never]: "3%",
                animationDelay: "740ms",
              }}
            />
          </div>
          <span className="lp-heatbars-value">$11</span>
        </div>
      </div>
      <div className="lp-heatbars-divider" />
      <div className="lp-heatbars-total">
        <div className="lp-heatbars-total-head">
          <span className="lp-heatbars-total-label">Daily cap</span>
          <span className="lp-heatbars-total-value">
            <span className="lp-heatbars-total-num">$717</span>
            <span className="lp-heatbars-total-cap"> / $1,000</span>
          </span>
        </div>
        <div className="lp-heatbars-progress">
          <div className="lp-heatbars-progress-fill" />
        </div>
        <div className="lp-heatbars-total-foot">
          <span>$283 left</span>
          <span className="lp-heatbars-total-burn">burning at $30/hr · 9h to cap</span>
        </div>
      </div>
    </div>
  );
}

function TerminalAnimation({ onComplete }: { onComplete: () => void }) {
  const [visibleLines, setVisibleLines] = useState<number>(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    TERMINAL_LINES.forEach((line, i) => {
      const t = setTimeout(() => setVisibleLines(i + 1), line.delay);
      timerRef.current.push(t);
    });
    const done = setTimeout(onComplete, 4600);
    timerRef.current.push(done);
    return () => timerRef.current.forEach(clearTimeout);
  }, [onComplete]);

  return (
    <div className="term-window">
      <div className="term-bar">
        <span className="term-dot" style={{ background: "var(--cyan)" }} />
        <span className="term-dot" style={{ background: "var(--border)" }} />
        <span className="term-dot" style={{ background: "var(--border)" }} />
        <span className="term-bar-title">Terminal</span>
      </div>
      <div className="term-body">
        {TERMINAL_LINES.slice(0, visibleLines).map((line, i) => (
          <div key={i} className={`term-line ${line.highlight ? "term-highlight" : ""}`}>
            {line.prompt && <span className="term-prompt">$</span>}
            {!line.prompt && <span className="term-indent" />}
            <span>{line.text}</span>
          </div>
        ))}
        <div className="term-cursor" />
      </div>
    </div>
  );
}

function MiniDashboard() {
  return (
    <div className="dash-preview">
      {/* Topbar */}
      <div className="dash-topbar">
        <div className="dash-topbar-left">
          <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
            <circle cx="10" cy="10" r="8" stroke="#e07840" strokeWidth="1.5" />
            <circle cx="10" cy="10" r="2" fill="#e07840" />
            <path d="M 10 2 A 8 8 0 0 1 18 10" stroke="#e89656" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span className="dash-topbar-brand">BURNLENS</span>
        </div>
        <div className="dash-topbar-nav">
          <span className="dash-topbar-link active">Overview</span>
          <span className="dash-topbar-link">Models</span>
          <span className="dash-topbar-link">Teams</span>
          <span className="dash-topbar-link">Alerts</span>
        </div>
        <div className="dash-topbar-right">
          <span className="dash-live"><span className="dash-live-dot" />LIVE</span>
          <span className="dash-period active">7d</span>
          <span className="dash-period">30d</span>
        </div>
      </div>

      {/* Stats */}
      <div className="dash-stats">
        <div className="dash-stat">
          <div className="dash-stat-label">Total spend</div>
          <div className="dash-stat-value cyan">$26.44</div>
          <div className="dash-stat-delta down">&darr; 12% vs prev</div>
        </div>
        <div className="dash-stat">
          <div className="dash-stat-label">Requests</div>
          <div className="dash-stat-value">7,659</div>
        </div>
        <div className="dash-stat">
          <div className="dash-stat-label">Avg / req</div>
          <div className="dash-stat-value">$0.0035</div>
        </div>
        <div className="dash-stat">
          <div className="dash-stat-label">Waste detected</div>
          <div className="dash-stat-value amber">$4.12</div>
          <div className="dash-stat-delta">15.6% of spend</div>
        </div>
      </div>

      {/* Chart + Models side by side */}
      <div className="dash-body">
        <div className="dash-chart-section">
          <div className="dash-section-header">Daily spend</div>
          <div className="dash-bars">
            {MOCK_DAILY.map((v, i) => (
              <div key={i} className="dash-bar-col">
                <div
                  className="dash-bar"
                  style={{ height: `${(v / 5.5) * 100}%` }}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="dash-models-section">
          <div className="dash-section-header">By model</div>
          {MOCK_MODELS.map((m, i) => (
            <div key={i} className="dash-model-row">
              <span className="dash-model-rank">{i + 1}</span>
              <div className="dash-model-info">
                <span className="dash-model-name">{m.name}</span>
                <div className="dash-model-bar-bg">
                  <div className="dash-model-bar-fill" style={{ width: `${m.pct}%` }} />
                </div>
              </div>
              <span className="dash-model-cost">${m.cost.toFixed(2)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function LandingPage() {
  const [termDone, setTermDone] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <>
      <div className="lp">
        {/* NAV */}
        <nav className="lp-nav">
          <Link href="/" className="lp-nav-logo">
            <svg width="22" height="22" viewBox="0 0 26 26" fill="none">
              <circle cx="13" cy="13" r="11.5" stroke="#2f2820" strokeWidth="1"/>
              <path d="M13 1.5 A11.5 11.5 0 0 1 24 8" stroke="#e89656" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
              <circle cx="13" cy="13" r="7.5" stroke="#2f2820" strokeWidth="1"/>
              <path d="M13 5.5 A7.5 7.5 0 0 1 20.5 10" stroke="#e07840" strokeWidth="1.2" strokeLinecap="round" fill="none"/>
              <circle cx="13" cy="13" r="3.5" stroke="#2f2820" strokeWidth="0.8"/>
              <circle cx="13" cy="13" r="2" fill="#e89656"/>
            </svg>
            BURNLENS
          </Link>
          <div className="lp-nav-right">
            <a href="#how">How it works</a>
            <a href="#pricing">Pricing</a>
            <a href="https://github.com/sairintechnologycom/burnlens#readme">Docs</a>
            <Link href="/demo" className="outline">Live demo</Link>
            <Link href="/setup?intent=register" className="primary">Get Started</Link>
          </div>
          <button
            className="lp-mobile-menu-btn"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((o) => !o)}
          >
            {menuOpen ? (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M4 4L16 16M16 4L4 16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            )}
          </button>
        </nav>

        {/* MOBILE DRAWER */}
        {menuOpen && (
          <>
            <div className="lp-mobile-overlay" onClick={() => setMenuOpen(false)} />
            <div className="lp-mobile-drawer">
              <a href="#how" onClick={() => setMenuOpen(false)}>How it works</a>
              <a href="#pricing" onClick={() => setMenuOpen(false)}>Pricing</a>
              <a href="https://github.com/sairintechnologycom/burnlens#readme" onClick={() => setMenuOpen(false)}>Docs</a>
              <Link href="/demo" onClick={() => setMenuOpen(false)}>Live demo</Link>
              <Link href="/setup" className="lp-mobile-cta" onClick={() => setMenuOpen(false)}>Get Started</Link>
            </div>
          </>
        )}

        {/* HERO: left-aligned asymmetric two-column */}
        <section className="lp-hero">
          <div className="lp-hero-grid">
            <div className="lp-hero-left">
              <h1 className="lp-headline">
                Hard-cap your AI spend across every provider — <span className="acc">before the call</span>, not after the bill
              </h1>
              <p className="lp-subline">
                One local-first proxy for OpenAI, Anthropic, Google, Groq, Mistral, Together, and Azure OpenAI. Hard 429 caps, per-feature attribution, prompts never leave your machine. Free for solo use. $29/mo for teams.
              </p>
              <div className="lp-hero-cta">
                <Link href="/setup?intent=register" className="lp-hero-btn primary">
                  Start free trial
                  <svg width="14" height="14" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <path d="M5 10h10m-4-4 4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </Link>
                <a
                  href="https://github.com/sairintechnologycom/burnlens"
                  className="lp-hero-btn secondary"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                    <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38v-1.34c-2.22.48-2.69-1.07-2.69-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.06-.49.06-.49.8.06 1.23.83 1.23.83.72 1.23 1.88.88 2.34.67.07-.52.28-.88.51-1.08-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.01.08-2.11 0 0 .67-.21 2.2.82a7.65 7.65 0 0 1 4 0c1.53-1.03 2.2-.82 2.2-.82.44 1.1.16 1.91.08 2.11.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.74.54 1.48v2.2c0 .21.15.46.55.38A8 8 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/>
                  </svg>
                  View on GitHub
                </a>
              </div>
              <div className="lp-provider-strip lp-provider-strip-left">
                {["OpenAI", "Anthropic", "Google", "Groq", "Mistral", "Together", "Azure OpenAI"].map((p) => (
                  <span key={p} className="lp-provider-chip">{p}</span>
                ))}
                <span className="lp-provider-more">AWS Bedrock — on the roadmap</span>
              </div>
            </div>
            <div className="lp-hero-right">
              <HeatBars />
            </div>
          </div>
        </section>

        {/* INSTALL: terminal animation in its own block */}
        <section className="lp-install-demo">
          <div className="lp-install-demo-inner">
            <TerminalAnimation onComplete={() => setTermDone(true)} />
          </div>
        </section>

        {/* TRANSITION: terminal done → dashboard appears */}
        {termDone && (
          <>
            <div className="lp-transition">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M10 4 L10 16 M5 11 L10 16 L15 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>

            <div style={{ padding: "0 24px 80px" }}>
              <MiniDashboard />
              <p style={{
                textAlign: "center", marginTop: 16,
                fontFamily: "var(--font-mono), monospace",
                fontSize: 11, color: "var(--l-muted)", letterSpacing: "0.06em"
              }}>
                localhost:8420/ui — your data never leaves your machine
              </p>
            </div>
          </>
        )}

        {/* THE PROBLEM */}
        <section className="lp-problem">
          <h2>The problem</h2>
          <div className="lp-problem-grid">
            <div className="lp-problem-card">
              <h3>Bills tell you the model, not the why.</h3>
              <p>
                Your invoice says <code>gpt-4o: $4,287</code>. It doesn&apos;t say
                which feature, team, or customer burned it. By the time you trace
                the spike, it&apos;s already on next month&apos;s card.
              </p>
            </div>
            <div className="lp-problem-card">
              <h3>Alerts arrive after the damage.</h3>
              <p>
                A bad deploy, a runaway agent, or one abusive customer can trigger
                thousands of API calls before any dashboard turns red. You find out
                when you open the bill.
              </p>
            </div>
            <div className="lp-problem-card">
              <h3>Every provider is a different silo.</h3>
              <p>
                OpenAI&apos;s usage page. Anthropic&apos;s console. Azure Cost Management.
                Bedrock CloudWatch. No unified view, no way to ask which feature
                is your biggest AI spend across all providers.
              </p>
            </div>
          </div>
        </section>

        {/* HOW IT WORKS */}
        <div className="lp-editorial" id="how">
          <h2>How it works</h2>
          <div className="lp-ed-section">
            <div className="lp-ed-label">01 · Drop-in proxy</div>
            <div className="lp-ed-content">
              <h3>Set one env var. Done.</h3>
              <p>
                BurnLens runs a local proxy on <code>:8420</code>. Set{" "}
                <code>OPENAI_BASE_URL</code> or <code>ANTHROPIC_BASE_URL</code> and
                your existing SDK code routes through automatically.
                Designed for low overhead with full streaming passthrough.
              </p>
            </div>
          </div>

          <div className="lp-ed-section">
            <div className="lp-ed-label">02 · Tag what matters</div>
            <div className="lp-ed-content">
              <h3>Attribute any call to any dimension.</h3>
              <p>
                Three request headers — <code>X-BurnLens-Tag-Feature</code>,{" "}
                <code>-Team</code>, <code>-Customer</code> — attribute cost to any
                dimension you care about. Tags are stripped before reaching the AI
                provider. They never leave your machine.
              </p>
            </div>
          </div>

          <div className="lp-ed-section">
            <div className="lp-ed-label">03 · Cap before you call</div>
            <div className="lp-ed-content">
              <h3>429 before the upstream request, not after the bill.</h3>
              <p>
                Register an API key with a daily dollar limit. At 100%, BurnLens
                returns <code>429</code> before the call is forwarded upstream.
                50% and 80% thresholds fire Slack or email alerts.
              </p>
            </div>
          </div>

          <div className="lp-ed-section">
            <div className="lp-ed-label">04 · One dashboard</div>
            <div className="lp-ed-content">
              <h3>Every provider, unified.</h3>
              <p>
                OpenAI, Anthropic, Google, Groq, Mistral, Together, and Azure OpenAI spend in one view today.
                AWS Bedrock is on the roadmap.
                Model breakdowns, waste detection, and budget tracking using versioned provider pricing.
              </p>
            </div>
          </div>
        </div>

        {/* USE CASES */}
        <section className="lp-usecases">
          <h2>Built for every AI use case</h2>
          <div className="lp-usecases-grid">
            <div className="lp-usecase-card">
              <h3>Coding agents: per-PR, per-dev attribution</h3>
              <p>
                Cursor, Claude Code, Cline, Windsurf — see cost per repo, developer,
                or PR. Hard daily caps per API key stop one runaway agent from
                burning the team&apos;s monthly budget overnight.
              </p>
              <p style={{ marginTop: 12, fontSize: "var(--fs-12)" }}>
                <a
                  href="/scan"
                  style={{ color: "var(--cyan)", textDecoration: "none", fontWeight: 500 }}
                >
                  Scan retroactive history with one command →
                </a>
              </p>
            </div>
            <div className="lp-usecase-card">
              <h3>Customer-facing AI: per-customer spend and controls</h3>
              <p>
                Tag each request with a customer ID. See which customers drive the
                most cost. Alert on per-customer budget thresholds and configure
                cheaper-model routing.
              </p>
            </div>
            <div className="lp-usecase-card">
              <h3>RAG and agents: see what justifies the cost</h3>
              <p>
                Tag retrieval calls, tool calls, and generation separately. See
                whether your vector search or synthesis step is the cost driver —
                and whether it justifies the output quality.
              </p>
            </div>
            <div className="lp-usecase-card">
              <h3>Internal tools: per-team budgets with exportable cost records</h3>
              <p>
                Set per-team monthly budgets, get Slack alerts at 80% and 100%,
                and export monthly records for comparison with provider invoices.
              </p>
            </div>
          </div>
        </section>

        {/* BEYOND THE DASHBOARD */}
        <section className="lp-usecases">
          <h2>Beyond the dashboard</h2>
          <div className="lp-usecases-grid">
            <div className="lp-usecase-card">
              <h3>Semantic cache: skip the call, save the cost</h3>
              <p>
                BurnLens caches repeated prompts using exact match and cosine-similarity
                embedding search. Identical or near-identical queries are served from
                cache — the upstream API call never happens and you pay nothing.
              </p>
            </div>
            <div className="lp-usecase-card">
              <h3>Model recommendations: find the cheaper path</h3>
              <p>
                <code>burnlens recommend</code> analyses your usage and suggests cheaper
                model alternatives with confidence scores and projected savings.
                Switch from gpt-5.6-sol to gpt-5.6-terra where output tokens stay short.
              </p>
            </div>
            <div className="lp-usecase-card">
              <h3>Anomaly detection: catch runaways in real time</h3>
              <p>
                Sliding-window statistical analysis (MAD / Z-score) across 1-minute,
                5-minute, 15-minute, and 1-hour windows. Cost spikes and runaway
                agent loops fire alerts before the damage compounds.
              </p>
            </div>
            <div className="lp-usecase-card">
              <h3>Automatic model routing: degrade gracefully</h3>
              <p>
                When a budget threshold is hit, BurnLens can silently route requests
                to a cheaper model instead of hard-blocking with 429. Your app stays
                live — it just gets more cost-efficient.
              </p>
            </div>
          </div>
        </section>

        {/* WHY BURNLENS */}
        <section className="lp-compare">
          <h2>Why BurnLens</h2>
          <div className="lp-compare-wrap">
            <table className="lp-compare-table">
              <thead>
                <tr>
                  <th></th>
                  <th>BurnLens</th>
                  <th>Helicone / Langfuse</th>
                  <th>Vantage / CloudZero</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Open source</td>
                  <td className="yes">✓</td>
                  <td className="partial">Partial</td>
                  <td className="no">✗</td>
                </tr>
                <tr>
                  <td>Local-first (prompts stay local)</td>
                  <td className="yes">✓</td>
                  <td className="no">✗</td>
                  <td className="no">✗</td>
                </tr>
                <tr>
                  <td>Hard caps before API call</td>
                  <td className="yes">✓</td>
                  <td className="no">✗</td>
                  <td className="no">✗</td>
                </tr>
                <tr>
                  <td>Per-customer attribution</td>
                  <td className="yes">✓</td>
                  <td className="yes">✓</td>
                  <td className="no">✗</td>
                </tr>
                <tr>
                  <td>Multi-cloud (Azure / AWS / GCP)</td>
                  <td className="partial">Partial</td>
                  <td className="partial">Partial</td>
                  <td className="yes">✓</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* PRICING */}
        <section className="lp-pricing" id="pricing">
          <h2 className="lp-pricing-title">Simple pricing</h2>
          <p className="lp-pricing-sub">Free forever for individual developers. Pay only when your team needs cloud sync.</p>
          <div className="lp-pricing-grid">
            <div className="lp-plan">
              <div className="lp-plan-name">Free</div>
              <div className="lp-plan-price">$0<span>/mo</span></div>
              <ul className="lp-plan-features">
                <li>Local proxy + dashboard</li>
                <li>All 7 providers</li>
                <li>Waste detection + recommendations</li>
                <li>Budget alerts + anomaly detection</li>
                <li>7-day history</li>
              </ul>
              <a href="#install" className="lp-plan-cta outline">Install free</a>
            </div>
            <div className="lp-plan featured">
              <div className="lp-plan-badge">Popular</div>
              <div className="lp-plan-name">Cloud</div>
              <div className="lp-plan-price">$29<span>/mo</span></div>
              <ul className="lp-plan-features">
                <li>Everything in Free</li>
                <li>Cloud sync + team dashboard</li>
                <li>90-day history</li>
                <li>Up to 3 seats</li>
                <li>Email alerts</li>
              </ul>
              <Link href="/setup?intent=register" className="lp-plan-cta primary">Start free trial</Link>
            </div>
            <div className="lp-plan">
              <div className="lp-plan-name">Teams</div>
              <div className="lp-plan-price">$99<span>/mo</span></div>
              <ul className="lp-plan-features">
                <li>Everything in Cloud</li>
                <li>Up to 10 seats</li>
                <li>RBAC (owner/admin/viewer)</li>
                <li>365-day history</li>
                <li>Audit log</li>
              </ul>
              <a href="mailto:contact@sairintechnology.com?subject=BurnLens%20Teams%20plan" className="lp-plan-cta outline">Talk to sales</a>
            </div>
            <div className="lp-plan">
              <div className="lp-plan-name">Enterprise</div>
              <div className="lp-plan-price">Custom</div>
              <ul className="lp-plan-features">
                <li>Everything in Teams</li>
                <li>Unlimited seats</li>
                <li>OTEL export</li>
                <li>Custom pricing rules</li>
                <li>10-year retention</li>
              </ul>
              <a href="mailto:contact@sairintechnology.com" className="lp-plan-cta outline">Contact Us</a>
            </div>
          </div>
        </section>

        {/* INSTALL CTA */}
        <section className="lp-install" id="install">
          <h2>Up in 3 commands</h2>
          <div className="lp-install-code">
            <div className="lp-install-line">
              <span className="lp-install-prompt">$</span>
              <span>pip install burnlens</span>
            </div>
            <div className="lp-install-line">
              <span className="lp-install-prompt">$</span>
              <span>burnlens start</span>
            </div>
            <div className="lp-install-line">
              <span className="lp-install-prompt">#</span>
              <span className="lp-install-comment">Dashboard at localhost:8420/ui</span>
            </div>
          </div>
          <div className="lp-install-cta">
            <Link href="/setup?intent=register" className="lp-btn-go">Get Started</Link>
            <a href="https://github.com/sairintechnologycom/burnlens" className="lp-btn-gh">View on GitHub</a>
          </div>
        </section>

        <footer className="lp-footer">
          <div className="lp-footer-main">
            BurnLens &copy; 2026 · Open Source · Self-Hosted
          </div>
          <div className="lp-footer-company">
            A product of <a href="https://sairintechnology.com" target="_blank" rel="noopener noreferrer">Sairin Technology</a>
          </div>
          <div className="lp-footer-legal">
            <a href="/scan">Scan coding-agent spend</a>
            <span>·</span>
            <a href="/demo">Live demo</a>
            <span>·</span>
            <a href="https://github.com/sairintechnologycom/burnlens" target="_blank" rel="noopener noreferrer">GitHub</a>
          </div>
          <div className="lp-footer-legal">
            <a href="/status">Status</a>
            <span>·</span>
            <a href="/security">Security</a>
            <span>·</span>
            <a href="/terms">Terms &amp; Conditions</a>
            <span>·</span>
            <a href="/privacy">Privacy Policy</a>
            <span>·</span>
            <a href="/refund">Refund Policy</a>
          </div>
        </footer>
      </div>
    </>
  );
}

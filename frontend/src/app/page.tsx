"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

const TERMINAL_LINES = [
  { prompt: true,  text: "pip install burnlens", delay: 0 },
  { prompt: false, text: "Collecting burnlens", delay: 800 },
  { prompt: false, text: "  Downloading burnlens-1.0.1.tar.gz (42 kB)", delay: 1200 },
  { prompt: false, text: "Successfully installed burnlens-1.0.1", delay: 1800 },
  { prompt: true,  text: "burnlens start", delay: 2400 },
  { prompt: false, text: "BurnLens v1.0.1 \u2022 proxy on :8420 \u2022 dashboard on :8420/ui", delay: 3000, highlight: true },
  { prompt: false, text: "Intercepting: OPENAI_BASE_URL, ANTHROPIC_BASE_URL", delay: 3400 },
  { prompt: false, text: "Ready. Waiting for requests...", delay: 3800, highlight: true },
];

const MOCK_MODELS = [
  { name: "claude-sonnet-4", cost: 12.47, pct: 100, calls: 1243 },
  { name: "gpt-4o", cost: 8.92, pct: 71, calls: 891 },
  { name: "gemini-2.0-flash", cost: 3.21, pct: 26, calls: 2104 },
  { name: "gpt-4o-mini", cost: 1.84, pct: 15, calls: 3421 },
];

const MOCK_DAILY = [0.8, 1.2, 2.1, 1.6, 3.4, 2.8, 4.1, 3.2, 2.9, 3.8, 4.6, 3.1, 5.2, 4.8];

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
        <span className="term-dot" style={{ background: "#f04060" }} />
        <span className="term-dot" style={{ background: "#f0a928" }} />
        <span className="term-dot" style={{ background: "#22c98a" }} />
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
            <circle cx="10" cy="10" r="8" stroke="#00e5c8" strokeWidth="1.5" />
            <circle cx="10" cy="10" r="2" fill="#00e5c8" />
            <path d="M 10 2 A 8 8 0 0 1 18 10" stroke="#f0a928" strokeWidth="1.5" strokeLinecap="round" />
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

  return (
    <>
      <div className="lp">
        {/* NAV */}
        <nav className="lp-nav">
          <Link href="/" className="lp-nav-logo">
            <svg width="22" height="22" viewBox="0 0 26 26" fill="none">
              <circle cx="13" cy="13" r="11.5" stroke="#2a3540" strokeWidth="1"/>
              <path d="M13 1.5 A11.5 11.5 0 0 1 24 8" stroke="#f0a928" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
              <circle cx="13" cy="13" r="7.5" stroke="#1e2830" strokeWidth="1"/>
              <path d="M13 5.5 A7.5 7.5 0 0 1 20.5 10" stroke="#f0a928" strokeWidth="1.2" strokeLinecap="round" fill="none"/>
              <circle cx="13" cy="13" r="3.5" stroke="#1e2830" strokeWidth="0.8"/>
              <circle cx="13" cy="13" r="2" fill="#00e5c8"/>
            </svg>
            BURNLENS
          </Link>
          <div className="lp-nav-right">
            <a href="#how">How it works</a>
            <a href="#pricing">Pricing</a>
            <a href="https://github.com/sairintechnologycom/burnlens#readme">Docs</a>
            <Link href="/dashboard" className="outline">Dashboard</Link>
            <Link href="/setup" className="primary">Get Started</Link>
          </div>
        </nav>

        {/* HERO: tagline + terminal */}
        <section className="lp-hero">
          <p className="lp-tagline">LLM FinOps · Open Source</p>
          <h1 className="lp-headline">
            See exactly what your <span className="acc">AI API calls</span> cost
          </h1>
          <p className="lp-subline">
            One command. Zero code changes. Every dollar tracked.
          </p>
          <TerminalAnimation onComplete={() => setTermDone(true)} />
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
                fontSize: 11, color: "#6b7785", letterSpacing: "0.06em"
              }}>
                localhost:8420/ui — your data never leaves your machine
              </p>
            </div>
          </>
        )}

        {/* EDITORIAL: how it works */}
        <div className="lp-editorial" id="how">
          <div className="lp-ed-section">
            <div className="lp-ed-label">Intercept</div>
            <div className="lp-ed-content">
              <h3>Set one env var. Done.</h3>
              <p>
                BurnLens runs a local proxy on <code>:8420</code>.
                Set <code>OPENAI_BASE_URL</code> or <code>ANTHROPIC_BASE_URL</code> and
                your existing SDK code routes through BurnLens automatically.
                Less than 20ms overhead. Streaming passthrough.
              </p>
            </div>
          </div>

          <div className="lp-ed-section">
            <div className="lp-ed-label">Attribute</div>
            <div className="lp-ed-content">
              <h3>Tag calls to features, teams, customers.</h3>
              <p>
                Add <code>X-BurnLens-Tag-Feature: search</code> headers to your requests.
                See cost per feature, per team, per customer. Know whether your
                summarizer costs more than your chatbot.
              </p>
            </div>
          </div>

          <div className="lp-ed-section">
            <div className="lp-ed-label">Optimize</div>
            <div className="lp-ed-content">
              <h3>5 rules find 40–60% waste automatically.</h3>
              <p>
                Model right-sizing, duplicate prompt detection, prompt caching
                opportunities, batch API candidates, and provider arbitrage.
                Each recommendation shows exact dollar savings.
              </p>
            </div>
          </div>

          <div className="lp-ed-section">
            <div className="lp-ed-label">Alert</div>
            <div className="lp-ed-content">
              <h3>Budget caps with teeth.</h3>
              <p>
                Per-team and per-customer monthly spend limits. Warning at 80%,
                hard 429 block at 100%. Slack webhooks or email — your call.
              </p>
            </div>
          </div>
        </div>

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
                <li>All 3 providers</li>
                <li>5 waste detection rules</li>
                <li>Budget alerts</li>
                <li>7-day history</li>
              </ul>
              <Link href="/setup" className="lp-plan-cta outline">Get Started</Link>
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
              <Link href="/setup" className="lp-plan-cta primary">Start Free Trial</Link>
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
              <Link href="/setup" className="lp-plan-cta outline">Get Started</Link>
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
              <a href="mailto:bhushan@burnlens.app" className="lp-plan-cta outline">Contact Us</a>
            </div>
          </div>
        </section>

        {/* WHAT'S NEW */}
        <section className="lp-whats-new">
          <h2 className="lp-wn-title">What&apos;s new in v1.0.1</h2>
          <div className="lp-wn-list">
            <div className="lp-wn-item">
              <span className="lp-wn-tag fix">Fixed</span>
              <span>Alert deduplication now persists across proxy restarts</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag new">New</span>
              <span>Google Cloud Billing API integration — Vertex AI + Gemini asset discovery</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag fix">Fixed</span>
              <span>Server-side asset sorting — global sort across all pages</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag fix">Fixed</span>
              <span>Monthly spend KPI now aggregates all assets, not just current page</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag new">New</span>
              <span>90-day discovery events archival with nightly cleanup</span>
            </div>
          </div>
        </section>

        {/* INSTALL CTA */}
        <section className="lp-install">
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
            <Link href="/setup" className="lp-btn-go">Get Started</Link>
            <a href="https://github.com/sairintechnologycom/burnlens" className="lp-btn-gh">View on GitHub</a>
          </div>
        </section>

        <footer className="lp-footer">
          BurnLens &copy; 2026 · Open Source · Self-Hosted
        </footer>
      </div>
    </>
  );
}

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
        <span className="term-dot" style={{ background: "var(--red)" }} />
        <span className="term-dot" style={{ background: "var(--amber)" }} />
        <span className="term-dot" style={{ background: "var(--green)" }} />
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
  const [menuOpen, setMenuOpen] = useState(false);

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
              <Link href="/dashboard" onClick={() => setMenuOpen(false)}>Dashboard</Link>
              <Link href="/setup" className="lp-mobile-cta" onClick={() => setMenuOpen(false)}>Get Started</Link>
            </div>
          </>
        )}

        {/* HERO: tagline + terminal */}
        <section className="lp-hero">
          <p className="lp-tagline">FinOps · Open Source · Multi-Provider</p>
          <h1 className="lp-headline">
            The open-source <span className="acc">FinOps proxy</span> for AI spend
          </h1>
          <p className="lp-subline">
            Track every dollar by feature, team, and customer across OpenAI, Anthropic, Google, Azure, AWS Bedrock, and Groq.
            Hard-cap budgets before the API call — not after the bill arrives.
          </p>
          <div className="lp-provider-strip">
            {["OpenAI", "Anthropic", "Google", "Azure", "AWS Bedrock", "Groq", "Mistral", "Together"].map((p) => (
              <span key={p} className="lp-provider-chip">{p}</span>
            ))}
            <span className="lp-provider-more">+ more</span>
          </div>
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
                fontSize: 11, color: "var(--l-muted)", letterSpacing: "0.06em"
              }}>
                localhost:8420/ui — your data never leaves your machine
              </p>
            </div>
          </>
        )}

        {/* THE PROBLEM */}
        <section className="lp-problem">
          <div className="lp-problem-grid">
            <div className="lp-problem-card">
              <div className="lp-problem-label">The bill</div>
              <h3>Bills tell you the model, not the why.</h3>
              <p>
                Your invoice says <code>gpt-4o: $4,287</code>. It doesn&apos;t say
                which feature, team, or customer burned it. By the time you trace
                the spike, it&apos;s already on next month&apos;s card.
              </p>
            </div>
            <div className="lp-problem-card">
              <div className="lp-problem-label">The damage</div>
              <h3>Alerts arrive after the damage.</h3>
              <p>
                A bad deploy, a runaway agent, or one abusive customer can trigger
                thousands of API calls before any dashboard turns red. You find out
                when you open the bill.
              </p>
            </div>
            <div className="lp-problem-card">
              <div className="lp-problem-label">The silos</div>
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
          <div className="lp-ed-section">
            <div className="lp-ed-label">01 · Drop-in proxy</div>
            <div className="lp-ed-content">
              <h3>Set one env var. Done.</h3>
              <p>
                BurnLens runs a local proxy on <code>:8420</code>. Set{" "}
                <code>OPENAI_BASE_URL</code> or <code>ANTHROPIC_BASE_URL</code> and
                your existing SDK code routes through automatically.
                Less than 20ms overhead. Full streaming passthrough.
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
                OpenAI, Anthropic, Google, Azure, Bedrock, and Groq spend in
                one view. Model breakdowns, waste detection, and budget tracking
                — all reconciled to the provider bill.
              </p>
            </div>
          </div>
        </div>

        {/* USE CASES */}
        <section className="lp-usecases">
          <h2>Built for every AI use case</h2>
          <div className="lp-usecases-grid">
            <div className="lp-usecase-card">
              <div className="lp-usecase-label">Coding agents</div>
              <h3>Per-PR, per-dev attribution</h3>
              <p>
                Cursor, Claude Code, Cline, Windsurf — see cost per repo, developer,
                or PR. Hard daily caps per API key stop one runaway agent from
                burning the team&apos;s monthly budget overnight.
              </p>
            </div>
            <div className="lp-usecase-card">
              <div className="lp-usecase-label">Customer-facing AI</div>
              <h3>Per-customer spend with 429 enforcement</h3>
              <p>
                Tag each request with a customer ID. See which customers drive the
                most cost. Enforce per-customer monthly spend limits — BurnLens
                returns 429 before the call is forwarded.
              </p>
            </div>
            <div className="lp-usecase-card">
              <div className="lp-usecase-label">RAG and agents</div>
              <h3>See what justifies the cost</h3>
              <p>
                Tag retrieval calls, tool calls, and generation separately. See
                whether your vector search or synthesis step is the cost driver —
                and whether it justifies the output quality.
              </p>
            </div>
            <div className="lp-usecase-card">
              <div className="lp-usecase-label">Internal tools</div>
              <h3>Per-team budgets that reconcile to the bill</h3>
              <p>
                Set per-team monthly budgets, get Slack alerts at 80% and 100%,
                and export monthly reports that reconcile line-by-line to the
                actual provider invoice.
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
                  <td className="yes">✓</td>
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
                <li>All 3 providers</li>
                <li>5 waste detection rules</li>
                <li>Budget alerts</li>
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

        {/* WHAT'S NEW */}
        <section className="lp-whats-new">
          <h2 className="lp-wn-title">What&apos;s new in v1.2.0</h2>
          <div className="lp-wn-list">
            <div className="lp-wn-item">
              <span className="lp-wn-tag new">New</span>
              <span><code>burnlens scan</code> — reads Claude Code, Cursor, Codex, and Gemini CLI local logs; imports cost history without a proxy</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag new">New</span>
              <span>Claude Code reader — parses <code>~/.claude/projects/</code> JSONL, deduplicates turns, attributes cost per session</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag new">New</span>
              <span>Cursor reader — imports spend from Cursor&apos;s local bubble DB with provider/model cost routing</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag new">New</span>
              <span>Codex reader — parses 700+ session SQLite DB; handles event_msg wrapper and turn_context model fields</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag new">New</span>
              <span>Gemini CLI reader — supports both JSON and JSONL chat formats from <code>~/.gemini/tmp/</code></span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag new">New</span>
              <span>Per-API-key daily hard cap — 50/80/100% alerts, HTTP 429 kill-switch at 100%, TZ-aware reset</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag new">New</span>
              <span>Git-aware auto-tagging — <code>burnlens run -- &lt;cmd&gt;</code> attributes every call to repo / dev / PR / branch</span>
            </div>
            <div className="lp-wn-item">
              <span className="lp-wn-tag fix">Fixed</span>
              <span>Google &amp; Anthropic streaming responses now log accurate token counts (no more 0-token rows)</span>
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

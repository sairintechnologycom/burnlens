"use client";

import Link from "next/link";

export default function LandingPage() {
  return (
    <>
      <style>{`
        .landing *, .landing *::before, .landing *::after { box-sizing: border-box; margin: 0; padding: 0; }

        .landing {
          --bg:       #080c10;
          --bg2:      #0e1318;
          --bg3:      #131920;
          --border:   #1e2830;
          --cyan:     #00e5c8;
          --cyan-dim: #00b89e;
          --amber:    #f0a928;
          --l-text:   #e8eaed;
          --l-muted:  #6b7785;
          --muted2:   #9aa3ae;
          min-height: 100vh;
          background: var(--bg);
          color: var(--l-text);
          font-family: var(--font-sans), 'DM Sans', sans-serif;
          font-size: 16px;
          line-height: 1.6;
        }

        /* ── NAV ── */
        .l-nav {
          position: fixed;
          top: 0; left: 0; right: 0;
          z-index: 100;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 40px;
          height: 60px;
          background: rgba(8,12,16,0.85);
          backdrop-filter: blur(12px);
          border-bottom: 1px solid var(--border);
        }

        .l-nav-logo {
          display: flex;
          align-items: center;
          gap: 10px;
          font-family: var(--font-sans), 'Syne', sans-serif;
          font-weight: 800;
          font-size: 15px;
          letter-spacing: 0.08em;
          color: var(--l-text);
          text-decoration: none;
        }

        .l-nav-links {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .l-nav-links a {
          color: var(--muted2);
          text-decoration: none;
          font-size: 14px;
          padding: 6px 14px;
          border-radius: 6px;
          transition: color 0.2s;
        }
        .l-nav-links a:hover { color: var(--l-text); }

        .l-btn-outline {
          border: 1px solid var(--border);
          color: var(--l-text) !important;
          border-radius: 6px;
        }
        .l-btn-outline:hover { border-color: var(--l-muted); }

        .l-btn-primary {
          background: var(--cyan);
          color: #080c10 !important;
          font-weight: 500;
          border-radius: 6px;
          padding: 7px 18px !important;
          transition: background 0.2s, transform 0.1s !important;
        }
        .l-btn-primary:hover { background: var(--cyan-dim) !important; }

        /* ── HERO ── */
        .l-hero {
          min-height: 100vh;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          text-align: center;
          padding: 80px 24px 60px;
          position: relative;
          overflow: hidden;
        }

        .l-hero::before {
          content: '';
          position: absolute;
          top: 30%;
          left: 50%;
          transform: translate(-50%, -50%);
          width: 700px;
          height: 400px;
          background: radial-gradient(ellipse, rgba(0,229,200,0.06) 0%, transparent 70%);
          pointer-events: none;
        }

        .l-hero-eyebrow {
          font-family: var(--font-mono), 'DM Mono', monospace;
          font-size: 11px;
          letter-spacing: 0.2em;
          color: var(--cyan);
          text-transform: uppercase;
          margin-bottom: 28px;
          opacity: 0;
          animation: l-fadeUp 0.6s ease 0.1s forwards;
        }

        .l-hero h1 {
          font-family: var(--font-sans), 'Syne', sans-serif;
          font-weight: 800;
          font-size: clamp(52px, 8vw, 88px);
          line-height: 1.0;
          letter-spacing: -0.02em;
          color: var(--l-text);
          max-width: 820px;
          opacity: 0;
          animation: l-fadeUp 0.6s ease 0.2s forwards;
        }

        .l-hero h1 .accent {
          color: var(--cyan);
          display: block;
        }

        .l-hero-sub {
          margin-top: 28px;
          font-size: 17px;
          color: var(--muted2);
          max-width: 480px;
          line-height: 1.7;
          opacity: 0;
          animation: l-fadeUp 0.6s ease 0.35s forwards;
        }

        .l-hero-cta {
          margin-top: 40px;
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
          justify-content: center;
          opacity: 0;
          animation: l-fadeUp 0.6s ease 0.5s forwards;
        }

        .l-cta-primary {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: var(--cyan);
          color: #080c10;
          font-weight: 500;
          font-size: 15px;
          padding: 12px 28px;
          border-radius: 8px;
          text-decoration: none;
          border: none;
          cursor: pointer;
          transition: background 0.2s, transform 0.1s;
        }
        .l-cta-primary:hover { background: var(--cyan-dim); transform: translateY(-1px); }

        .l-cta-secondary {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: transparent;
          color: var(--l-text);
          font-size: 15px;
          padding: 11px 24px;
          border-radius: 8px;
          text-decoration: none;
          border: 1px solid var(--border);
          cursor: pointer;
          transition: border-color 0.2s, transform 0.1s;
        }
        .l-cta-secondary:hover { border-color: var(--l-muted); transform: translateY(-1px); }

        .l-hero-trust {
          margin-top: 20px;
          display: flex;
          align-items: center;
          gap: 20px;
          opacity: 0;
          animation: l-fadeUp 0.6s ease 0.65s forwards;
        }

        .l-trust-item {
          font-family: var(--font-mono), 'DM Mono', monospace;
          font-size: 10px;
          letter-spacing: 0.18em;
          color: var(--l-muted);
          text-transform: uppercase;
        }

        .l-trust-dot {
          width: 3px;
          height: 3px;
          border-radius: 50%;
          background: var(--border);
          flex-shrink: 0;
        }

        /* ── DIVIDER ── */
        .l-divider {
          width: 100%;
          height: 1px;
          background: linear-gradient(90deg, transparent, var(--border), transparent);
        }

        /* ── STATS ── */
        .l-stats {
          padding: 60px 40px;
          background: var(--bg);
        }

        .l-stats-inner {
          max-width: 900px;
          margin: 0 auto;
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 0;
        }

        .l-stat-item {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          text-align: center;
          padding: 0 24px;
          position: relative;
        }

        .l-stat-item:not(:last-child)::after {
          content: '';
          position: absolute;
          right: 0;
          top: 50%;
          transform: translateY(-50%);
          height: 36px;
          width: 1px;
          background: var(--border);
        }

        .l-stat-number {
          font-family: var(--font-sans), 'Syne', sans-serif;
          font-weight: 700;
          font-size: 38px;
          color: var(--cyan);
          line-height: 1;
          letter-spacing: -0.02em;
        }

        .l-stat-label {
          font-family: var(--font-mono), 'DM Mono', monospace;
          font-size: 10px;
          letter-spacing: 0.16em;
          color: var(--l-muted);
          text-transform: uppercase;
          margin-top: 8px;
        }

        /* ── FEATURES ── */
        .l-features {
          padding: 80px 40px 100px;
          background: var(--bg);
        }

        .l-features-inner {
          max-width: 1040px;
          margin: 0 auto;
        }

        .l-section-label {
          font-family: var(--font-mono), 'DM Mono', monospace;
          font-size: 10px;
          letter-spacing: 0.2em;
          color: var(--cyan);
          text-transform: uppercase;
          text-align: center;
          margin-bottom: 14px;
        }

        .l-section-title {
          font-family: var(--font-sans), 'Syne', sans-serif;
          font-weight: 800;
          font-size: clamp(28px, 4vw, 40px);
          color: var(--l-text);
          text-align: center;
          margin-bottom: 56px;
          letter-spacing: -0.01em;
        }

        .l-cards-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 16px;
        }

        .l-card {
          background: var(--bg2);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 28px 28px 32px;
          display: flex;
          flex-direction: column;
          gap: 14px;
          transition: border-color 0.2s, transform 0.2s;
        }
        .l-card:hover {
          border-color: rgba(0,229,200,0.25);
          transform: translateY(-2px);
        }

        .l-card-icon {
          width: 32px;
          height: 32px;
          flex-shrink: 0;
        }

        .l-card-title {
          font-family: var(--font-sans), 'Syne', sans-serif;
          font-weight: 700;
          font-size: 16px;
          color: var(--l-text);
          line-height: 1.2;
        }

        .l-card-desc {
          font-size: 14px;
          color: var(--muted2);
          line-height: 1.65;
          flex: 1;
        }

        .l-card-desc code {
          font-family: var(--font-mono), 'DM Mono', monospace;
          font-size: 12px;
          color: var(--cyan);
        }

        /* ── INSTALL STRIP ── */
        .l-install-strip {
          padding: 72px 40px;
          background: var(--bg2);
          border-top: 1px solid var(--border);
          border-bottom: 1px solid var(--border);
          text-align: center;
        }

        .l-install-strip h2 {
          font-family: var(--font-sans), 'Syne', sans-serif;
          font-weight: 800;
          font-size: 32px;
          margin-bottom: 32px;
          letter-spacing: -0.01em;
          color: var(--l-text);
        }

        .l-code-block {
          display: inline-flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 6px;
          background: var(--bg3);
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 20px 32px;
          font-family: var(--font-mono), 'DM Mono', monospace;
          font-size: 14px;
        }

        .l-code-line {
          display: flex;
          align-items: center;
          gap: 12px;
          color: var(--l-text);
        }

        .l-code-prompt {
          color: var(--cyan);
          user-select: none;
        }

        .l-code-comment {
          color: var(--l-muted);
        }

        /* ── ANIMATIONS ── */
        @keyframes l-fadeUp {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }

        /* ── RESPONSIVE ── */
        @media (max-width: 768px) {
          .l-nav { padding: 0 20px; }
          .l-stats-inner { grid-template-columns: repeat(2, 1fr); gap: 32px 0; }
          .l-stat-item:nth-child(2)::after { display: none; }
          .l-cards-grid { grid-template-columns: 1fr; }
          .l-stats, .l-features { padding-left: 20px; padding-right: 20px; }
          .l-install-strip { padding: 48px 20px; }
        }
      `}</style>

      <div className="landing">
        {/* NAV */}
        <nav className="l-nav">
          <Link href="/" className="l-nav-logo">
            <svg className="logo-icon" width="26" height="26" viewBox="0 0 26 26" fill="none">
              <circle cx="13" cy="13" r="11.5" stroke="#2a3540" strokeWidth="1"/>
              <path d="M13 1.5 A11.5 11.5 0 0 1 24 8" stroke="#f0a928" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
              <circle cx="13" cy="13" r="7.5" stroke="#1e2830" strokeWidth="1"/>
              <path d="M13 5.5 A7.5 7.5 0 0 1 20.5 10" stroke="#f0a928" strokeWidth="1.2" strokeLinecap="round" fill="none"/>
              <circle cx="13" cy="13" r="3.5" stroke="#1e2830" strokeWidth="0.8"/>
              <circle cx="13" cy="13" r="2" fill="#00e5c8"/>
            </svg>
            BURNLENS
          </Link>
          <div className="l-nav-links">
            <a href="#features">Features</a>
            <Link href="/dashboard" className="l-btn-outline">Dashboard</Link>
            <a href="#install" className="l-btn-primary">Get Started</a>
          </div>
        </nav>

        {/* HERO */}
        <section className="l-hero">
          <p className="l-hero-eyebrow">LLM FinOps · Open Source · Zero Code Changes</p>
          <h1>
            Stop overpaying for
            <span className="accent">AI API calls</span>
          </h1>
          <p className="l-hero-sub">
            Connect Anthropic, OpenAI &amp; Google AI. See where every dollar goes.
            Cut costs 40–60% with automated recommendations.
          </p>
          <div className="l-hero-cta">
            <a href="#install" className="l-cta-primary">
              Get Started
            </a>
            <Link href="/dashboard" className="l-cta-secondary">
              Launch Dashboard
            </Link>
          </div>
          <div className="l-hero-trust">
            <span className="l-trust-item">Open Source</span>
            <span className="l-trust-dot"></span>
            <span className="l-trust-item">Self-Hosted</span>
            <span className="l-trust-dot"></span>
            <span className="l-trust-item">Full Privacy</span>
          </div>
        </section>

        <div className="l-divider"></div>

        {/* STATS */}
        <section className="l-stats">
          <div className="l-stats-inner">
            <div className="l-stat-item">
              <span className="l-stat-number">40–60%</span>
              <span className="l-stat-label">Avg cost reduction</span>
            </div>
            <div className="l-stat-item">
              <span className="l-stat-number">3 min</span>
              <span className="l-stat-label">Setup time</span>
            </div>
            <div className="l-stat-item">
              <span className="l-stat-number">3</span>
              <span className="l-stat-label">Providers</span>
            </div>
            <div className="l-stat-item">
              <span className="l-stat-number">5</span>
              <span className="l-stat-label">Optimization rules</span>
            </div>
          </div>
        </section>

        <div className="l-divider"></div>

        {/* FEATURES */}
        <section className="l-features" id="features">
          <div className="l-features-inner">
            <p className="l-section-label">Features</p>
            <h2 className="l-section-title">Built for builders who ship</h2>

            <div className="l-cards-grid">
              {/* Multi-Provider */}
              <div className="l-card">
                <svg className="l-card-icon" viewBox="0 0 32 32" fill="none">
                  <circle cx="16" cy="16" r="15" stroke="#1e2830" strokeWidth="1"/>
                  <path d="M8 16 A8 8 0 0 1 24 16" stroke="#00e5c8" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
                  <circle cx="16" cy="16" r="3" fill="#00e5c8" fillOpacity="0.2" stroke="#00e5c8" strokeWidth="1"/>
                  <circle cx="8"  cy="16" r="2" fill="#00e5c8"/>
                  <circle cx="24" cy="16" r="2" fill="#00e5c8"/>
                </svg>
                <div className="l-card-title">Multi-Provider</div>
                <div className="l-card-desc">Anthropic, OpenAI, Google AI — all proxied through a single endpoint, visible in one dashboard.</div>
              </div>

              {/* Cost by Feature */}
              <div className="l-card">
                <svg className="l-card-icon" viewBox="0 0 32 32" fill="none">
                  <rect x="4" y="20" width="6" height="8" rx="2" fill="#00e5c8" fillOpacity="0.25" stroke="#00e5c8" strokeWidth="1"/>
                  <rect x="13" y="14" width="6" height="14" rx="2" fill="#00e5c8" fillOpacity="0.45" stroke="#00e5c8" strokeWidth="1"/>
                  <rect x="22" y="7"  width="6" height="21" rx="2" fill="#00e5c8" stroke="#00e5c8" strokeWidth="1"/>
                </svg>
                <div className="l-card-title">Cost by Feature</div>
                <div className="l-card-desc">Tag API calls with <code>X-BurnLens-Tag-Feature</code>. Know the true cost of every product feature and team.</div>
              </div>

              {/* Smart Optimizer */}
              <div className="l-card">
                <svg className="l-card-icon" viewBox="0 0 32 32" fill="none">
                  <circle cx="16" cy="16" r="10" stroke="#1e2830" strokeWidth="1"/>
                  <circle cx="16" cy="16" r="6"  stroke="#00e5c8" strokeWidth="1" strokeDasharray="3 2"/>
                  <circle cx="16" cy="16" r="2"  fill="#f0a928"/>
                  <path d="M16 6 L16 10 M16 22 L16 26 M6 16 L10 16 M22 16 L26 16" stroke="#00e5c8" strokeWidth="1.2" strokeLinecap="round"/>
                </svg>
                <div className="l-card-title">Smart Optimizer</div>
                <div className="l-card-desc">Model downgrade suggestions, prompt caching detection, duplicate request alerts — all automatic.</div>
              </div>

              {/* Self-Hosted */}
              <div className="l-card">
                <svg className="l-card-icon" viewBox="0 0 32 32" fill="none">
                  <rect x="4" y="10" width="24" height="14" rx="3" stroke="#1e2830" strokeWidth="1"/>
                  <rect x="7" y="13" width="18" height="8" rx="2" fill="#00e5c8" fillOpacity="0.08" stroke="#00e5c8" strokeWidth="0.8"/>
                  <circle cx="10" cy="17" r="1.5" fill="#00e5c8"/>
                  <circle cx="14" cy="17" r="1.5" fill="#00e5c8" fillOpacity="0.5"/>
                  <path d="M16 24 L16 27 M12 27 L20 27" stroke="#1e2830" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
                <div className="l-card-title">Self-Hosted</div>
                <div className="l-card-desc">Runs on <code>localhost:8420</code>. SQLite storage. Data never leaves your machine. No account required.</div>
              </div>

              {/* Budget Alerts */}
              <div className="l-card">
                <svg className="l-card-icon" viewBox="0 0 32 32" fill="none">
                  <path d="M16 5 L28 26 L4 26 Z" stroke="#f0a928" strokeWidth="1.2" fill="#f0a928" fillOpacity="0.1" strokeLinejoin="round"/>
                  <line x1="16" y1="13" x2="16" y2="20" stroke="#f0a928" strokeWidth="1.5" strokeLinecap="round"/>
                  <circle cx="16" cy="23" r="1.2" fill="#f0a928"/>
                </svg>
                <div className="l-card-title">Budget Alerts</div>
                <div className="l-card-desc">Per-team and per-customer monthly spend caps. Warning at 80%, hard 429 block at 100%. Slack webhooks included.</div>
              </div>

              {/* Zero Code Changes */}
              <div className="l-card">
                <svg className="l-card-icon" viewBox="0 0 32 32" fill="none">
                  <path d="M10 12 L5 16 L10 20" stroke="#00e5c8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                  <path d="M22 12 L27 16 L22 20" stroke="#00e5c8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                  <line x1="19" y1="9" x2="13" y2="23" stroke="#00e5c8" strokeWidth="1.2" strokeLinecap="round" opacity="0.5"/>
                </svg>
                <div className="l-card-title">Zero Code Changes</div>
                <div className="l-card-desc">Set one env var: <code>OPENAI_BASE_URL</code>. Your existing SDK code works unchanged. &lt;20ms proxy overhead.</div>
              </div>
            </div>
          </div>
        </section>

        <div className="l-divider"></div>

        {/* INSTALL */}
        <section className="l-install-strip" id="install">
          <h2>Up in 3 commands</h2>
          <div className="l-code-block">
            <div className="l-code-line">
              <span className="l-code-prompt">$</span>
              <span>pip install burnlens</span>
            </div>
            <div className="l-code-line">
              <span className="l-code-prompt">$</span>
              <span>burnlens start</span>
            </div>
            <div className="l-code-line">
              <span className="l-code-prompt">#</span>
              <span className="l-code-comment">Dashboard at http://127.0.0.1:8420/ui</span>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

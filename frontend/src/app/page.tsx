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
      <style>{`
        .lp {
          --bg: #080c10; --bg2: #0e1318; --bg3: #131920; --border: #1e2830;
          --cyan: #00e5c8; --cyan-dim: #00b89e; --amber: #f0a928;
          --l-text: #e8eaed; --l-muted: #6b7785; --muted2: #9aa3ae;
          min-height: 100vh; background: var(--bg); color: var(--l-text);
          font-family: var(--font-sans), system-ui, sans-serif;
        }

        /* NAV */
        .lp-nav {
          position: fixed; top: 0; left: 0; right: 0; z-index: 100;
          display: flex; align-items: center; justify-content: space-between;
          padding: 0 40px; height: 56px;
          background: rgba(8,12,16,0.88); backdrop-filter: blur(12px);
          border-bottom: 1px solid var(--border);
        }
        .lp-nav-logo {
          display: flex; align-items: center; gap: 10px;
          font-weight: 800; font-size: 14px; letter-spacing: 0.08em; color: var(--l-text);
          text-decoration: none;
        }
        .lp-nav-right { display: flex; align-items: center; gap: 8px; }
        .lp-nav-right a {
          font-size: 13px; padding: 6px 14px; border-radius: 6px;
          color: var(--muted2); text-decoration: none; transition: color 0.15s;
        }
        .lp-nav-right a:hover { color: var(--l-text); }
        .lp-nav-right .outline { border: 1px solid var(--border); color: var(--l-text); }
        .lp-nav-right .primary {
          background: var(--cyan); color: #080c10; font-weight: 600;
          padding: 6px 16px; border: none;
        }
        .lp-nav-right .primary:hover { background: var(--cyan-dim); }

        /* HERO */
        .lp-hero {
          min-height: 100vh; display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          padding: 80px 24px 40px; text-align: center; position: relative;
        }
        .lp-hero::before {
          content: ''; position: absolute; top: 25%; left: 50%;
          transform: translate(-50%, -50%); width: 600px; height: 300px;
          background: radial-gradient(ellipse, rgba(0,229,200,0.04) 0%, transparent 70%);
          pointer-events: none;
        }
        .lp-tagline {
          font-family: var(--font-mono), monospace;
          font-size: 11px; letter-spacing: 0.18em; color: var(--cyan);
          text-transform: uppercase; margin-bottom: 24px;
          opacity: 0; animation: lp-fade 0.5s ease 0.1s forwards;
        }
        .lp-headline {
          font-weight: 800; font-size: clamp(32px, 5vw, 52px);
          line-height: 1.1; letter-spacing: -0.02em; color: var(--l-text);
          max-width: 640px; margin-bottom: 16px;
          opacity: 0; animation: lp-fade 0.5s ease 0.2s forwards;
        }
        .lp-headline .acc { color: var(--cyan); }
        .lp-subline {
          font-size: 16px; color: var(--muted2); max-width: 420px;
          line-height: 1.6; margin-bottom: 32px;
          opacity: 0; animation: lp-fade 0.5s ease 0.3s forwards;
        }

        /* TERMINAL */
        .term-window {
          width: 100%; max-width: 620px;
          background: #0a0e14; border: 1px solid var(--border);
          border-radius: 10px; overflow: hidden;
          box-shadow: 0 20px 60px rgba(0,0,0,0.5);
          opacity: 0; animation: lp-fade 0.5s ease 0.4s forwards;
        }
        .term-bar {
          display: flex; align-items: center; gap: 6px;
          padding: 10px 14px; background: #0d1117; border-bottom: 1px solid var(--border);
        }
        .term-dot { width: 10px; height: 10px; border-radius: 50%; }
        .term-bar-title {
          margin-left: auto; font-family: var(--font-mono), monospace;
          font-size: 10px; color: var(--l-muted); letter-spacing: 0.04em;
        }
        .term-body { padding: 16px 18px; min-height: 180px; }
        .term-line {
          font-family: var(--font-mono), monospace; font-size: 13px;
          color: var(--muted2); line-height: 1.8; display: flex; gap: 8px;
          animation: lp-line 0.15s ease forwards;
        }
        .term-highlight { color: var(--cyan); }
        .term-prompt { color: var(--cyan); user-select: none; min-width: 12px; }
        .term-indent { min-width: 12px; }
        .term-cursor {
          display: inline-block; width: 7px; height: 14px;
          background: var(--cyan); opacity: 0.7;
          animation: lp-blink 1s step-end infinite; margin-top: 4px;
        }
        @keyframes lp-blink { 50% { opacity: 0; } }
        @keyframes lp-line { from { opacity: 0; } to { opacity: 1; } }

        /* TRANSITION ARROW */
        .lp-transition {
          text-align: center; padding: 32px 0;
          opacity: 0; animation: lp-fade 0.4s ease 0.2s forwards;
        }
        .lp-transition svg { color: var(--l-muted); }

        /* DASHBOARD PREVIEW */
        .dash-preview {
          width: 100%; max-width: 900px; margin: 0 auto;
          background: var(--bg2); border: 1px solid var(--border);
          border-radius: 10px; overflow: hidden;
          box-shadow: 0 24px 80px rgba(0,0,0,0.5);
          opacity: 0; animation: lp-slideUp 0.6s ease forwards;
        }

        .dash-topbar {
          display: flex; align-items: center; height: 36px;
          border-bottom: 1px solid var(--border); padding: 0 12px;
          background: #0d1117; font-size: 10px;
        }
        .dash-topbar-left {
          display: flex; align-items: center; gap: 6px;
          padding-right: 16px; border-right: 1px solid var(--border);
        }
        .dash-topbar-brand {
          font-weight: 800; font-size: 10px; letter-spacing: 0.08em; color: var(--l-text);
        }
        .dash-topbar-nav {
          display: flex; gap: 2px; margin-left: 12px; flex: 1;
        }
        .dash-topbar-link {
          font-size: 10px; font-weight: 600; color: var(--l-muted);
          padding: 4px 8px; border-radius: 4px;
        }
        .dash-topbar-link.active { background: #1a2030; color: var(--l-text); }
        .dash-topbar-right {
          display: flex; align-items: center; gap: 6px;
        }
        .dash-live {
          display: flex; align-items: center; gap: 4px;
          font-family: var(--font-mono), monospace; font-size: 9px;
          color: var(--cyan); padding: 2px 8px;
          background: rgba(0,229,200,0.06); border: 1px solid rgba(0,229,200,0.15);
          border-radius: 10px;
        }
        .dash-live-dot {
          width: 4px; height: 4px; border-radius: 50%;
          background: var(--cyan); animation: lp-blink 2s ease-in-out infinite;
        }
        .dash-period {
          font-family: var(--font-mono), monospace; font-size: 9px;
          padding: 2px 6px; border-radius: 3px; color: var(--l-muted);
        }
        .dash-period.active { background: var(--l-text); color: var(--bg); }

        /* Stats strip */
        .dash-stats {
          display: grid; grid-template-columns: repeat(4, 1fr);
          border-bottom: 1px solid var(--border);
        }
        .dash-stat {
          padding: 12px 14px; border-right: 1px solid var(--border);
        }
        .dash-stat:last-child { border-right: none; }
        .dash-stat-label {
          font-family: var(--font-mono), monospace;
          font-size: 8px; text-transform: uppercase;
          letter-spacing: 0.12em; color: var(--l-muted); margin-bottom: 2px;
        }
        .dash-stat-value {
          font-family: var(--font-mono), monospace;
          font-size: 16px; font-weight: 500; color: var(--l-text);
        }
        .dash-stat-value.cyan { color: var(--cyan); }
        .dash-stat-value.amber { color: var(--amber); }
        .dash-stat-delta {
          font-family: var(--font-mono), monospace;
          font-size: 9px; color: var(--l-muted); margin-top: 1px;
        }
        .dash-stat-delta.down { color: #22c98a; }

        /* Chart + Models */
        .dash-body {
          display: grid; grid-template-columns: 1fr 240px;
        }
        .dash-chart-section {
          border-right: 1px solid var(--border); padding: 0;
        }
        .dash-models-section { padding: 0; }
        .dash-section-header {
          font-family: var(--font-mono), monospace;
          font-size: 8px; text-transform: uppercase;
          letter-spacing: 0.14em; color: var(--l-muted);
          padding: 8px 14px; background: #0d1117;
          border-bottom: 1px solid var(--border);
        }
        .dash-bars {
          display: flex; align-items: flex-end; gap: 4px;
          padding: 16px 14px; height: 120px;
        }
        .dash-bar-col {
          flex: 1; height: 100%; display: flex;
          align-items: flex-end; justify-content: center;
        }
        .dash-bar {
          width: 100%; border-radius: 2px 2px 0 0;
          background: rgba(0,229,200,0.2);
          border-top: 2px solid var(--cyan);
          animation: lp-barGrow 0.4s ease forwards;
          transform-origin: bottom;
        }
        @keyframes lp-barGrow { from { transform: scaleY(0); } to { transform: scaleY(1); } }

        .dash-model-row {
          display: grid; grid-template-columns: 14px 1fr auto;
          gap: 6px; align-items: center;
          padding: 8px 14px; border-bottom: 1px solid var(--border);
        }
        .dash-model-rank {
          font-family: var(--font-mono), monospace;
          font-size: 9px; color: #2a3347;
        }
        .dash-model-info { min-width: 0; }
        .dash-model-name {
          font-size: 11px; font-weight: 600; color: var(--l-text);
          display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .dash-model-bar-bg {
          height: 2px; background: var(--border); border-radius: 1px; margin-top: 3px;
        }
        .dash-model-bar-fill {
          height: 100%; background: var(--cyan); border-radius: 1px;
        }
        .dash-model-cost {
          font-family: var(--font-mono), monospace;
          font-size: 10px; color: var(--l-muted);
        }

        /* EDITORIAL SECTIONS */
        .lp-editorial {
          max-width: 640px; margin: 0 auto;
          padding: 100px 24px 80px;
        }
        .lp-ed-section {
          margin-bottom: 72px;
          display: grid; grid-template-columns: 120px 1fr; gap: 24px;
          align-items: start;
        }
        .lp-ed-label {
          font-family: var(--font-mono), monospace;
          font-size: 10px; letter-spacing: 0.16em;
          color: var(--cyan); text-transform: uppercase;
          padding-top: 4px;
        }
        .lp-ed-content h3 {
          font-weight: 700; font-size: 18px; color: var(--l-text);
          margin-bottom: 8px; line-height: 1.3;
        }
        .lp-ed-content p {
          font-size: 14px; color: var(--muted2); line-height: 1.7;
        }
        .lp-ed-content code {
          font-family: var(--font-mono), monospace;
          font-size: 12px; color: var(--cyan);
          background: rgba(0,229,200,0.06); padding: 2px 6px;
          border-radius: 3px;
        }

        /* INSTALL CTA */
        .lp-install {
          text-align: center; padding: 72px 24px;
          border-top: 1px solid var(--border);
          background: var(--bg2);
        }
        .lp-install h2 {
          font-weight: 800; font-size: 28px; margin-bottom: 24px;
          color: var(--l-text);
        }
        .lp-install-code {
          display: inline-flex; flex-direction: column;
          align-items: flex-start; gap: 4px;
          background: var(--bg3); border: 1px solid var(--border);
          border-radius: 8px; padding: 18px 28px;
          font-family: var(--font-mono), monospace; font-size: 14px;
          margin-bottom: 28px;
        }
        .lp-install-line {
          display: flex; gap: 10px; color: var(--l-text);
        }
        .lp-install-prompt { color: var(--cyan); user-select: none; }
        .lp-install-comment { color: var(--l-muted); }
        .lp-install-cta {
          display: flex; gap: 12px; justify-content: center; margin-top: 24px;
        }
        .lp-install-cta a {
          font-size: 14px; padding: 10px 24px; border-radius: 8px;
          text-decoration: none; font-weight: 500; transition: all 0.15s;
        }
        .lp-btn-go {
          background: var(--cyan); color: #080c10;
        }
        .lp-btn-go:hover { background: var(--cyan-dim); }
        .lp-btn-gh {
          border: 1px solid var(--border); color: var(--l-text);
        }
        .lp-btn-gh:hover { border-color: var(--l-muted); }

        /* FOOTER */
        .lp-footer {
          padding: 24px; text-align: center;
          font-family: var(--font-mono), monospace;
          font-size: 10px; color: #2a3347;
          border-top: 1px solid var(--border);
        }

        @keyframes lp-fade {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes lp-slideUp {
          from { opacity: 0; transform: translateY(24px); }
          to { opacity: 1; transform: translateY(0); }
        }

        /* PRICING */
        .lp-pricing {
          max-width: 960px; margin: 0 auto; padding: 80px 24px;
          border-top: 1px solid var(--border);
        }
        .lp-pricing-title {
          font-weight: 800; font-size: 28px; text-align: center;
          color: var(--l-text); margin-bottom: 8px;
        }
        .lp-pricing-sub {
          text-align: center; font-size: 14px; color: var(--muted2);
          margin-bottom: 40px;
        }
        .lp-pricing-grid {
          display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
        }
        .lp-plan {
          background: var(--bg2); border: 1px solid var(--border);
          border-radius: 10px; padding: 24px 20px; position: relative;
          display: flex; flex-direction: column;
        }
        .lp-plan.featured { border-color: var(--cyan); }
        .lp-plan-badge {
          position: absolute; top: -10px; left: 50%; transform: translateX(-50%);
          background: var(--cyan); color: #080c10; font-size: 10px;
          font-weight: 700; padding: 2px 12px; border-radius: 10px;
          letter-spacing: 0.04em;
        }
        .lp-plan-name {
          font-weight: 700; font-size: 16px; color: var(--l-text); margin-bottom: 8px;
        }
        .lp-plan-price {
          font-family: var(--font-mono), monospace;
          font-size: 28px; font-weight: 700; color: var(--l-text); margin-bottom: 16px;
        }
        .lp-plan-price span { font-size: 13px; color: var(--l-muted); font-weight: 400; }
        .lp-plan-features {
          list-style: none; flex: 1; margin-bottom: 20px;
        }
        .lp-plan-features li {
          font-size: 13px; color: var(--muted2); line-height: 2;
          padding-left: 16px; position: relative;
        }
        .lp-plan-features li::before {
          content: '\2713'; position: absolute; left: 0; color: var(--cyan); font-size: 11px;
        }
        .lp-plan-cta {
          display: block; text-align: center; padding: 8px 16px;
          border-radius: 6px; font-size: 13px; font-weight: 600;
          text-decoration: none; transition: all 0.15s;
        }
        .lp-plan-cta.outline {
          border: 1px solid var(--border); color: var(--l-text);
        }
        .lp-plan-cta.outline:hover { border-color: var(--l-muted); }
        .lp-plan-cta.primary {
          background: var(--cyan); color: #080c10; border: none;
        }
        .lp-plan-cta.primary:hover { background: var(--cyan-dim); }

        /* WHAT'S NEW */
        .lp-whats-new {
          max-width: 640px; margin: 0 auto; padding: 60px 24px 80px;
        }
        .lp-wn-title {
          font-weight: 800; font-size: 22px; text-align: center;
          color: var(--l-text); margin-bottom: 24px;
        }
        .lp-wn-list {
          display: flex; flex-direction: column; gap: 10px;
        }
        .lp-wn-item {
          display: flex; align-items: center; gap: 10px;
          font-size: 13px; color: var(--muted2);
          padding: 8px 14px; background: var(--bg2);
          border: 1px solid var(--border); border-radius: 6px;
        }
        .lp-wn-tag {
          font-family: var(--font-mono), monospace;
          font-size: 9px; font-weight: 700; letter-spacing: 0.08em;
          text-transform: uppercase; padding: 2px 8px;
          border-radius: 3px; flex-shrink: 0;
        }
        .lp-wn-tag.fix { background: rgba(34,201,138,0.12); color: #22c98a; }
        .lp-wn-tag.new { background: rgba(0,229,200,0.12); color: var(--cyan); }

        @media (max-width: 768px) {
          .lp-nav { padding: 0 16px; }
          .lp-ed-section { grid-template-columns: 1fr; gap: 8px; }
          .dash-body { grid-template-columns: 1fr; }
          .dash-models-section { border-top: 1px solid var(--border); }
          .dash-stats { grid-template-columns: repeat(2, 1fr); }
          .dash-stat:nth-child(2) { border-right: none; }
          .dash-topbar-nav { display: none; }
          .lp-pricing-grid { grid-template-columns: 1fr; max-width: 360px; margin: 0 auto; }
        }
      `}</style>

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
            <a href="https://github.com/bhushan/burnlens#readme">Docs</a>
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
            <a href="https://github.com/bhushan/burnlens" className="lp-btn-gh">View on GitHub</a>
          </div>
        </section>

        <footer className="lp-footer">
          BurnLens &copy; 2026 · Open Source · Self-Hosted
        </footer>
      </div>
    </>
  );
}

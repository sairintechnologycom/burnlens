"use client";

import { useState, useEffect, Suspense, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function isLocalBackend(): boolean {
  try {
    const url = new URL(API_BASE);
    const host = url.hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0";
  } catch {
    return true;
  }
}

function SetupContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isExpired = searchParams.get("expired") === "1";
  const [mode, setMode] = useState<"enter" | "register">("enter");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);

  // If running locally, redirect straight to dashboard
  useEffect(() => {
    if (isLocalBackend()) {
      router.replace("/dashboard");
    }
  }, [router]);
  const [error, setError] = useState("");

  const [regName, setRegName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [generatedKey, setGeneratedKey] = useState("");
  const [copied, setCopied] = useState(false);

  const validateKey = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await fetch(`${API_BASE}/api/v1/orgs/me`, {
        headers: { "X-API-Key": apiKey },
      });
      if (!resp.ok) throw new Error("Invalid API key");
      const data = await resp.json();
      localStorage.setItem("burnlens_api_key", apiKey);
      localStorage.setItem("burnlens_org_id", data.org_id);
      localStorage.setItem("burnlens_org_name", data.name);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Could not validate API key");
    } finally {
      setLoading(false);
    }
  }, [apiKey, router]);

  const handleRegister = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const resp = await fetch(`${API_BASE}/api/v1/orgs/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: regName, email: regEmail }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({ detail: "Registration failed" }));
        throw new Error(data.detail);
      }
      const data = await resp.json();
      setGeneratedKey(data.api_key);
      localStorage.setItem("burnlens_api_key", data.api_key);
      localStorage.setItem("burnlens_org_id", data.org_id);
      localStorage.setItem("burnlens_org_name", regName);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [regName, regEmail]);

  const copyKey = useCallback(() => {
    navigator.clipboard.writeText(generatedKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [generatedKey]);

  return (
    <>
      <style>{`
        .sp {
          --bg: #080c10; --bg2: #0e1318; --bg3: #131920; --border: #1e2830;
          --cyan: #00e5c8; --cyan-dim: #00b89e; --amber: #f0a928;
          --s-text: #e8eaed; --s-muted: #6b7785; --s-red: #f04060;
          min-height: 100vh; background: var(--bg);
          display: flex; flex-direction: column;
          font-family: var(--font-sans), system-ui, sans-serif;
          color: var(--s-text);
        }

        /* Top bar */
        .sp-topbar {
          display: flex; align-items: center; justify-content: space-between;
          padding: 0 32px; height: 56px;
          border-bottom: 1px solid var(--border);
        }
        .sp-logo {
          display: flex; align-items: center; gap: 8px;
          font-weight: 800; font-size: 14px; letter-spacing: 0.08em;
          color: var(--s-text); text-decoration: none;
        }
        .sp-back {
          display: flex; align-items: center; gap: 6px;
          font-family: var(--font-mono), monospace;
          font-size: 12px; color: var(--s-muted);
          text-decoration: none; transition: color 0.15s;
        }
        .sp-back:hover { color: var(--s-text); }

        /* Main area */
        .sp-main {
          flex: 1; display: grid; grid-template-columns: 1fr 1fr;
        }

        /* Left side — branding */
        .sp-left {
          display: flex; flex-direction: column; justify-content: center;
          padding: 64px; border-right: 1px solid var(--border);
          background: var(--bg2); position: relative; overflow: hidden;
        }
        .sp-left::before {
          content: ''; position: absolute; top: 30%; left: 50%;
          transform: translate(-50%, -50%); width: 500px; height: 300px;
          background: radial-gradient(ellipse, rgba(0,229,200,0.04) 0%, transparent 70%);
          pointer-events: none;
        }
        .sp-left h2 {
          font-weight: 800; font-size: 32px; line-height: 1.15;
          letter-spacing: -0.02em; color: var(--s-text);
          margin-bottom: 16px; position: relative;
        }
        .sp-left h2 .acc { color: var(--cyan); }
        .sp-left p {
          font-size: 15px; color: var(--s-muted); line-height: 1.65;
          max-width: 340px; position: relative;
        }
        .sp-left-features {
          margin-top: 40px; display: flex; flex-direction: column; gap: 16px;
          position: relative;
        }
        .sp-left-feat {
          display: flex; align-items: center; gap: 12px;
        }
        .sp-left-feat-dot {
          width: 6px; height: 6px; border-radius: 50%;
          background: var(--cyan); flex-shrink: 0;
        }
        .sp-left-feat span {
          font-family: var(--font-mono), monospace;
          font-size: 12px; color: var(--s-muted); letter-spacing: 0.02em;
        }

        /* Right side — form */
        .sp-right {
          display: flex; align-items: center; justify-content: center;
          padding: 64px 48px;
        }
        .sp-form-area {
          width: 100%; max-width: 380px;
        }

        /* Tab switcher */
        .sp-tabs {
          display: flex; gap: 0; margin-bottom: 32px;
          border: 1px solid var(--border); border-radius: 6px; overflow: hidden;
        }
        .sp-tab {
          flex: 1; padding: 8px 0; text-align: center;
          font-family: var(--font-mono), monospace;
          font-size: 11px; font-weight: 500; letter-spacing: 0.04em;
          color: var(--s-muted); background: var(--bg);
          border: none; cursor: pointer; transition: all 0.15s;
        }
        .sp-tab.active {
          background: var(--bg3); color: var(--s-text);
        }
        .sp-tab:first-child { border-right: 1px solid var(--border); }

        .sp-form-title {
          font-weight: 700; font-size: 20px; color: var(--s-text);
          margin-bottom: 4px;
        }
        .sp-form-sub {
          font-size: 13px; color: var(--s-muted); margin-bottom: 24px;
        }

        /* Inputs */
        .sp-label {
          display: block; font-family: var(--font-mono), monospace;
          font-size: 9px; text-transform: uppercase; letter-spacing: 0.12em;
          color: var(--s-muted); margin-bottom: 6px;
        }
        .sp-input {
          width: 100%; background: var(--bg); border: 1px solid var(--border);
          border-radius: 6px; padding: 10px 14px; color: var(--s-text);
          font-family: var(--font-mono), monospace; font-size: 13px;
          transition: border-color 0.15s; outline: none;
        }
        .sp-input:focus { border-color: var(--cyan); }
        .sp-input::placeholder { color: #2a3540; }

        .sp-field { margin-bottom: 16px; }

        /* Buttons */
        .sp-btn-primary {
          width: 100%; padding: 11px 0; border: none; border-radius: 6px;
          background: var(--cyan); color: #080c10;
          font-weight: 600; font-size: 14px; cursor: pointer;
          transition: background 0.15s;
        }
        .sp-btn-primary:hover { background: var(--cyan-dim); }
        .sp-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

        /* Error */
        .sp-error {
          padding: 10px 14px; border-radius: 6px; margin-bottom: 16px;
          background: rgba(240,64,96,0.08); border: 1px solid rgba(240,64,96,0.2);
          color: var(--s-red); font-size: 12px;
        }

        /* Warning */
        .sp-warning {
          padding: 10px 14px; border-radius: 6px; margin-bottom: 16px;
          background: rgba(240,169,40,0.08); border: 1px solid rgba(240,169,40,0.2);
          color: var(--amber); font-size: 12px;
        }

        /* Generated key */
        .sp-key-row {
          display: flex; gap: 8px; margin-bottom: 12px;
        }
        .sp-key-input {
          flex: 1; background: var(--bg); border: 1px solid var(--border);
          border-radius: 6px; padding: 10px 14px; color: var(--cyan);
          font-family: var(--font-mono), monospace; font-size: 12px;
          outline: none;
        }
        .sp-btn-copy {
          padding: 0 16px; border: 1px solid var(--border); border-radius: 6px;
          background: var(--bg); color: var(--s-muted);
          font-family: var(--font-mono), monospace; font-size: 11px;
          cursor: pointer; transition: all 0.15s; white-space: nowrap;
        }
        .sp-btn-copy:hover { border-color: var(--cyan); color: var(--cyan); }

        .sp-code-block {
          background: var(--bg); border: 1px solid var(--border);
          border-radius: 6px; padding: 14px 16px; margin-bottom: 12px;
          font-family: var(--font-mono), monospace; font-size: 11px;
          color: var(--cyan); line-height: 1.8; overflow-x: auto;
        }

        .sp-success-icon {
          width: 48px; height: 48px; border-radius: 50%;
          background: rgba(0,229,200,0.08); border: 1px solid rgba(0,229,200,0.2);
          display: flex; align-items: center; justify-content: center;
          margin-bottom: 20px;
        }

        /* Footer */
        .sp-footer {
          padding: 16px 32px; border-top: 1px solid var(--border);
          display: flex; align-items: center; justify-content: center; gap: 20px;
        }
        .sp-footer span {
          font-family: var(--font-mono), monospace;
          font-size: 10px; letter-spacing: 0.12em;
          color: #2a3347; text-transform: uppercase;
        }
        .sp-footer-dot {
          width: 3px; height: 3px; border-radius: 50%; background: #1e2830;
        }

        @media (max-width: 768px) {
          .sp-main { grid-template-columns: 1fr; }
          .sp-left { display: none; }
          .sp-right { padding: 32px 24px; }
          .sp-topbar { padding: 0 16px; }
        }
      `}</style>

      <div className="sp">
        {/* Top bar */}
        <div className="sp-topbar">
          <Link href="/" className="sp-logo">
            <svg width="20" height="20" viewBox="0 0 26 26" fill="none">
              <circle cx="13" cy="13" r="11.5" stroke="#2a3540" strokeWidth="1"/>
              <path d="M13 1.5 A11.5 11.5 0 0 1 24 8" stroke="#f0a928" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
              <circle cx="13" cy="13" r="7.5" stroke="#1e2830" strokeWidth="1"/>
              <circle cx="13" cy="13" r="2" fill="#00e5c8"/>
            </svg>
            BURNLENS
          </Link>
          <Link href="/" className="sp-back">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M10 4L6 8l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Back to home
          </Link>
        </div>

        <div className="sp-main">
          {/* Left branding panel */}
          <div className="sp-left">
            <h2>
              See where every<br />
              <span className="acc">AI dollar</span> goes
            </h2>
            <p>
              Connect your LLM providers in 30 seconds.
              Zero code changes, full cost visibility.
            </p>
            <div className="sp-left-features">
              <div className="sp-left-feat">
                <span className="sp-left-feat-dot" />
                <span>Multi-provider: Anthropic, OpenAI, Google AI</span>
              </div>
              <div className="sp-left-feat">
                <span className="sp-left-feat-dot" />
                <span>Cost attribution by feature, team, customer</span>
              </div>
              <div className="sp-left-feat">
                <span className="sp-left-feat-dot" />
                <span>Automated waste detection and alerts</span>
              </div>
              <div className="sp-left-feat">
                <span className="sp-left-feat-dot" />
                <span>Self-hosted — data never leaves your machine</span>
              </div>
            </div>
          </div>

          {/* Right form panel */}
          <div className="sp-right">
            <div className="sp-form-area">
              {generatedKey ? (
                /* ── Success state ── */
                <>
                  <div className="sp-success-icon">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                      <path d="M5 10l4 4 6-8" stroke="#00e5c8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </div>
                  <div className="sp-form-title">You&apos;re in</div>
                  <div className="sp-form-sub">Save your API key — you won&apos;t see it again.</div>

                  <div className="sp-field">
                    <label className="sp-label">Your API key</label>
                    <div className="sp-key-row">
                      <input className="sp-key-input" readOnly value={generatedKey} />
                      <button className="sp-btn-copy" onClick={copyKey}>
                        {copied ? "Copied" : "Copy"}
                      </button>
                    </div>
                  </div>

                  <div className="sp-field">
                    <label className="sp-label">Add to burnlens.yaml</label>
                    <pre className="sp-code-block">
{`cloud:
  enabled: true
  api_key: "${generatedKey}"
  endpoint: "${API_BASE}"`}
                    </pre>
                  </div>

                  <div className="sp-warning">
                    This key grants full access. Store it securely.
                  </div>

                  <button
                    className="sp-btn-primary"
                    onClick={() => router.push("/dashboard")}
                  >
                    Open Dashboard
                  </button>
                </>
              ) : (
                /* ── Login / Register ── */
                <>
                  {isExpired && (
                    <div className="sp-warning">
                      Session expired. Please sign in again.
                    </div>
                  )}

                  <div className="sp-tabs">
                    <button
                      className={`sp-tab ${mode === "enter" ? "active" : ""}`}
                      onClick={() => { setMode("enter"); setError(""); }}
                    >
                      Sign in
                    </button>
                    <button
                      className={`sp-tab ${mode === "register" ? "active" : ""}`}
                      onClick={() => { setMode("register"); setError(""); }}
                    >
                      Register
                    </button>
                  </div>

                  {error && <div className="sp-error">{error}</div>}

                  {mode === "enter" ? (
                    <>
                      <div className="sp-form-title">Welcome back</div>
                      <div className="sp-form-sub">Enter your API key to access the dashboard.</div>

                      <div className="sp-field">
                        <label className="sp-label">API key</label>
                        <input
                          type="password"
                          className="sp-input"
                          placeholder="bl_live_..."
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter" && apiKey) validateKey(); }}
                        />
                      </div>

                      <button
                        className="sp-btn-primary"
                        onClick={validateKey}
                        disabled={loading || !apiKey}
                      >
                        {loading ? "Connecting..." : "Connect"}
                      </button>
                    </>
                  ) : (
                    <form onSubmit={handleRegister}>
                      <div className="sp-form-title">Create your org</div>
                      <div className="sp-form-sub">Start tracking LLM costs in under a minute.</div>

                      <div className="sp-field">
                        <label className="sp-label">Organization name</label>
                        <input
                          type="text"
                          required
                          className="sp-input"
                          placeholder="Acme Engineering"
                          value={regName}
                          onChange={(e) => setRegName(e.target.value)}
                          style={{ fontFamily: "var(--font-sans), system-ui" }}
                        />
                      </div>

                      <div className="sp-field">
                        <label className="sp-label">Email</label>
                        <input
                          type="email"
                          required
                          className="sp-input"
                          placeholder="eng@acme.com"
                          value={regEmail}
                          onChange={(e) => setRegEmail(e.target.value)}
                        />
                      </div>

                      <button
                        type="submit"
                        className="sp-btn-primary"
                        disabled={loading}
                      >
                        {loading ? "Creating..." : "Create Organization"}
                      </button>
                    </form>
                  )}
                </>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="sp-footer">
          <span>Open source</span>
          <span className="sp-footer-dot" />
          <span>Self-hosted</span>
          <span className="sp-footer-dot" />
          <span>Full privacy</span>
        </div>
      </div>
    </>
  );
}

export default function SetupPage() {
  return (
    <Suspense fallback={
      <div style={{
        minHeight: "100vh", background: "#080c10",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <div className="skeleton" style={{ width: 32, height: 32, borderRadius: "50%" }} />
      </div>
    }>
      <SetupContent />
    </Suspense>
  );
}

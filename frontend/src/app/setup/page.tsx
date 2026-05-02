"use client";

import { useState, useEffect, Suspense, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { BASE_URL } from "@/lib/api";

function isLocalBackend(): boolean {
  try {
    const url = new URL(BASE_URL);
    const host = url.hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0";
  } catch {
    return true;
  }
}

function storeSession(data: {
  token: string;
  workspace: { id: string; name: string; plan: string; api_key: string };
}) {
  // C-3: the JWT is set by the backend as the `burnlens_session` HttpOnly
  // cookie — we intentionally DO NOT persist `data.token` client-side.
  // Only non-sensitive workspace metadata goes to localStorage, used by
  // useAuth to hydrate the session hint on page load.
  localStorage.setItem("burnlens_workspace_id", data.workspace.id);
  localStorage.setItem("burnlens_workspace_name", data.workspace.name);
  localStorage.setItem("burnlens_plan", data.workspace.plan);
  localStorage.setItem("burnlens_api_key", data.workspace.api_key);
  // Clean up legacy JWT if a previous (pre-C-3) session left one behind.
  localStorage.removeItem("burnlens_token");
}

function SetupContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isExpired = searchParams.get("expired") === "1";
  const [mode, setMode] = useState<"login" | "register">("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Login fields
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Register fields
  const [regName, setRegName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");

  useEffect(() => {
    if (isLocalBackend()) {
      router.replace("/dashboard");
    }
  }, [router]);

  const handleLogin = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await fetch(`${BASE_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        credentials: "include",
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({ detail: "Login failed" }));
        throw new Error(data.detail || "Login failed");
      }
      const data = await resp.json();
      storeSession(data);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [email, password, router]);

  const handleRegister = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const resp = await fetch(`${BASE_URL}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: regEmail,
          password: regPassword,
          workspace_name: regName,
        }),
        credentials: "include",
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({ detail: "Registration failed" }));
        throw new Error(data.detail || "Registration failed");
      }
      const data = await resp.json();
      storeSession(data);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [regName, regEmail, regPassword, router]);

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
        .sp-main {
          flex: 1; display: grid; grid-template-columns: 1fr 1fr;
        }
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
        .sp-right {
          display: flex; align-items: center; justify-content: center;
          padding: 64px 48px;
        }
        .sp-form-area { width: 100%; max-width: 380px; }
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
        .sp-tab.active { background: var(--bg3); color: var(--s-text); }
        .sp-tab:first-child { border-right: 1px solid var(--border); }
        .sp-form-title {
          font-weight: 700; font-size: 20px; color: var(--s-text);
          margin-bottom: 4px;
        }
        .sp-form-sub {
          font-size: 13px; color: var(--s-muted); margin-bottom: 24px;
        }
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
        .sp-btn-primary {
          width: 100%; padding: 11px 0; border: none; border-radius: 6px;
          background: var(--cyan); color: var(--bg);
          font-weight: 600; font-size: 14px; cursor: pointer;
          transition: background 0.15s;
        }
        .sp-btn-primary:hover { background: var(--cyan-dim); }
        .sp-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
        .sp-error {
          padding: 10px 14px; border-radius: 6px; margin-bottom: 16px;
          background: rgba(240,64,96,0.08); border: 1px solid rgba(240,64,96,0.2);
          color: var(--s-red); font-size: 12px;
        }
        .sp-warning {
          padding: 10px 14px; border-radius: 6px; margin-bottom: 16px;
          background: rgba(240,169,40,0.08); border: 1px solid rgba(240,169,40,0.2);
          color: var(--amber); font-size: 12px;
        }
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
          width: 3px; height: 3px; border-radius: 50%; background: var(--border);
        }
        @media (max-width: 768px) {
          .sp-main { grid-template-columns: 1fr; }
          .sp-left { display: none; }
          .sp-right { padding: 32px 24px; }
          .sp-topbar { padding: 0 16px; }
        }
      `}</style>

      <div className="sp">
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

          <div className="sp-right">
            <div className="sp-form-area">
              {isExpired && (
                <div className="sp-warning">
                  Session expired. Please sign in again.
                </div>
              )}

              <div className="sp-tabs">
                <button
                  className={`sp-tab ${mode === "login" ? "active" : ""}`}
                  onClick={() => { setMode("login"); setError(""); }}
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

              {mode === "login" ? (
                <>
                  <div className="sp-form-title">Welcome back</div>
                  <div className="sp-form-sub">Sign in to access your dashboard.</div>

                  <div className="sp-field">
                    <label className="sp-label">Email</label>
                    <input
                      type="email"
                      className="sp-input"
                      placeholder="you@company.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && email && password) handleLogin(); }}
                    />
                  </div>

                  <div className="sp-field">
                    <label className="sp-label">Password</label>
                    <input
                      type="password"
                      className="sp-input"
                      placeholder="••••••••"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && email && password) handleLogin(); }}
                    />
                  </div>

                  <button
                    className="sp-btn-primary"
                    onClick={handleLogin}
                    disabled={loading || !email || !password}
                  >
                    {loading ? "Signing in..." : "Sign in"}
                  </button>
                </>
              ) : (
                <form onSubmit={handleRegister}>
                  <div className="sp-form-title">Create your workspace</div>
                  <div className="sp-form-sub">Start tracking LLM costs in under a minute.</div>

                  <div className="sp-field">
                    <label className="sp-label">Workspace name</label>
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
                      placeholder="you@company.com"
                      value={regEmail}
                      onChange={(e) => setRegEmail(e.target.value)}
                    />
                  </div>

                  <div className="sp-field">
                    <label className="sp-label">Password</label>
                    <input
                      type="password"
                      required
                      minLength={8}
                      className="sp-input"
                      placeholder="Min 8 characters"
                      value={regPassword}
                      onChange={(e) => setRegPassword(e.target.value)}
                    />
                  </div>

                  <button
                    type="submit"
                    className="sp-btn-primary"
                    disabled={loading || !regName.trim() || !regEmail.trim() || regPassword.length < 8}
                  >
                    {loading ? "Creating..." : "Create Workspace"}
                  </button>
                </form>
              )}
            </div>
          </div>
        </div>

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

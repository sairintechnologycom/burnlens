"use client";

import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, XCircle } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8420";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("This verification link is invalid. Try resending the email from your dashboard.");
      return;
    }
    fetch(`${API_BASE}/auth/verify-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        if (res.ok) {
          localStorage.setItem("burnlens_email_verified", "true");
          setStatus("success");
          setMessage("Your account is fully active. Welcome to BurnLens.");
        } else {
          const body = await res.json().catch(() => ({}));
          const detail =
            typeof body.detail === "string"
              ? body.detail
              : "This link has expired. Request a new verification email from your dashboard.";
          setStatus("error");
          setMessage(detail);
        }
      })
      .catch(() => {
        setStatus("error");
        setMessage("Could not connect. Please try again.");
      });
  }, [token]);

  return (
    <div className="sp-form-area">
      {status === "loading" && (
        <p
          aria-live="polite"
          style={{ fontSize: 13, color: "var(--s-muted)" }}
        >
          Verifying your email&hellip;
        </p>
      )}

      {status === "success" && (
        <>
          <CheckCircle2
            size={24}
            color="var(--green, #22c98a)"
            aria-hidden="true"
            style={{ marginBottom: 16 }}
          />
          <div className="sp-form-title" style={{ color: "var(--s-text)" }}>
            Email verified
          </div>
          <p className="sp-form-sub">{message}</p>
          <Link
            href="/dashboard"
            className="sp-btn-primary"
            style={{ display: "inline-block", textAlign: "center", textDecoration: "none" }}
          >
            Go to dashboard
          </Link>
        </>
      )}

      {status === "error" && (
        <>
          <XCircle
            size={24}
            color="var(--s-red, #f04060)"
            aria-hidden="true"
            style={{ marginBottom: 16 }}
          />
          <div className="sp-form-title" style={{ color: "var(--s-red, #f04060)" }}>
            Verification failed
          </div>
          <p className="sp-form-sub">{message}</p>
          <Link
            href="/dashboard"
            className="sp-btn-primary"
            style={{ display: "inline-block", textAlign: "center", textDecoration: "none" }}
          >
            Go to dashboard
          </Link>
        </>
      )}
    </div>
  );
}

export default function VerifyEmailPage() {
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
        .sp-form-title {
          font-weight: 700; font-size: 20px; color: var(--s-text);
          margin-bottom: 4px;
        }
        .sp-form-sub {
          font-size: 13px; color: var(--s-muted); margin-bottom: 24px;
        }
        .sp-btn-primary {
          width: 100%; padding: 11px 0; border: none; border-radius: 6px;
          background: var(--cyan); color: var(--bg);
          font-weight: 600; font-size: 14px; cursor: pointer;
          transition: background 0.15s;
        }
        .sp-btn-primary:hover { background: var(--cyan-dim); }
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
          <Link href="/setup" className="sp-back">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M10 4L6 8l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Back to sign in
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
            <Suspense
              fallback={
                <div className="sp-form-area">
                  <p style={{ color: "var(--s-muted)", fontSize: 13 }}>Verifying&hellip;</p>
                </div>
              }
            >
              <VerifyEmailContent />
            </Suspense>
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

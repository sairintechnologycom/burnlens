"use client";

import { useState, Suspense, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function SetupContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isExpired = searchParams.get("expired") === "1";
  const [mode, setMode] = useState<"enter" | "register">("enter");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);
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
    <div className="setup-page">
      <div className="setup-card">
        {isExpired && (
          <div style={{
            padding: "10px 14px",
            marginBottom: 20,
            borderRadius: 4,
            background: "var(--sev-h-bg)",
            border: "1px solid var(--amber)",
            color: "var(--amber)",
            fontSize: 12,
          }}>
            Session expired. Please enter your API key.
          </div>
        )}

        {generatedKey ? (
          <>
            <h1>Registration Complete</h1>
            <p className="sub">Save your API key now. You will not see it again.</p>

            <div style={{ marginBottom: 16 }}>
              <label className="form-label">Your API Key</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  className="form-input"
                  readOnly
                  value={generatedKey}
                  style={{ flex: 1, color: "var(--cyan)" }}
                />
                <button className="btn btn-cyan" onClick={copyKey}>
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>

            <div style={{ marginBottom: 16 }}>
              <label className="form-label">Add to burnlens.yaml</label>
              <pre style={{
                background: "var(--bg2)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                padding: 12,
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: "var(--cyan)",
                overflowX: "auto",
                lineHeight: 1.8,
              }}>
{`cloud:
  enabled: true
  api_key: "${generatedKey}"
  endpoint: "${API_BASE}"`}
              </pre>
            </div>

            <div style={{
              padding: "10px 14px",
              borderRadius: 4,
              background: "var(--sev-h-bg)",
              fontSize: 11,
              color: "var(--amber)",
              marginBottom: 16,
              lineHeight: 1.5,
            }}>
              This key grants full access. Store it securely.
            </div>

            <button
              onClick={() => router.push("/dashboard")}
              className="btn btn-cyan"
              style={{ width: "100%", padding: "10px", justifyContent: "center" }}
            >
              Enter Dashboard
            </button>
          </>
        ) : mode === "enter" ? (
          <>
            <h1>Connect to BurnLens</h1>
            <p className="sub">Enter your API key to access the dashboard.</p>

            {error && (
              <div style={{
                padding: "10px 14px",
                marginBottom: 16,
                borderRadius: 4,
                background: "var(--sev-c-bg)",
                color: "var(--red)",
                fontSize: 12,
              }}>
                {error}
              </div>
            )}

            <div style={{ marginBottom: 20 }}>
              <label className="form-label">API Key</label>
              <input
                type="password"
                placeholder="bl_live_..."
                className="form-input"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && apiKey) validateKey(); }}
              />
            </div>

            <button
              onClick={validateKey}
              disabled={loading || !apiKey}
              className="btn btn-cyan"
              style={{ width: "100%", padding: "10px", justifyContent: "center", marginBottom: 20 }}
            >
              {loading ? "Connecting..." : "Connect"}
            </button>

            <div style={{ textAlign: "center", borderTop: "1px solid var(--border)", paddingTop: 16 }}>
              <span style={{ fontSize: 11, color: "var(--muted)" }}>No API key? </span>
              <button
                onClick={() => { setMode("register"); setError(""); }}
                style={{
                  fontSize: 12,
                  color: "var(--cyan)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontFamily: "var(--font-mono)",
                }}
              >
                Register
              </button>
            </div>
          </>
        ) : (
          <>
            <h1>Register Organization</h1>
            <p className="sub">Create an account to start tracking costs.</p>

            {error && (
              <div style={{
                padding: "10px 14px",
                marginBottom: 16,
                borderRadius: 4,
                background: "var(--sev-c-bg)",
                color: "var(--red)",
                fontSize: 12,
              }}>
                {error}
              </div>
            )}

            <form onSubmit={handleRegister}>
              <div style={{ marginBottom: 16 }}>
                <label className="form-label">Organization Name</label>
                <input
                  type="text"
                  required
                  placeholder="Acme Engineering"
                  className="form-input"
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  style={{ fontFamily: "var(--font-sans)" }}
                />
              </div>

              <div style={{ marginBottom: 20 }}>
                <label className="form-label">Email</label>
                <input
                  type="email"
                  required
                  placeholder="eng@acme.com"
                  className="form-input"
                  value={regEmail}
                  onChange={(e) => setRegEmail(e.target.value)}
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="btn btn-cyan"
                style={{ width: "100%", padding: "10px", justifyContent: "center", marginBottom: 20 }}
              >
                {loading ? "Creating..." : "Create Organization"}
              </button>
            </form>

            <div style={{ textAlign: "center", borderTop: "1px solid var(--border)", paddingTop: 16 }}>
              <button
                onClick={() => { setMode("enter"); setError(""); }}
                style={{
                  fontSize: 12,
                  color: "var(--cyan)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontFamily: "var(--font-mono)",
                }}
              >
                Already have a key? Sign in
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function SetupPage() {
  return (
    <Suspense fallback={
      <div className="setup-page">
        <div className="setup-card" style={{ textAlign: "center" }}>
          <div className="skeleton" style={{ width: 32, height: 32, borderRadius: "50%", margin: "0 auto 12px" }} />
          <span style={{ fontSize: 12, color: "var(--muted)" }}>Loading...</span>
        </div>
      </div>
    }>
      <SetupContent />
    </Suspense>
  );
}

"use client";

import { useState, Suspense, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Key, Copy, Check, AlertTriangle, ArrowRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function SetupContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isExpired = searchParams.get("expired") === "1";
  const [mode, setMode] = useState<"enter" | "register">("enter");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Registration fields
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
      if (!resp.ok) {
        throw new Error("Invalid API key");
      }
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
    <div className="w-full max-w-lg">
      {isExpired && (
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="card"
          style={{ marginBottom: 32, borderColor: "rgba(249, 115, 22, 0.2)", background: "rgba(249, 115, 22, 0.05)", display: "flex", gap: 16, alignItems: "center", padding: "16px 24px" }}
        >
          <div style={{ color: "#fb923c" }}><AlertTriangle size={24} /></div>
          <div>
            <h4 className="text-white font-bold text-sm">Session expired</h4>
            <p className="text-muted text-xs">Please enter your API key to continue.</p>
          </div>
        </motion.div>
      )}

      <Link href="/" className="btn" style={{ border: "none", background: "none", padding: 0, marginBottom: 32, display: "inline-flex", alignItems: "center" }}>
        <ArrowLeft size={16} style={{ marginRight: 8 }} />
        <span className="text-sm font-medium">Back to Home</span>
      </Link>

      <AnimatePresence mode="wait">
        {generatedKey ? (
          <motion.div
            key="generated"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="card"
            style={{ padding: 32 }}
          >
            <div style={{ marginBottom: 32, textAlign: "center" }}>
              <div style={{ width: 64, height: 64, borderRadius: "50%", background: "rgba(116,212,165,0.1)", border: "1px solid rgba(116,212,165,0.2)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px", color: "var(--primary)" }}>
                <Key size={32} />
              </div>
              <h1 className="text-2xl font-bold text-white" style={{ marginBottom: 8 }}>Registration Complete</h1>
              <p className="text-muted text-sm" style={{ maxWidth: 320, margin: "0 auto" }}>
                Save your API key now. You will not see it again.
              </p>
            </div>

            <div style={{ marginBottom: 24 }}>
              <label className="form-label">Your API Key</label>
              <div style={{ position: "relative" }}>
                <input
                  type="text"
                  readOnly
                  value={generatedKey}
                  className="form-input"
                  style={{ paddingRight: 48, color: "var(--primary)", fontFamily: "var(--font-mono)", fontSize: 13 }}
                />
                <button
                  onClick={copyKey}
                  style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", color: "var(--muted)", padding: 8 }}
                >
                  {copied ? <Check className="text-primary" size={18} /> : <Copy size={18} />}
                </button>
              </div>
            </div>

            <div style={{ marginBottom: 24 }}>
              <label className="form-label">Add to your burnlens.yaml</label>
              <pre style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 12, padding: 16, fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--primary)", overflowX: "auto", lineHeight: 1.8 }}>
{`cloud:
  enabled: true
  api_key: "${generatedKey}"
  endpoint: "${API_BASE}"`}
              </pre>
            </div>

            <div style={{ padding: 16, borderRadius: 12, background: "rgba(249, 115, 22, 0.05)", border: "1px solid rgba(249, 115, 22, 0.1)", color: "#fb923c", fontSize: 12, lineHeight: 1.6, marginBottom: 24 }}>
              <strong>Warning:</strong> This key grants full access to your organization data. Store it securely.
            </div>

            <button
              onClick={() => router.push("/dashboard")}
              className="btn btn-primary w-full"
              style={{ padding: "16px", fontSize: "16px" }}
            >
              Enter Dashboard
              <ArrowRight size={18} style={{ marginLeft: 8 }} />
            </button>
          </motion.div>
        ) : mode === "enter" ? (
          <motion.div
            key="enter"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="card"
            style={{ padding: 32 }}
          >
            <div style={{ marginBottom: 32 }}>
              <h1 className="text-2xl font-bold text-white" style={{ marginBottom: 8 }}>Connect to BurnLens</h1>
              <p className="text-muted text-sm">Enter your API key to access the team dashboard.</p>
            </div>

            {error && (
              <div style={{ padding: 16, borderRadius: 12, marginBottom: 24, background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", color: "#f87171", fontSize: 13 }}>
                {error}
              </div>
            )}

            <div style={{ marginBottom: 24 }}>
              <label className="form-label">API Key</label>
              <input
                type="password"
                placeholder="bl_live_..."
                className="form-input"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && apiKey) validateKey(); }}
                style={{ fontFamily: "var(--font-mono)" }}
              />
            </div>

            <button
              onClick={validateKey}
              disabled={loading || !apiKey}
              className="btn btn-primary w-full"
              style={{ padding: "16px", fontSize: "16px", marginBottom: 24 }}
            >
              {loading ? (
                <div className="w-5 h-5 animate-spin" style={{ border: "2px solid rgba(0,0,0,0.2)", borderTopColor: "rgba(0,0,0,1)", borderRadius: "50%" }} />
              ) : (
                <>
                  <Key size={18} style={{ marginRight: 8 }} />
                  Connect
                </>
              )}
            </button>

            <div style={{ textAlign: "center", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 24 }}>
              <p className="text-muted text-xs" style={{ marginBottom: 8 }}>Don&apos;t have an API key?</p>
              <button
                onClick={() => { setMode("register"); setError(""); }}
                className="text-sm font-medium"
                style={{ color: "var(--primary)", background: "none", border: "none", cursor: "pointer" }}
              >
                Register a new organization
              </button>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="register"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="card"
            style={{ padding: 32 }}
          >
            <div style={{ marginBottom: 32 }}>
              <h1 className="text-2xl font-bold text-white" style={{ marginBottom: 8 }}>Register Organization</h1>
              <p className="text-muted text-sm">Create an account to start tracking your LLM costs.</p>
            </div>

            {error && (
              <div style={{ padding: 16, borderRadius: 12, marginBottom: 24, background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", color: "#f87171", fontSize: 13 }}>
                {error}
              </div>
            )}

            <form onSubmit={handleRegister}>
              <div style={{ marginBottom: 20 }}>
                <label className="form-label">Organization Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Acme Engineering"
                  className="form-input"
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                />
              </div>

              <div style={{ marginBottom: 24 }}>
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
                className="btn btn-primary w-full"
                style={{ padding: "16px", fontSize: "16px", marginBottom: 24 }}
              >
                {loading ? (
                  <div className="w-5 h-5 animate-spin" style={{ border: "2px solid rgba(0,0,0,0.2)", borderTopColor: "rgba(0,0,0,1)", borderRadius: "50%" }} />
                ) : (
                  "Create Organization"
                )}
              </button>
            </form>

            <div style={{ textAlign: "center", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 24 }}>
              <button
                onClick={() => { setMode("enter"); setError(""); }}
                className="text-sm font-medium"
                style={{ color: "var(--primary)", background: "none", border: "none", cursor: "pointer" }}
              >
                Already have an API key? Sign in
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function SetupPage() {
  return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: "radial-gradient(circle at top right, rgba(116,212,165,0.05), transparent 40%)" }}>
      <Suspense fallback={
        <div className="card" style={{ padding: 32, textAlign: "center", width: "100%", maxWidth: "512px" }}>
          <div className="w-8 h-8 animate-spin mx-auto" style={{ border: "3px solid rgba(116,212,165,0.1)", borderTopColor: "var(--primary)", borderRadius: "50%" }} />
          <p className="text-muted text-sm mt-4">Loading setup...</p>
        </div>
      }>
        <SetupContent />
      </Suspense>
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";

function SettingsContent() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [copied, setCopied] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    document.title = "Settings | BurnLens";
  }, []);

  const handleCopy = () => {
    if (!session) return;
    navigator.clipboard.writeText(session.apiKey);
    setCopied(true);
    showToast("API key copied", "success");
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRegenerate = async () => {
    if (!session) return;
    if (!confirm("Regenerate your API key? The old key will stop working immediately.")) return;
    setRegenerating(true);
    try {
      const data = await apiFetch("/api/v1/orgs/regenerate-key", session.token, { method: "POST" });
      localStorage.setItem("burnlens_api_key", data.api_key);
      showToast("API key regenerated", "success");
      window.location.reload();
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else showToast("Failed: " + err.message, "error");
    } finally {
      setRegenerating(false);
    }
  };

  const handleSync = async () => {
    if (!session) return;
    setSyncing(true);
    try {
      await apiFetch("/api/v1/sync/trigger", session.token, { method: "POST" });
      showToast("Sync triggered", "success");
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else showToast("Sync failed: " + err.message, "error");
    } finally {
      setSyncing(false);
    }
  };

  const maskedKey = session?.apiKey
    ? `${session.apiKey.slice(0, 12)}${"•".repeat(8)}`
    : "—";

  return (
    <div>
      {/* Organization */}
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Organization</span>
        </div>
        <div style={{ padding: 18 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <div>
              <label className="form-label">Org name</label>
              <input
                className="form-input"
                defaultValue={session?.workspaceName}
                style={{ fontFamily: "var(--font-sans)" }}
              />
            </div>
            <div>
              <label className="form-label">Tier</label>
              <div style={{
                padding: "8px 12px",
                background: "var(--bg3)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "var(--cyan)",
              }}>
                Free
              </div>
            </div>
          </div>

          <div>
            <label className="form-label">API key</label>
            <div style={{ display: "flex", gap: 8 }}>
              <div className="form-input" style={{ flex: 1, color: "var(--muted)", userSelect: "none" }}>
                {maskedKey}
              </div>
              <button className="btn" onClick={handleCopy}>
                {copied ? "Copied" : "Copy"}
              </button>
              <button
                className="btn btn-red"
                onClick={handleRegenerate}
                disabled={regenerating}
              >
                {regenerating ? "..." : "Regenerate"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Cloud sync */}
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Cloud sync</span>
        </div>
        <div style={{ padding: 18 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <div>
              <label className="form-label">Status</label>
              <div style={{
                padding: "8px 12px",
                background: "var(--bg3)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "var(--green)",
              }}>
                Enabled
              </div>
            </div>
            <div>
              <label className="form-label">Endpoint</label>
              <div className="form-input" style={{ color: "var(--muted)" }}>
                {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}
              </div>
            </div>
          </div>
          <button className="btn btn-cyan" onClick={handleSync} disabled={syncing}>
            {syncing ? "Syncing..." : "Sync now"}
          </button>
        </div>
      </div>

      {/* Connections */}
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Connections</span>
        </div>
        <div style={{ padding: 18, fontSize: 12, color: "var(--muted)" }}>
          Provider connections are managed via the Connections page.
        </div>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Shell>
      <SettingsContent />
    </Shell>
  );
}

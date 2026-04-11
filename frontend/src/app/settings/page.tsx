"use client";

import { useState, useEffect } from "react";
import DashboardLayout from "@/components/DashboardLayout";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";
import { Shield, CreditCard, User, Bell, Download, Trash2, Key, Copy, Check, FileDown } from "lucide-react";

type Tab = "profile" | "api-keys" | "billing" | "export";

export default function SettingsPage() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();

  useEffect(() => {
    document.title = "Settings | BurnLens";
  }, []);

  const [activeTab, setActiveTab] = useState<Tab>("profile");
  const [deleting, setDeleting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [exportDays, setExportDays] = useState(30);
  const [exportFormat, setExportFormat] = useState<"json" | "csv">("csv");

  const handleDelete = async () => {
    if (!session) return;
    const confirmed = prompt("This action is PERMANENT. Type your organization name to confirm:");
    if (confirmed !== session.orgName) {
      showToast("Organization name didn't match. Deletion cancelled.", "warning");
      return;
    }
    setDeleting(true);
    try {
      await apiFetch("/api/v1/account", session.apiKey, { method: "DELETE" });
      showToast("Your organization and all data have been permanently deleted.", "success");
      logout();
    } catch (err: any) {
      if (err instanceof AuthError) {
        logout();
      } else {
        showToast("Delete failed: " + err.message, "error");
        setDeleting(false);
      }
    }
  };

  const handleExport = async () => {
    if (!session) return;
    setExporting(true);
    try {
      if (exportFormat === "csv") {
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/export?days=${exportDays}&format=csv`,
          { headers: { "X-API-Key": session.apiKey } }
        );
        if (!response.ok) throw new Error("Export failed");
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `burnlens-export-${exportDays}d.csv`;
        a.click();
        URL.revokeObjectURL(url);
        showToast("Export completed successfully", "success");
      } else {
        const data = await apiFetch(`/api/v1/export?days=${exportDays}&format=json`, session.apiKey);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `burnlens-export-${exportDays}d.json`;
        a.click();
        URL.revokeObjectURL(url);
        showToast("Export completed successfully", "success");
      }
    } catch (err: any) {
      if (err instanceof AuthError) {
        logout();
      } else {
        showToast("Export failed: " + err.message, "error");
      }
    } finally {
      setExporting(false);
    }
  };

  const handleCopyApiKey = () => {
    if (!session) return;
    navigator.clipboard.writeText(session.apiKey);
    setCopied(true);
    showToast("API key copied to clipboard", "success");
    setTimeout(() => setCopied(false), 2000);
  };

  const tabs: { id: Tab; label: string; icon: any }[] = [
    { id: "profile", label: "Profile", icon: User },
    { id: "api-keys", label: "API Keys", icon: Shield },
    { id: "export", label: "Data Export", icon: FileDown },
    { id: "billing", label: "Billing", icon: CreditCard },
  ];

  return (
    <DashboardLayout>
      <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Settings</h1>
          <p className="text-muted text-sm" style={{ marginTop: 4 }}>Manage your organization profile, data, and billing information.</p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 32 }}>
          {/* ── Tab Navigation ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {tabs.map(tab => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  className={`sidebar-nav-item ${activeTab === tab.id ? "active" : ""}`}
                  style={{
                    width: "100%",
                    justifyContent: "flex-start",
                    ...(activeTab === tab.id ? { border: "1px solid rgba(116,212,165,0.2)" } : {}),
                  }}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <Icon size={18} />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* ── Content Area ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
            {/* Profile Tab */}
            {activeTab === "profile" && (
              <>
                <div className="card" style={{ padding: 32 }}>
                  <h3 className="text-white font-bold text-lg" style={{ marginBottom: 24 }}>Organization Details</h3>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 24 }}>
                    <div>
                      <label className="form-label">Organization Name</label>
                      <input readOnly value={session?.orgName} className="form-input" style={{ background: "rgba(255,255,255,0.01)", cursor: "default" }} />
                    </div>
                    <div>
                      <label className="form-label">Org ID</label>
                      <input readOnly value={session?.orgId} className="form-input" style={{ background: "rgba(255,255,255,0.01)", cursor: "default", color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 11 }} />
                    </div>
                  </div>
                </div>

                <div className="card" style={{ padding: 32, borderColor: "rgba(239, 68, 68, 0.1)" }}>
                  <h3 className="text-white font-bold text-lg" style={{ marginBottom: 8 }}>Danger Zone</h3>
                  <p className="text-muted text-sm" style={{ marginBottom: 24 }}>Permanently delete your organization, all connections, usage records, optimizations, and alerts. This action cannot be undone.</p>
                  <button
                    className="btn"
                    style={{ borderColor: "rgba(239, 68, 68, 0.2)", color: "#ef4444", padding: "0 24px", height: 44 }}
                    onMouseEnter={(e) => e.currentTarget.style.background = "rgba(239, 68, 68, 0.05)"}
                    onMouseLeave={(e) => e.currentTarget.style.background = "none"}
                    onClick={handleDelete}
                    disabled={deleting}
                  >
                    <Trash2 size={16} style={{ marginRight: 8 }} />
                    {deleting ? "Deleting..." : "Delete Organization"}
                  </button>
                </div>
              </>
            )}

            {/* API Keys Tab */}
            {activeTab === "api-keys" && (
              <div className="card" style={{ padding: 32 }}>
                <h3 className="text-white font-bold text-lg" style={{ marginBottom: 8 }}>API Key</h3>
                <p className="text-muted text-sm" style={{ marginBottom: 24 }}>Use this key to authenticate API requests. Keep it secret.</p>

                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <div className="form-input" style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    background: "rgba(255,255,255,0.02)",
                    letterSpacing: "0.02em",
                  }}>
                    <Key size={14} style={{ marginRight: 12, color: "var(--muted)", flexShrink: 0 }} />
                    <span style={{ color: "var(--muted)" }}>
                      {session?.apiKey ? `${session.apiKey.slice(0, 8)}${"•".repeat(24)}${session.apiKey.slice(-4)}` : "—"}
                    </span>
                  </div>
                  <button
                    className="btn"
                    style={{ padding: "0 16px", height: 44, minWidth: 100 }}
                    onClick={handleCopyApiKey}
                  >
                    {copied ? <Check size={16} style={{ color: "var(--primary)" }} /> : <Copy size={16} />}
                    <span style={{ marginLeft: 6 }}>{copied ? "Copied!" : "Copy"}</span>
                  </button>
                </div>

                <p style={{ fontSize: 10, color: "var(--muted)", marginTop: 12 }}>
                  Treat this like a password. If compromised, contact support to rotate it.
                </p>
              </div>
            )}

            {/* Data Export Tab */}
            {activeTab === "export" && (
              <div className="card" style={{ padding: 32 }}>
                <h3 className="text-white font-bold text-lg" style={{ marginBottom: 8 }}>
                  <Download size={20} style={{ display: "inline", verticalAlign: "-3px", marginRight: 8 }} />
                  Export Your Data
                </h3>
                <p className="text-muted text-sm" style={{ marginBottom: 32 }}>
                  Download your usage records as CSV or JSON. Your data belongs to you.
                </p>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
                  <div>
                    <label className="form-label">Time Period</label>
                    <select
                      className="form-input"
                      value={exportDays}
                      onChange={(e) => setExportDays(Number(e.target.value))}
                      style={{ appearance: "auto" }}
                    >
                      <option value={7}>Last 7 days</option>
                      <option value={30}>Last 30 days</option>
                      <option value={90}>Last 90 days</option>
                      <option value={180}>Last 180 days</option>
                      <option value={365}>Last 365 days</option>
                    </select>
                  </div>
                  <div>
                    <label className="form-label">Format</label>
                    <select
                      className="form-input"
                      value={exportFormat}
                      onChange={(e) => setExportFormat(e.target.value as "json" | "csv")}
                      style={{ appearance: "auto" }}
                    >
                      <option value="csv">CSV (spreadsheet-friendly)</option>
                      <option value="json">JSON (developer-friendly)</option>
                    </select>
                  </div>
                </div>

                <button
                  className="btn btn-primary"
                  style={{ padding: "0 32px", height: 48 }}
                  onClick={handleExport}
                  disabled={exporting}
                >
                  <Download size={16} style={{ marginRight: 8 }} />
                  {exporting ? "Preparing..." : `Download ${exportFormat.toUpperCase()}`}
                </button>
              </div>
            )}

            {/* Billing Tab */}
            {activeTab === "billing" && (
              <div className="card" style={{ padding: 32 }}>
                <h3 className="text-white font-bold text-lg" style={{ marginBottom: 8 }}>License & Billing</h3>
                <p className="text-muted text-sm" style={{ marginBottom: 24 }}>Manage your BurnLens license and subscription.</p>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 24, marginBottom: 32 }}>
                  <div>
                    <label className="form-label">Current Tier</label>
                    <div style={{
                      padding: "12px 16px",
                      borderRadius: 8,
                      background: "rgba(116,212,165,0.05)",
                      border: "1px solid rgba(116,212,165,0.15)",
                      color: "var(--primary)",
                      fontWeight: 700,
                      fontSize: 14,
                    }}>
                      Free Tier
                    </div>
                  </div>
                  <div>
                    <label className="form-label">Data Retention</label>
                    <div style={{
                      padding: "12px 16px",
                      borderRadius: 8,
                      background: "rgba(255,255,255,0.02)",
                      border: "1px solid rgba(255,255,255,0.05)",
                      color: "var(--muted)",
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                    }}>
                      30 days
                    </div>
                  </div>
                </div>

                <a href="/#pricing" className="btn btn-primary" style={{ padding: "0 32px", height: 48, textDecoration: "none", display: "inline-flex" }}>
                  <CreditCard size={16} style={{ marginRight: 8 }} />
                  Upgrade Plan
                </a>
              </div>
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

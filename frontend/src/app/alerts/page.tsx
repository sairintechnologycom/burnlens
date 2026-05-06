"use client";

import { useEffect, useState, useCallback } from "react";
import { BellIcon } from "lucide-react";
import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";

interface AlertRule {
  id: string;
  threshold_pct: number;
  channel: string;
  enabled: boolean;
  has_slack: boolean;
  extra_emails: string[];
  created_at: string;
  updated_at: string;
}

function AlertsContent() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();

  const [rules, setRules] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null);
  const [editThreshold, setEditThreshold] = useState<number>(80);
  const [editEmails, setEditEmails] = useState<string[]>([]);
  const [emailInput, setEmailInput] = useState("");
  const [emailError, setEmailError] = useState("");
  const [saving, setSaving] = useState(false);

  const isOwner = session?.role === "owner";

  useEffect(() => {
    document.title = "Alerts | BurnLens";
  }, []);

  const fetchRules = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch("/api/v1/alert-rules", session.token);
      setRules(Array.isArray(data) ? data : []);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  // Close modal on Escape
  useEffect(() => {
    if (!editingRule) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setEditingRule(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [editingRule]);

  const handleToggle = async (rule: AlertRule) => {
    if (pendingId) return;
    const prev = rule.enabled;
    const ruleId = rule.id;
    setPendingId(ruleId);
    // Optimistic update
    setRules((rs: AlertRule[]) => rs.map((r: AlertRule) => r.id === ruleId ? { ...r, enabled: !prev } : r));
    try {
      await apiFetch(`/api/v1/alert-rules/${ruleId}`, session!.token, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !prev }),
      });
      showToast("Alert rule updated", "success");
    } catch (err: any) {
      // Revert on error
      setRules((rs: AlertRule[]) => rs.map((r: AlertRule) => r.id === ruleId ? { ...r, enabled: prev } : r));
      if (err instanceof AuthError) logout();
      else showToast("Failed to update rule", "error");
    } finally {
      setPendingId(null);
    }
  };

  const openEdit = (rule: AlertRule) => {
    setEditingRule(rule);
    setEditThreshold(rule.threshold_pct);
    setEditEmails([...rule.extra_emails]);
    setEmailInput("");
    setEmailError("");
  };

  const handleAddEmail = (e: { key: string; preventDefault: () => void }) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const raw = emailInput.trim();
    if (!raw.includes("@") || !raw.includes(".")) {
      setEmailError("Enter a valid email address");
      return;
    }
    const email = raw.toLowerCase();
    if (!editEmails.map((em: string) => em.toLowerCase()).includes(email)) {
      setEditEmails((prev: string[]) => [...prev, email]);
    }
    setEmailInput("");
    setEmailError("");
  };

  const handleRemoveEmail = (email: string) => {
    setEditEmails((prev: string[]) => prev.filter((e: string) => e !== email));
  };

  const handleSave = async () => {
    if (!editingRule || !session) return;
    setSaving(true);
    try {
      await apiFetch(`/api/v1/alert-rules/${editingRule.id}`, session.token, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold_pct: editThreshold, extra_emails: editEmails }),
      });
      setRules((rs: AlertRule[]) =>
        rs.map((r: AlertRule) =>
          r.id === editingRule.id
            ? { ...r, threshold_pct: editThreshold, extra_emails: editEmails }
            : r
        )
      );
      setEditingRule(null);
      showToast("Alert rule saved", "success");
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else showToast("Failed to save rule", "error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8, marginBottom: 16 }}>
          <div className="skeleton" style={{ height: 48 }} />
          <div className="skeleton" style={{ height: 48 }} />
        </div>
        <div className="card">
          <div className="skeleton" style={{ height: 40, marginBottom: 8 }} />
          <div className="skeleton" style={{ height: 40 }} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span
          className="error-inline"
          onClick={fetchRules}
          style={{ cursor: "pointer" }}
        >
          Couldn&apos;t load alert rules — retry &#x2197;
        </span>
      </div>
    );
  }

  const enabledCount = rules.filter((r: AlertRule) => r.enabled).length;

  return (
    <div>
      {/* Stat strip */}
      <div className="stat-strip" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
        <div className="stat-cell">
          <div className="stat-label">Total Rules</div>
          <div className="stat-value">{rules.length}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Enabled</div>
          <div className="stat-value" style={{ color: "var(--green)" }}>{enabledCount}</div>
        </div>
      </div>

      {/* Alert rules table */}
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Alert Rules</span>
        </div>

        {rules.length === 0 ? (
          <EmptyState
            title="No alert rules configured"
            description="Alert rules are created by the system when you configure budget thresholds. Rules will appear here once your workspace has active budget settings."
          />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Threshold</th>
                <th>Channel</th>
                <th>Slack</th>
                <th>Recipients</th>
                <th>Enabled</th>
                {isOwner && <th></th>}
              </tr>
            </thead>
            <tbody>
              {rules.map((rule: AlertRule) => (
                <tr key={rule.id}>
                  {/* Threshold badge */}
                  <td>
                    <span
                      style={{
                        background: rule.threshold_pct === 80
                          ? "rgba(245,166,35,0.12)"
                          : "var(--bg3)",
                        color: rule.threshold_pct === 80
                          ? "var(--amber)"
                          : "var(--muted)",
                        fontFamily: "var(--font-mono)",
                        fontSize: 12,
                        borderRadius: 3,
                        padding: "2px 8px",
                      }}
                    >
                      {rule.threshold_pct}%
                    </span>
                  </td>

                  {/* Channel */}
                  <td>
                    <span className="provider-badge">{rule.channel}</span>
                  </td>

                  {/* Slack */}
                  <td>
                    {rule.has_slack ? (
                      <span
                        style={{
                          background: "rgba(45,212,191,0.1)",
                          border: "1px solid rgba(45,212,191,0.3)",
                          color: "var(--cyan)",
                          fontFamily: "var(--font-mono)",
                          fontSize: 12,
                          borderRadius: 3,
                          padding: "2px 8px",
                        }}
                      >
                        webhook set
                      </span>
                    ) : (
                      <span style={{ color: "var(--dim)" }}>—</span>
                    )}
                  </td>

                  {/* Recipients count */}
                  <td>{rule.extra_emails.length}</td>

                  {/* Enabled toggle / dot */}
                  <td>
                    {isOwner ? (
                      <button
                        aria-label={rule.enabled ? "Disable rule" : "Enable rule"}
                        aria-pressed={rule.enabled}
                        disabled={pendingId === rule.id}
                        onClick={() => handleToggle(rule)}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          width: 20,
                          height: 12,
                          borderRadius: 6,
                          background: rule.enabled ? "var(--green)" : "var(--bg3)",
                          border: "none",
                          padding: 2,
                          cursor: pendingId === rule.id ? "not-allowed" : "pointer",
                          opacity: pendingId === rule.id ? 0.6 : 1,
                          pointerEvents: pendingId === rule.id ? "none" : "auto",
                          transition: "background 0.15s",
                          flexShrink: 0,
                        }}
                      >
                        <span
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: "50%",
                            background: "white",
                            marginLeft: rule.enabled ? "auto" : 0,
                            transition: "margin 0.15s",
                          }}
                        />
                      </button>
                    ) : (
                      <span
                        style={{
                          display: "inline-block",
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: rule.enabled ? "var(--green)" : "var(--dim)",
                        }}
                      />
                    )}
                  </td>

                  {/* Actions — owner only */}
                  {isOwner && (
                    <td>
                      <button
                        className="btn"
                        onClick={() => openEdit(rule)}
                        style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                      >
                        <BellIcon size={14} />
                        Edit Rule
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Edit modal */}
      {editingRule !== null && (
        <>
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.5)",
              zIndex: 100,
            }}
            onClick={() => setEditingRule(null)}
          />
          <div
            style={{
              position: "fixed",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              zIndex: 101,
              width: "100%",
              maxWidth: 480,
            }}
          >
            <div className="setup-card">
              <h1 style={{ fontSize: 14, fontWeight: 600 }}>Edit Alert Rule</h1>
              <p className="sub">Changes take effect on the next budget check.</p>

              {/* Threshold select */}
              <label className="form-label">THRESHOLD</label>
              <select
                className="form-input"
                value={editThreshold}
                onChange={(e: { target: { value: string } }) => setEditThreshold(Number(e.target.value))}
                style={{ appearance: "auto" }}
              >
                <option value={80}>80%</option>
                <option value={100}>100%</option>
              </select>

              {/* Extra email recipients */}
              <label className="form-label" style={{ marginTop: 16 }}>
                EXTRA EMAIL RECIPIENTS
              </label>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 8,
                  padding: 8,
                  background: "var(--bg2)",
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                }}
              >
                {editEmails.map((email: string) => (
                  <span
                    key={email}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      background: "var(--bg3)",
                      color: "var(--text)",
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      borderRadius: 3,
                      padding: "2px 8px",
                    }}
                  >
                    {email}
                    <button
                      aria-label={`Remove ${email}`}
                      onClick={() => handleRemoveEmail(email)}
                      style={{
                        background: "none",
                        border: "none",
                        color: "var(--muted)",
                        cursor: "pointer",
                        padding: 0,
                        lineHeight: 1,
                        fontSize: 12,
                      }}
                    >
                      ×
                    </button>
                  </span>
                ))}
                <input
                  className="form-input"
                  style={{ width: "auto", flexGrow: 1 }}
                  placeholder="add email, press Enter"
                  value={emailInput}
                  onChange={(e: { target: { value: string } }) => setEmailInput(e.target.value)}
                  onKeyDown={handleAddEmail}
                />
              </div>
              {emailError && (
                <div style={{ fontSize: 12, color: "var(--red)", marginTop: 4 }}>
                  {emailError}
                </div>
              )}

              {/* Slack link */}
              <div style={{ marginTop: 12 }}>
                <a
                  href="/settings"
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    color: "var(--cyan)",
                    textDecoration: "underline",
                  }}
                  onClick={() => setEditingRule(null)}
                >
                  Manage Slack webhook in Settings →
                </a>
              </div>

              {/* Action buttons */}
              <div
                style={{
                  display: "flex",
                  gap: 8,
                  marginTop: 24,
                  justifyContent: "flex-end",
                }}
              >
                <button className="btn" onClick={() => setEditingRule(null)}>
                  Cancel
                </button>
                <button
                  className="btn btn-cyan"
                  onClick={handleSave}
                  disabled={saving}
                >
                  {saving ? "Saving…" : "Save Changes"}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function AlertsPage() {
  return (
    <Shell>
      <AlertsContent />
    </Shell>
  );
}

"use client";

import { useEffect, useState } from "react";
import DashboardLayout from "@/components/DashboardLayout";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";
import { Bell, Plus, Trash2, Mail, MessageSquare, Webhook, X, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface AlertRule {
  id: string;
  name: string;
  metric: string;
  threshold: number;
  provider_filter: string | null;
  model_filter: string | null;
  webhook_url: string | null;
  is_active: boolean;
  triggered_count: number;
}

const METRIC_OPTIONS = [
  { value: "daily_cost", label: "Daily Cost ($)" },
  { value: "monthly_cost", label: "Monthly Cost ($)" },
  { value: "daily_tokens", label: "Daily Tokens" },
  { value: "daily_calls", label: "Daily API Calls" },
  { value: "model_cost", label: "Per-Model Daily Cost ($)" },
  { value: "provider_cost", label: "Per-Provider Daily Cost ($)" },
];

const PROVIDER_OPTIONS = [
  { value: "", label: "All Providers" },
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
  { value: "google", label: "Google AI" },
];

export default function AlertsPage() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [alerts, setAlerts] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [metric, setMetric] = useState("daily_cost");
  const [threshold, setThreshold] = useState("");
  const [providerFilter, setProviderFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");

  const fetchAlerts = async () => {
    if (!session) return;
    try {
      const data = await apiFetch("/api/v1/alerts", session.apiKey);
      setAlerts(Array.isArray(data) ? data : data.alerts || []);
    } catch (err: any) {
      if (err instanceof AuthError) {
        logout();
      } else {
        console.error(err);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, [session]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !name.trim() || !threshold) return;
    setSaving(true);
    try {
      await apiFetch("/api/v1/alerts", session.apiKey, {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          metric,
          threshold: parseFloat(threshold),
          provider_filter: providerFilter || null,
          model_filter: modelFilter.trim() || null,
          webhook_url: webhookUrl.trim() || null,
        }),
      });
      resetForm();
      setShowCreate(false);
      showToast("Alert rule created successfully", "success");
      await fetchAlerts();
    } catch (err: any) {
      if (err instanceof AuthError) {
        logout();
      } else {
        showToast("Failed to create alert: " + err.message, "error");
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!session) return;
    if (!confirm("Delete this alert rule?")) return;
    try {
      await apiFetch(`/api/v1/alerts/${id}`, session.apiKey, { method: "DELETE" });
      setAlerts(alerts.filter(a => a.id !== id));
      showToast("Alert rule deleted", "success");
    } catch (err: any) {
      if (err instanceof AuthError) {
        logout();
      } else {
        showToast("Failed to delete alert: " + err.message, "error");
      }
    }
  };

  const resetForm = () => {
    setName("");
    setMetric("daily_cost");
    setThreshold("");
    setProviderFilter("");
    setModelFilter("");
    setWebhookUrl("");
  };

  const getMetricLabel = (value: string) => {
    return METRIC_OPTIONS.find(m => m.value === value)?.label || value;
  };

  const formatThreshold = (metric: string, threshold: number) => {
    if (metric.includes("cost")) return `$${threshold.toLocaleString()}`;
    return threshold.toLocaleString();
  };

  return (
    <DashboardLayout>
      <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
        {/* ── Header ── */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">Budget Alerts</h1>
            <p className="text-muted text-sm" style={{ marginTop: 4 }}>Get notified before your AI bills surprise you.</p>
          </div>

          <button
            className="btn btn-primary"
            style={{ padding: "0 20px", height: 40 }}
            onClick={() => setShowCreate(true)}
          >
            <Plus size={16} style={{ marginRight: 8 }} />
            Create Alert Rule
          </button>
        </div>

        {/* ── Create Modal ── */}
        <AnimatePresence>
          {showCreate && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              style={{
                position: "fixed",
                inset: 0,
                background: "rgba(0,0,0,0.7)",
                backdropFilter: "blur(8px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 1000,
                padding: 24,
              }}
              onClick={(e: any) => { if (e.target === e.currentTarget) setShowCreate(false); }}
            >
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 20 }}
                className="card"
                style={{
                  width: "100%",
                  maxWidth: 560,
                  padding: 32,
                  background: "var(--surface)",
                  borderColor: "rgba(255,255,255,0.1)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 32 }}>
                  <h2 className="text-xl font-bold text-white">Create Alert Rule</h2>
                  <button
                    onClick={() => setShowCreate(false)}
                    style={{ cursor: "pointer", background: "none", border: "none", color: "var(--muted)" }}
                  >
                    <X size={20} />
                  </button>
                </div>

                <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 24 }}>
                  <div>
                    <label className="form-label">Alert Name</label>
                    <input
                      className="form-input"
                      placeholder='e.g. "Daily spend > $50"'
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      required
                    />
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                    <div>
                      <label className="form-label">Metric</label>
                      <select
                        className="form-input"
                        value={metric}
                        onChange={(e) => setMetric(e.target.value)}
                        style={{ appearance: "auto" }}
                      >
                        {METRIC_OPTIONS.map(m => (
                          <option key={m.value} value={m.value}>{m.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="form-label">Threshold</label>
                      <input
                        className="form-input"
                        type="number"
                        step="0.01"
                        placeholder={metric.includes("cost") ? "$50.00" : "10000"}
                        value={threshold}
                        onChange={(e) => setThreshold(e.target.value)}
                        required
                      />
                    </div>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                    <div>
                      <label className="form-label">Provider Filter</label>
                      <select
                        className="form-input"
                        value={providerFilter}
                        onChange={(e) => setProviderFilter(e.target.value)}
                        style={{ appearance: "auto" }}
                      >
                        {PROVIDER_OPTIONS.map(p => (
                          <option key={p.value} value={p.value}>{p.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="form-label">Model Filter (optional)</label>
                      <input
                        className="form-input"
                        placeholder="e.g. claude-sonnet-4"
                        value={modelFilter}
                        onChange={(e) => setModelFilter(e.target.value)}
                      />
                    </div>
                  </div>

                  <div>
                    <label className="form-label">Webhook URL (optional)</label>
                    <input
                      className="form-input"
                      type="url"
                      placeholder="https://hooks.slack.com/services/..."
                      value={webhookUrl}
                      onChange={(e) => setWebhookUrl(e.target.value)}
                    />
                    <p style={{ fontSize: 10, color: "var(--muted)", marginTop: 6 }}>
                      POST request will be sent when threshold is exceeded.
                    </p>
                  </div>

                  <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", paddingTop: 16 }}>
                    <button
                      type="button"
                      className="btn"
                      style={{ padding: "0 24px", height: 44 }}
                      onClick={() => { resetForm(); setShowCreate(false); }}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="btn btn-primary"
                      style={{ padding: "0 32px", height: 44 }}
                      disabled={saving || !name.trim() || !threshold}
                    >
                      {saving ? "Creating..." : "Create Alert"}
                    </button>
                  </div>
                </form>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Alerts List ── */}
        {loading ? (
          [1, 2, 3].map(i => (
            <div key={i} className="animate-pulse" style={{ height: 80, background: "rgba(255,255,255,0.05)", borderRadius: 16 }} />
          ))
        ) : alerts.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {alerts.map((alert, i) => (
              <motion.div
                key={alert.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className="card"
                style={{ padding: "20px 24px", display: "flex", alignItems: "center", gap: 16 }}
              >
                <div style={{ width: 40, height: 40, borderRadius: 12, background: "rgba(116,212,165,0.1)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--primary)", flexShrink: 0 }}>
                  <Bell size={20} />
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span className="text-white font-semibold">{alert.name}</span>
                    <span style={{
                      fontSize: 9,
                      padding: "2px 8px",
                      borderRadius: 4,
                      background: alert.is_active ? "rgba(116,212,165,0.1)" : "rgba(255,255,255,0.05)",
                      color: alert.is_active ? "var(--primary)" : "var(--muted)",
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                    }}>
                      {alert.is_active ? "Active" : "Paused"}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--muted)" }}>
                    <span>{getMetricLabel(alert.metric)} &gt; {formatThreshold(alert.metric, alert.threshold)}</span>
                    {alert.provider_filter && <span>• {alert.provider_filter}</span>}
                    {alert.model_filter && <span>• {alert.model_filter}</span>}
                    {alert.webhook_url && (
                      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <Webhook size={12} /> Webhook
                      </span>
                    )}
                    {alert.triggered_count > 0 && (
                      <span style={{ color: "var(--accent)" }}>
                        <Zap size={12} style={{ display: "inline", verticalAlign: "-2px", marginRight: 2 }} />
                        Triggered {alert.triggered_count}x
                      </span>
                    )}
                  </div>
                </div>

                <button
                  onClick={() => handleDelete(alert.id)}
                  className="btn"
                  style={{ padding: "8px", height: 36, width: 36, color: "#ef4444", borderColor: "rgba(239,68,68,0.15)" }}
                  title="Delete alert"
                >
                  <Trash2 size={14} />
                </button>
              </motion.div>
            ))}
          </div>
        ) : (
          <div style={{ padding: "80px 24px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", border: "2px dashed rgba(255,255,255,0.05)", borderRadius: 32, background: "rgba(255,255,255,0.01)" }}>
            <div className="bg-white-5" style={{ width: 64, height: 64, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", marginBottom: 24 }}>
              <Bell size={32} />
            </div>
            <h2 className="text-xl font-bold text-white" style={{ marginBottom: 8 }}>No alerts configured</h2>
            <p className="text-muted text-sm" style={{ maxWidth: 384, marginBottom: 32 }}>Set up budget alerts to catch unexpected cost spikes before they hit your invoice.</p>
            <button onClick={() => setShowCreate(true)} className="btn btn-primary" style={{ padding: "0 32px", height: 48 }}>
              <Plus size={16} style={{ marginRight: 8 }} />
              Create Your First Alert
            </button>
          </div>
        )}

        {/* ── Feature Grid ── */}
        <div className="md-grid-3" style={{ gap: 24 }}>
          <div className="card" style={{ padding: 24 }}>
            <div style={{ color: "var(--primary)", marginBottom: 16 }}><Mail size={24} /></div>
            <h4 className="text-white font-bold" style={{ marginBottom: 8 }}>Email Alerts</h4>
            <p className="text-xs text-muted" style={{ lineHeight: 1.6 }}>Direct notifications to your inbox when thresholds are reached.</p>
          </div>
          <div className="card" style={{ padding: 24 }}>
            <div style={{ color: "var(--primary)", marginBottom: 16 }}><MessageSquare size={24} /></div>
            <h4 className="text-white font-bold" style={{ marginBottom: 8 }}>Slack / Discord</h4>
            <p className="text-xs text-muted" style={{ lineHeight: 1.6 }}>Push notifications to your dev channels for immediate updates.</p>
          </div>
          <div className="card" style={{ padding: 24 }}>
            <div style={{ color: "var(--primary)", marginBottom: 16 }}><Webhook size={24} /></div>
            <h4 className="text-white font-bold" style={{ marginBottom: 8 }}>Webhooks</h4>
            <p className="text-xs text-muted" style={{ lineHeight: 1.6 }}>Trigger custom actions or block CI/CD pipelines automatically.</p>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

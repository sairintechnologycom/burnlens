"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";

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

function AlertsContent() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [alerts, setAlerts] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState("");
  const [metric, setMetric] = useState("daily_cost");
  const [threshold, setThreshold] = useState("");
  const [providerFilter, setProviderFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");

  const fetchAlerts = async () => {
    if (!session) return;
    try {
      const data = await apiFetch("/api/v1/alerts", session.token);
      setAlerts(Array.isArray(data) ? data : data.alerts || []);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAlerts(); }, [session]);

  const resetForm = () => {
    setName(""); setMetric("daily_cost"); setThreshold("");
    setProviderFilter(""); setModelFilter(""); setWebhookUrl("");
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session || !name.trim() || !threshold) return;
    setSaving(true);
    try {
      await apiFetch("/api/v1/alerts", session.token, {
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
      showToast("Alert created", "success");
      await fetchAlerts();
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else showToast("Failed: " + err.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!session || !confirm("Delete this alert?")) return;
    try {
      await apiFetch(`/api/v1/alerts/${id}`, session.token, { method: "DELETE" });
      setAlerts(alerts.filter(a => a.id !== id));
      showToast("Alert deleted", "success");
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else showToast("Failed: " + err.message, "error");
    }
  };

  const getMetricLabel = (v: string) => METRIC_OPTIONS.find(m => m.value === v)?.label || v;
  const formatThreshold = (m: string, t: number) => m.includes("cost") ? `$${t}` : t.toLocaleString();

  return (
    <div>
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Budget alerts</span>
          <button className="section-header-action" onClick={() => setShowCreate(true)}>
            + Create
          </button>
        </div>

        {loading ? (
          <div style={{ padding: 16 }}>
            {[1, 2, 3].map((i) => (
              <div key={i} className="skeleton" style={{ height: 48, marginBottom: 8 }} />
            ))}
          </div>
        ) : alerts.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>No alerts configured</div>
            <button className="btn btn-cyan" onClick={() => setShowCreate(true)}>
              Create first alert
            </button>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Metric</th>
                <th>Threshold</th>
                <th>Status</th>
                <th>Triggered</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id}>
                  <td style={{ fontWeight: 500 }}>{a.name}</td>
                  <td>{getMetricLabel(a.metric)}</td>
                  <td>{formatThreshold(a.metric, a.threshold)}</td>
                  <td>
                    <span style={{ color: a.is_active ? "var(--green)" : "var(--muted)", fontSize: 10, textTransform: "uppercase" }}>
                      {a.is_active ? "Active" : "Paused"}
                    </span>
                  </td>
                  <td>{a.triggered_count}x</td>
                  <td>
                    <button
                      className="btn btn-red"
                      style={{ padding: "2px 8px", fontSize: 10 }}
                      onClick={() => handleDelete(a.id)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create modal */}
      {showCreate && (
        <>
          <div
            style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 100 }}
            onClick={() => setShowCreate(false)}
          />
          <div style={{
            position: "fixed",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            zIndex: 101,
            width: "100%",
            maxWidth: 480,
          }}>
            <div className="setup-card">
              <h1 style={{ fontSize: 18 }}>Create Alert Rule</h1>
              <p className="sub">Get notified when thresholds are exceeded.</p>

              <form onSubmit={handleCreate}>
                <div style={{ marginBottom: 12 }}>
                  <label className="form-label">Alert name</label>
                  <input className="form-input" required placeholder="Daily spend > $50" value={name} onChange={(e) => setName(e.target.value)} style={{ fontFamily: "var(--font-sans)" }} />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
                  <div>
                    <label className="form-label">Metric</label>
                    <select className="form-input" value={metric} onChange={(e) => setMetric(e.target.value)} style={{ appearance: "auto" }}>
                      {METRIC_OPTIONS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="form-label">Threshold</label>
                    <input className="form-input" type="number" step="0.01" required placeholder="50.00" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
                  <div>
                    <label className="form-label">Provider filter</label>
                    <select className="form-input" value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)} style={{ appearance: "auto" }}>
                      {PROVIDER_OPTIONS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="form-label">Model filter</label>
                    <input className="form-input" placeholder="claude-sonnet-4" value={modelFilter} onChange={(e) => setModelFilter(e.target.value)} />
                  </div>
                </div>

                <div style={{ marginBottom: 16 }}>
                  <label className="form-label">Webhook URL (optional)</label>
                  <input className="form-input" type="url" placeholder="https://hooks.slack.com/..." value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} />
                </div>

                <div style={{ display: "flex", gap: 8 }}>
                  <button type="button" className="btn" style={{ flex: 1 }} onClick={() => { resetForm(); setShowCreate(false); }}>Cancel</button>
                  <button type="submit" className="btn btn-cyan" style={{ flex: 2 }} disabled={saving || !name.trim() || !threshold}>
                    {saving ? "Creating..." : "Create Alert"}
                  </button>
                </div>
              </form>
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

"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";

interface Connection {
  id: string;
  provider: string;
  display_name: string;
  is_active: boolean;
  created_at: string;
}

const PROVIDERS = [
  { id: "anthropic", name: "Anthropic", desc: "Claude models" },
  { id: "openai", name: "OpenAI", desc: "GPT models" },
  { id: "google", name: "Google AI", desc: "Gemini models" },
];

function ConnectionsContent() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ provider: "anthropic", display_name: "", api_key: "" });
  const [submitting, setSubmitting] = useState(false);

  const fetchConnections = async () => {
    if (!session) return;
    try {
      const data = await apiFetch("/api/v1/connections", session.token);
      setConnections(data);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchConnections(); }, [session]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await apiFetch("/api/v1/connections", session!.apiKey, {
        method: "POST",
        body: JSON.stringify(form),
      });
      setAdding(false);
      setForm({ provider: "anthropic", display_name: "", api_key: "" });
      showToast("Connection added", "success");
      await fetchConnections();
    } catch (err: any) {
      showToast("Failed: " + err.message, "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!session || !confirm("Delete this connection?")) return;
    try {
      await apiFetch(`/api/v1/connections/${id}`, session.token, { method: "DELETE" });
      setConnections(connections.filter(c => c.id !== id));
      showToast("Connection deleted", "success");
    } catch (err: any) {
      showToast("Failed: " + err.message, "error");
    }
  };

  return (
    <div>
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Provider connections</span>
          <button className="section-header-action" onClick={() => setAdding(true)}>
            + Add
          </button>
        </div>

        {loading ? (
          <div style={{ padding: 16 }}>
            {[1, 2, 3].map((i) => (
              <div key={i} className="skeleton" style={{ height: 48, marginBottom: 8 }} />
            ))}
          </div>
        ) : connections.length === 0 ? (
          <EmptyState
            title="No provider connections yet"
            description="Connect Anthropic, OpenAI, or Google AI to let BurnLens discover your assets and track spend across providers. Credentials are encrypted at rest."
            action={{ label: "Add first connection", onClick: () => setAdding(true) }}
          />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Provider</th>
                <th>Status</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {connections.map((c) => (
                <tr key={c.id}>
                  <td style={{ fontWeight: 500 }}>{c.display_name}</td>
                  <td><span className="provider-badge">{c.provider}</span></td>
                  <td>
                    <span style={{ color: c.is_active ? "var(--green)" : "var(--muted)", fontSize: 10, textTransform: "uppercase" }}>
                      {c.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>{new Date(c.created_at).toLocaleDateString()}</td>
                  <td>
                    <button
                      className="btn btn-red"
                      style={{ padding: "2px 8px", fontSize: 10 }}
                      onClick={() => handleDelete(c.id)}
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

      {/* Add modal */}
      {adding && (
        <>
          <div
            style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 100 }}
            onClick={() => setAdding(false)}
          />
          <div style={{
            position: "fixed",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            zIndex: 101,
            width: "100%",
            maxWidth: 440,
          }}>
            <div className="setup-card">
              <h1 style={{ fontSize: 18 }}>Connect Provider</h1>
              <p className="sub">Credentials are encrypted at rest.</p>

              <form onSubmit={handleAdd}>
                <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
                  {PROVIDERS.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setForm({ ...form, provider: p.id })}
                      className={form.provider === p.id ? "btn btn-cyan" : "btn"}
                      style={{ flex: 1, padding: "8px", fontSize: 10 }}
                    >
                      {p.name}
                    </button>
                  ))}
                </div>

                <div style={{ marginBottom: 12 }}>
                  <label className="form-label">Display name</label>
                  <input
                    className="form-input"
                    required
                    placeholder="Production Account"
                    value={form.display_name}
                    onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                    style={{ fontFamily: "var(--font-sans)" }}
                  />
                </div>

                <div style={{ marginBottom: 16 }}>
                  <label className="form-label">API Key</label>
                  <input
                    className="form-input"
                    type="password"
                    required
                    placeholder="sk-..."
                    value={form.api_key}
                    onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  />
                </div>

                <div style={{ display: "flex", gap: 8 }}>
                  <button type="button" className="btn" style={{ flex: 1 }} onClick={() => setAdding(false)}>
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-cyan" style={{ flex: 2 }} disabled={submitting}>
                    {submitting ? "Saving..." : "Save"}
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

export default function ConnectionsPage() {
  return (
    <Shell>
      <ConnectionsContent />
    </Shell>
  );
}

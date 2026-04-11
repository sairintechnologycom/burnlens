"use client";

import { useEffect, useState } from "react";
import DashboardLayout from "@/components/DashboardLayout";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";
import { 
  Plus, 
  Trash2, 
  CheckCircle2, 
  AlertCircle, 
  Shield, 
  ExternalLink,
  ShieldCheck,
  Zap,
  Cpu,
  Globe
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface Connection {
  id: string;
  provider: string;
  display_name: string;
  is_active: boolean;
  created_at: string;
}

const PROVIDERS = [
  { id: "anthropic", name: "Anthropic", icon: Zap, color: "#D4A574", desc: "Claude 3.7 Sonnet, 3.5 Sonnet, Haiku" },
  { id: "openai", name: "OpenAI", icon: Cpu, color: "#74D4A5", desc: "GPT-4o, GPT-4o-mini, o1, o3-mini" },
  { id: "google", name: "Google AI", icon: Globe, color: "#74A5D4", desc: "Gemini 1.5 Pro, Flash, 2.0 Flash" },
];

export default function ConnectionsPage() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ provider: "anthropic", display_name: "", api_key: "" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const fetchConnections = async () => {
    if (!session) return;
    try {
      const data = await apiFetch("/api/v1/connections", session.apiKey);
      setConnections(data);
    } catch (err: any) {
      if (err instanceof AuthError) {
        showToast("Session expired. Please re-authenticate.", "error");
        logout();
      } else {
        console.error(err);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConnections();
  }, [session]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await apiFetch("/api/v1/connections", session!.apiKey, {
        method: "POST",
        body: JSON.stringify(form),
      });
      setAdding(false);
      setForm({ provider: "anthropic", display_name: "", api_key: "" });
      showToast("Connection added successfully", "success");
      await fetchConnections();
    } catch (err: any) {
      showToast("Failed to add connection: " + err.message, "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!session) return;
    if (!confirm("Are you sure? This will stop data collection for this account.")) return;
    try {
      await apiFetch(`/api/v1/connections/${id}`, session.apiKey, { method: "DELETE" });
      setConnections(connections.filter(c => c.id !== id));
      showToast("Connection deleted", "success");
    } catch (err: any) {
      showToast("Failed to delete connection: " + err.message, "error");
    }
  };

  return (
    <DashboardLayout>
      <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
        {/* ── Header ── */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">Connections</h1>
            <p className="text-muted text-sm" style={{ marginTop: 4 }}>Manage your LLM provider credentials securely.</p>
          </div>
          
          <button 
            onClick={() => setAdding(true)}
            className="btn btn-primary"
            style={{ padding: "0 20px", height: 40 }}
          >
            <Plus size={16} style={{ marginRight: 8 }} />
            Connect Provider
          </button>
        </div>

        {/* ── Existing Connections ── */}
        <div className="md-grid-3" style={{ gap: 24 }}>
          {loading ? (
            [1, 2, 3].map(i => <div key={i} className="animate-pulse" style={{ height: 192, background: "rgba(255,255,255,0.05)", borderRadius: 16 }} />)
          ) : connections.length > 0 ? (
            connections.map((conn) => {
              const pInfo = PROVIDERS.find(p => p.id === conn.provider);
              const Icon = pInfo?.icon || Shield;
              return (
                <motion.div 
                  key={conn.id}
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="card"
                  style={{ display: "flex", flexDirection: "column", height: "100%", padding: 24 }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
                    <div className="bg-white-5" style={{ width: 48, height: 48, borderRadius: 16, border: "1px solid rgba(255,255,255,0.05)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--primary)" }}>
                      <Icon size={24} />
                    </div>
                    <div className="bg-primary-5" style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 8px", borderRadius: 8, color: "var(--primary)", fontSize: 10, fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                      <CheckCircle2 size={10} />
                      ACTIVE
                    </div>
                  </div>
                  
                  <div style={{ flex: 1 }}>
                    <h3 className="text-white font-bold text-lg" style={{ marginBottom: 4 }}>{conn.display_name}</h3>
                    <p className="text-muted text-xs uppercase tracking-widest font-mono" style={{ marginBottom: 16 }}>{conn.provider}</p>
                  </div>

                  <div style={{ paddingTop: 24, borderTop: "1px solid rgba(255,255,255,0.05)", display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "auto" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, color: "rgba(255,255,255,0.3)", fontSize: 10, fontFamily: "var(--font-mono)" }}>
                      <ShieldCheck size={12} />
                      ENCRYPTED
                    </div>
                    <button 
                      onClick={() => handleDelete(conn.id)}
                      className="btn"
                      style={{ padding: 8, border: "none", background: "none" }}
                      onMouseEnter={(e) => e.currentTarget.style.color = "#ef4444"}
                      onMouseLeave={(e) => e.currentTarget.style.color = "var(--muted)"}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </motion.div>
              );
            })
          ) : (
            <div style={{ gridColumn: "1 / -1", padding: "80px 24px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", border: "2px dashed rgba(255,255,255,0.05)", borderRadius: 24, background: "rgba(255,255,255,0.01)" }}>
              <div className="bg-white-5" style={{ width: 64, height: 64, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", marginBottom: 24 }}>
                <Plus size={32} />
              </div>
              <h2 className="text-xl font-bold text-white" style={{ marginBottom: 8 }}>No connections yet</h2>
              <p className="text-muted text-sm" style={{ maxWidth: 320, marginBottom: 32 }}>Connect your first LLM provider to start tracking your AI spend.</p>
              <button 
                onClick={() => setAdding(true)}
                className="btn btn-primary"
                style={{ padding: "0 32px", height: 48 }}
              >
                Add Your First Account
              </button>
            </div>
          )}
        </div>

        {/* ── Add Connection Modal ── */}
        <AnimatePresence>
          {adding && (
            <div style={{ position: "fixed", inset: 0, zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
              <motion.div 
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.8)", backdropFilter: "blur(8px)" }} 
                onClick={() => setAdding(false)} 
              />
              <motion.div 
                initial={{ opacity: 0, scale: 0.9, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.9, y: 20 }}
                className="card"
                style={{ width: "100%", maxWidth: 512, background: "#0a0a14", borderColor: "rgba(255,255,255,0.1)", padding: 32, position: "relative", zIndex: 101, boxShadow: "0 24px 48px rgba(0,0,0,0.5)" }}
              >
                <div style={{ marginBottom: 32 }}>
                  <h2 className="text-2xl font-bold text-white" style={{ marginBottom: 8 }}>Connect New Provider</h2>
                  <p className="text-muted text-sm">Credentials are encrypted at rest and never leave this instance.</p>
                </div>

                {error && (
                  <div className="bg-red-500-10 border-red-500-20 text-red-500 text-sm" style={{ padding: 16, borderRadius: 12, marginBottom: 24, display: "flex", alignItems: "center", gap: 12 }}>
                    <AlertCircle size={18} />
                    {error}
                  </div>
                )}

                <form onSubmit={handleAdd} className="space-y-6">
                  {/* Provider Selection */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
                    {PROVIDERS.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => setForm({ ...form, provider: p.id })}
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "center",
                          gap: 12,
                          padding: 16,
                          borderRadius: 16,
                          border: "1px solid",
                          borderColor: form.provider === p.id ? "var(--primary)" : "rgba(255,255,255,0.05)",
                          background: form.provider === p.id ? "rgba(116,212,165,0.08)" : "rgba(255,255,255,0.02)",
                          color: form.provider === p.id ? "var(--primary)" : "var(--muted)",
                          transition: "all 0.2s ease",
                          cursor: "pointer"
                        }}
                      >
                        <p.icon size={24} />
                        <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--font-mono)" }}>
                          {p.name}
                        </span>
                      </button>
                    ))}
                  </div>

                  <div>
                    <label className="form-label">Display Name</label>
                    <input
                      type="text"
                      required
                      placeholder="e.g. Production Account"
                      className="form-input"
                      value={form.display_name}
                      onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                    />
                  </div>

                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                      <label className="form-label" style={{ marginBottom: 0 }}>API Key</label>
                      <a href="#" style={{ fontSize: 10, color: "var(--primary)", textDecoration: "none", display: "flex", alignItems: "center", gap: 4 }}>
                        Where to find this? <ExternalLink size={10} />
                      </a>
                    </div>
                    <div style={{ position: "relative" }}>
                      <input
                        type="password"
                        required
                        placeholder="sk-..."
                        className="form-input"
                        style={{ fontFamily: "var(--font-mono)" }}
                        value={form.api_key}
                        onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                      />
                      <Shield style={{ position: "absolute", right: 16, top: "50%", transform: "translateY(-50%)", color: "rgba(255,255,255,0.2)" }} size={18} />
                    </div>
                  </div>

                  <div style={{ paddingTop: 16, display: "flex", gap: 12 }}>
                    <button
                      type="button"
                      onClick={() => setAdding(false)}
                      className="btn"
                      style={{ flex: 1, height: 48 }}
                    >
                      Cancel
                    </button>
                    <button
                      disabled={submitting}
                      type="submit"
                      className="btn btn-primary"
                      style={{ flex: 2, height: 48 }}
                    >
                      {submitting ? (
                        <div className="w-5 h-5 animate-spin" style={{ border: "2px solid rgba(0,0,0,0.2)", borderTopColor: "rgba(0,0,0,1)", borderRadius: "50%" }} />
                      ) : (
                        <>
                          <CheckCircle2 size={18} style={{ marginRight: 8 }} />
                          Verify & Save
                        </>
                      )}
                    </button>
                  </div>
                </form>
              </motion.div>
            </div>
          )}
        </AnimatePresence>
      </div>
    </DashboardLayout>
  );
}

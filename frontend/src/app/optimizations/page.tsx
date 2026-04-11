"use client";

import { useEffect, useState } from "react";
import DashboardLayout from "@/components/DashboardLayout";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";
import { 
  CheckCircle2, 
  ShieldAlert, 
  ArrowRight,
  Zap,
  Cpu,
  Layers,
  Archive,
  Lightbulb,
  RefreshCw
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface Optimization {
  id: string;
  optimization_type: string;
  severity: string;
  title: string;
  detail: string;
  affected_model: string | null;
  affected_feature: string | null;
  current_monthly_cost: number;
  projected_monthly_cost: number;
  monthly_savings: number;
  confidence_pct: number;
  is_applied: boolean;
  is_dismissed: boolean;
}

const TYPE_ICONS: Record<string, any> = {
  model_downgrade: Cpu,
  legacy_model: Cpu,
  prompt_caching: Zap,
  batch_eligible: Layers,
  prompt_compression: Archive,
  provider_arbitrage: ShieldAlert,
};

export default function OptimizationsPage() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [opts, setOpts] = useState<Optimization[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);

  const fetchOpts = async () => {
    if (!session) return;
    try {
      const data = await apiFetch("/api/v1/optimizations", session.apiKey);
      setOpts(data);
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
    fetchOpts();
  }, [session]);

  const handleApply = async (id: string) => {
    try {
      await apiFetch(`/api/v1/optimizations/${id}/apply`, session!.apiKey, { method: "POST" });
      setOpts(opts.filter(o => o.id !== id));
      showToast("Optimization applied successfully", "success");
    } catch (err: any) {
      showToast("Failed to apply optimization: " + err.message, "error");
    }
  };

  const handleDismiss = async (id: string) => {
    try {
      await apiFetch(`/api/v1/optimizations/${id}/dismiss`, session!.apiKey, { method: "POST" });
      setOpts(opts.filter(o => o.id !== id));
      showToast("Optimization dismissed", "info");
    } catch (err: any) {
      showToast("Failed to dismiss: " + err.message, "error");
    }
  };

  const handleTrigger = async () => {
    if (!session) return;
    setTriggering(true);
    try {
      await apiFetch("/api/v1/optimize", session.apiKey, { method: "POST" });
      setTimeout(fetchOpts, 3000);
    } catch (err: any) {
      alert("Trigger failed: " + err.message);
    } finally {
      setTriggering(false);
    }
  };

  const getSeverityStyle = (severity: string) => {
    switch (severity) {
      case "critical": return { background: "rgba(239, 68, 68, 0.1)", color: "#ef4444", borderColor: "rgba(239, 68, 68, 0.2)" };
      case "high": return { background: "rgba(249, 115, 22, 0.1)", color: "#fb923c", borderColor: "rgba(249, 115, 22, 0.2)" };
      case "medium": return { background: "rgba(59, 130, 246, 0.1)", color: "#60a5fa", borderColor: "rgba(59, 130, 246, 0.2)" };
      default: return { background: "rgba(16, 185, 129, 0.1)", color: "#10b981", borderColor: "rgba(16, 185, 129, 0.2)" };
    }
  };

  const totalSavings = opts.reduce((sum, opt) => sum + (opt.monthly_savings || 0), 0);

  return (
    <DashboardLayout>
      <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
        {/* ── Header ── */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">Optimizations</h1>
            <p className="text-muted text-sm" style={{ marginTop: 4 }}>Rule-based recommendations to reduce your AI operational costs.</p>
          </div>
          
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <button 
              onClick={handleTrigger}
              disabled={triggering}
              className="btn"
              style={{ padding: "0 20px", height: 40 }}
            >
              <RefreshCw size={16} className={triggering ? "animate-spin" : ""} style={{ marginRight: 8 }} />
              {triggering ? "Running..." : "Run Analysis"}
            </button>
            {totalSavings > 0 && (
              <div className="card" style={{ padding: "8px 16px", display: "flex", alignItems: "center", gap: 12, borderColor: "rgba(16, 185, 129, 0.2)", background: "rgba(16, 185, 129, 0.05)" }}>
                <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", fontFamily: "var(--font-mono)" }}>Projected Monthly Savings</span>
                <span style={{ color: "#10b981", fontWeight: 700, fontFamily: "var(--font-mono)" }}>${totalSavings.toFixed(2)}</span>
              </div>
            )}
          </div>
        </div>

        {/* ── Optimizations List ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {loading ? (
            [1, 2, 3].map(i => <div key={i} className="animate-pulse" style={{ height: 128, background: "rgba(255,255,255,0.05)", borderRadius: 16 }} />)
          ) : opts.length > 0 ? (
            opts.map((opt, i) => {
              const Icon = TYPE_ICONS[opt.optimization_type] || Zap;
              const severityLabel = opt.severity || "low";
              return (
                <motion.div 
                  key={opt.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className="card"
                  style={{ padding: 0, display: "flex", flexDirection: "row", overflow: "hidden", borderLeft: `4px solid ${getSeverityStyle(severityLabel).color}` }}
                >
                  <div style={{ flex: 1, padding: 24, display: "flex", flexDirection: "row", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
                    <div className="bg-white-5" style={{ width: 48, height: 48, borderRadius: 16, border: "1px solid rgba(255,255,255,0.05)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--primary)", flexShrink: 0 }}>
                      <Icon size={24} />
                    </div>

                    <div style={{ flex: 1, minWidth: 200 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                        <span style={{ 
                          padding: "2px 8px", 
                          borderRadius: 4, 
                          fontSize: 9, 
                          fontWeight: 700, 
                          textTransform: "uppercase", 
                          letterSpacing: "0.08em", 
                          border: "1px solid",
                          ...getSeverityStyle(severityLabel)
                        }}>
                          {severityLabel}
                        </span>
                        <span style={{ color: "var(--muted)", fontSize: 10, fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                          {opt.optimization_type.replace(/_/g, " ")}
                        </span>
                      </div>
                      <h3 className="text-white font-bold text-lg" style={{ marginBottom: 4 }}>{opt.title}</h3>
                      <p className="text-muted text-sm">{opt.detail}</p>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: 4, width: 160 }}>
                      <span style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--font-mono)" }}>Monthly Savings</span>
                      <span style={{ color: "var(--primary)", fontSize: 20, fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                        -${(opt.monthly_savings || 0).toFixed(2)}
                      </span>
                      <span style={{ fontSize: 9, color: "var(--muted)", fontFamily: "var(--font-mono)" }}>
                        {opt.confidence_pct}% confidence
                      </span>
                    </div>

                    <div style={{ display: "flex", gap: 12, paddingLeft: 24, borderLeft: "1px solid rgba(255,255,255,0.05)" }}>
                      <button 
                        onClick={() => handleApply(opt.id)}
                        className="btn btn-primary"
                        style={{ padding: "0 20px", height: 40, fontSize: 12 }}
                      >
                        Apply <ArrowRight size={14} style={{ marginLeft: 6 }} />
                      </button>
                      <button 
                        onClick={() => handleDismiss(opt.id)}
                        className="btn"
                        style={{ padding: "0 12px", height: 40 }}
                      >
                        <Archive size={16} />
                      </button>
                    </div>
                  </div>
                </motion.div>
              );
            })
          ) : (
            <div className="card" style={{ padding: "80px 24px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", borderStyle: "dashed", background: "rgba(255,255,255,0.01)" }}>
              <div className="bg-white-5" style={{ width: 64, height: 64, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", marginBottom: 24 }}>
                <Lightbulb size={32} />
              </div>
              <h2 className="text-xl font-bold text-white" style={{ marginBottom: 8 }}>No recommendations yet</h2>
              <p className="text-muted text-sm" style={{ maxWidth: 360, marginBottom: 24 }}>
                Our optimization engine needs usage data to generate reliable recommendations. Seed demo data or connect a provider first.
              </p>
              <button onClick={handleTrigger} className="btn btn-primary" style={{ padding: "0 24px", height: 44 }}>
                <RefreshCw size={16} style={{ marginRight: 8 }} />
                Run Analysis Now
              </button>
            </div>
          )}
        </div>

        {/* ── Info Grid ── */}
        <div className="md-grid-3" style={{ gap: 40, paddingTop: 40, borderTop: "1px solid rgba(255,255,255,0.05)" }}>
          <div style={{ display: "flex", gap: 16 }}>
            <div style={{ color: "var(--primary)", flexShrink: 0 }}><Cpu size={24} /></div>
            <div>
              <h4 className="text-white font-bold text-sm" style={{ marginBottom: 4 }}>Model Right-Sizing</h4>
              <p className="text-muted text-xs" style={{ lineHeight: 1.6 }}>Identifies cases where cheaper models can handle tasks with high confidence.</p>
            </div>
          </div>
          <div style={{ display: "flex", gap: 16 }}>
            <div style={{ color: "var(--primary)", flexShrink: 0 }}><Zap size={24} /></div>
            <div>
              <h4 className="text-white font-bold text-sm" style={{ marginBottom: 4 }}>Prompt Caching</h4>
              <p className="text-muted text-xs" style={{ lineHeight: 1.6 }}>Detects repetitive system prompts that benefit from input caching (up to 50% discount).</p>
            </div>
          </div>
          <div style={{ display: "flex", gap: 16 }}>
            <div style={{ color: "var(--primary)", flexShrink: 0 }}><Layers size={24} /></div>
            <div>
              <h4 className="text-white font-bold text-sm" style={{ marginBottom: 4 }}>Batch Processing</h4>
              <p className="text-muted text-xs" style={{ lineHeight: 1.6 }}>Flags async-tolerant workloads that can be moved to Batch APIs for 50% flat discounts.</p>
            </div>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";

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
}

function OptimizationsContent() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [opts, setOpts] = useState<Optimization[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);

  const fetchOpts = async () => {
    if (!session) return;
    try {
      const data = await apiFetch("/api/v1/optimizations", session.token);
      setOpts(data);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchOpts(); }, [session]);

  const handleApply = async (id: string) => {
    try {
      await apiFetch(`/api/v1/optimizations/${id}/apply`, session!.apiKey, { method: "POST" });
      setOpts(opts.filter(o => o.id !== id));
      showToast("Applied", "success");
    } catch (err: any) {
      showToast("Failed: " + err.message, "error");
    }
  };

  const handleDismiss = async (id: string) => {
    try {
      await apiFetch(`/api/v1/optimizations/${id}/dismiss`, session!.apiKey, { method: "POST" });
      setOpts(opts.filter(o => o.id !== id));
      showToast("Dismissed", "info");
    } catch (err: any) {
      showToast("Failed: " + err.message, "error");
    }
  };

  const handleTrigger = async () => {
    if (!session) return;
    setTriggering(true);
    try {
      await apiFetch("/api/v1/optimize", session.token, { method: "POST" });
      setTimeout(fetchOpts, 3000);
    } catch (err: any) {
      showToast("Failed: " + err.message, "error");
    } finally {
      setTriggering(false);
    }
  };

  const totalSavings = opts.reduce((sum, o) => sum + (o.monthly_savings || 0), 0);

  return (
    <div>
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Optimizations</span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {totalSavings > 0 && (
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--green)" }}>
                Save ${totalSavings.toFixed(2)}/mo
              </span>
            )}
            <button className="section-header-action" onClick={handleTrigger} disabled={triggering}>
              {triggering ? "Running..." : "Run analysis"}
            </button>
          </div>
        </div>

        {loading ? (
          <div style={{ padding: 16 }}>
            {[1, 2, 3].map((i) => (
              <div key={i} className="skeleton" style={{ height: 80, marginBottom: 8 }} />
            ))}
          </div>
        ) : opts.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>No recommendations yet</div>
            <button className="btn btn-cyan" onClick={handleTrigger}>
              Run analysis
            </button>
          </div>
        ) : (
          opts.map((opt) => (
            <div key={opt.id} style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span className={`severity-badge severity-${opt.severity || "medium"}`}>
                  {opt.severity || "low"}
                </span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
                  {opt.optimization_type.replace(/_/g, " ")}
                </span>
              </div>
              <div style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: 13, color: "var(--text)", marginBottom: 4 }}>
                {opt.title}
              </div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>{opt.detail}</div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--green)" }}>
                    Save ${opt.monthly_savings.toFixed(2)}/mo
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--muted)" }}>
                    {opt.confidence_pct}% confidence
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="btn btn-cyan" style={{ padding: "2px 10px", fontSize: 10 }} onClick={() => handleApply(opt.id)}>
                    Apply
                  </button>
                  <button className="btn" style={{ padding: "2px 10px", fontSize: 10 }} onClick={() => handleDismiss(opt.id)}>
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function OptimizationsPage() {
  return (
    <Shell>
      <OptimizationsContent />
    </Shell>
  );
}

"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";

interface WasteAlert {
  id: string;
  severity: "critical" | "high" | "medium";
  title: string;
  description: string;
  model?: string;
  feature?: string;
  current_cost: number;
  projected_cost: number;
  monthly_savings: number;
}

interface Recommendation {
  id: string;
  title: string;
  description: string;
  command?: string;
  monthly_savings: number;
}

function WasteContent() {
  const { session, logout } = useAuth();
  const [alerts, setAlerts] = useState<WasteAlert[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    Promise.all([
      apiFetch("/api/v1/waste-alerts", session.apiKey).catch(() => []),
      apiFetch("/api/v1/recommendations", session.apiKey).catch(() => []),
    ])
      .then(([a, r]) => {
        setAlerts(a as WasteAlert[]);
        setRecommendations(r as Recommendation[]);
      })
      .catch((err) => {
        if (err instanceof AuthError) logout();
        else setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [session, logout]);

  const dismiss = (id: string) => {
    setDismissed((prev) => new Set(prev).add(id));
  };

  const activeAlerts = alerts.filter((a) => !dismissed.has(a.id));

  // Waste summary percentages (mock breakdown)
  const totalWaste = activeAlerts.reduce((sum, a) => sum + a.monthly_savings, 0);

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        {[1, 2, 3].map((i) => (
          <div key={i} className="skeleton" style={{ height: 100, marginBottom: 12 }} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={() => window.location.reload()}>
          Failed to load — retry &#x2197;
        </span>
      </div>
    );
  }

  return (
    <div>
      {/* Active alerts */}
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Active alerts</span>
          <span className="section-header-action">{activeAlerts.length} active</span>
        </div>
        {activeAlerts.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", fontSize: 11, color: "var(--muted)" }}>
            No active waste alerts
          </div>
        ) : (
          activeAlerts.map((a) => (
            <div key={a.id} style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span className={`severity-badge severity-${a.severity}`}>{a.severity}</span>
                <span style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: 13, color: "var(--text)" }}>
                  {a.title}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6, lineHeight: 1.4 }}>
                {a.description}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
                {a.model && <span className="tag tag-feature">{a.model}</span>}
                {a.feature && <span className="tag tag-team">{a.feature}</span>}
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", gap: 16 }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--muted)" }}>
                    Current: ${a.current_cost.toFixed(2)}/mo
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--muted)" }}>
                    Projected: ${a.projected_cost.toFixed(2)}/mo
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--green)" }}>
                    Save ${a.monthly_savings.toFixed(2)}/mo
                  </span>
                </div>
                <button
                  onClick={() => dismiss(a.id)}
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "var(--muted)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                  }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Recommendations */}
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Model recommendations</span>
        </div>
        {recommendations.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", fontSize: 11, color: "var(--muted)" }}>
            No recommendations
          </div>
        ) : (
          recommendations.map((r) => (
            <div key={r.id} style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }}>
              <div style={{ fontFamily: "var(--font-sans)", fontWeight: 600, fontSize: 13, color: "var(--text)", marginBottom: 4 }}>
                {r.title}
              </div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>{r.description}</div>
              {r.command && (
                <code style={{
                  display: "block",
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  color: "var(--cyan)",
                  background: "var(--bg2)",
                  padding: "6px 10px",
                  borderRadius: 3,
                  marginBottom: 6,
                }}>
                  {r.command}
                </code>
              )}
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--green)" }}>
                Save ${r.monthly_savings.toFixed(2)}/mo
              </span>
            </div>
          ))
        )}
      </div>

      {/* Waste summary */}
      {totalWaste > 0 && (
        <div className="card" style={{ margin: 16 }}>
          <div className="section-header">
            <span className="section-header-title">Waste summary</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--amber)" }}>
              ${totalWaste.toFixed(2)}/mo total
            </span>
          </div>
          <div style={{ padding: 16 }}>
            <div style={{
              height: 8,
              borderRadius: 4,
              background: "var(--bg3)",
              overflow: "hidden",
              display: "flex",
            }}>
              <div style={{ width: "35%", background: "var(--amber)", opacity: 0.7 }} />
              <div style={{ width: "25%", background: "var(--red)", opacity: 0.6 }} />
              <div style={{ width: "20%", background: "var(--amber)", opacity: 0.5 }} />
              <div style={{ width: "20%", background: "var(--red)", opacity: 0.4 }} />
            </div>
            <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
              {[
                { label: "Duplicate", pct: 35 },
                { label: "Bloat", pct: 25 },
                { label: "Overkill", pct: 20 },
                { label: "Prompt", pct: 20 },
              ].map((w) => (
                <span key={w.label} style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--muted)" }}>
                  {w.label} {w.pct}%
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function WastePage() {
  return (
    <Shell>
      <WasteContent />
    </Shell>
  );
}

"use client";

import { useEffect, useState } from "react";
import { usePeriod } from "@/lib/contexts/PeriodContext";
import { useAuth } from "@/lib/hooks/useAuth";
import { apiFetch } from "@/lib/api";

interface ModelEntry {
  model: string;
  total_cost: number;
}

interface WasteAlert {
  id: string;
  severity: "critical" | "high" | "medium";
  title: string;
  description: string;
  monthly_savings: number;
}

export default function RightPanel() {
  const { days } = usePeriod();
  const { session } = useAuth();
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [alerts, setAlerts] = useState<WasteAlert[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    Promise.all([
      apiFetch(`/api/v1/usage/by-model?days=${days}`, session.apiKey).catch(() => []),
      apiFetch(`/api/v1/waste-alerts`, session.apiKey).catch(() => []),
    ]).then(([m, a]) => {
      setModels((m as any[]).slice(0, 4));
      setAlerts((a as any[]).slice(0, 3));
    }).finally(() => setLoading(false));
  }, [session, days]);

  const maxCost = models.length > 0 ? models[0].total_cost : 1;

  return (
    <aside className="right-panel">
      {/* By Model */}
      <div className="rp-section-header">By model</div>
      {loading ? (
        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton" style={{ height: 32 }} />
          ))}
        </div>
      ) : models.length === 0 ? (
        <div style={{ padding: 16, fontSize: 11, color: "var(--muted)" }}>No data yet</div>
      ) : (
        models.map((m, i) => (
          <div key={m.model} className="rp-model-row">
            <span className="rp-model-rank">{i + 1}</span>
            <div>
              <div className="rp-model-name">{m.model}</div>
              <div
                className="rp-model-bar"
                style={{ width: `${(m.total_cost / maxCost) * 100}%` }}
              />
            </div>
            <span className="rp-model-cost">${m.total_cost.toFixed(2)}</span>
          </div>
        ))
      )}

      {/* Waste Alerts */}
      <div className="rp-section-header">Waste alerts</div>
      {loading ? (
        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 48 }} />
          ))}
        </div>
      ) : alerts.length === 0 ? (
        <div style={{ padding: 16, fontSize: 11, color: "var(--muted)" }}>No active alerts</div>
      ) : (
        alerts.map((a) => (
          <div key={a.id} className="rp-alert-item">
            <span className={`rp-alert-severity ${a.severity}`}>
              {a.severity}
            </span>
            <div className="rp-alert-title">{a.title}</div>
            <div className="rp-alert-desc">{a.description}</div>
            <div className="rp-alert-savings">Save ${a.monthly_savings.toFixed(2)}/mo</div>
          </div>
        ))
      )}
    </aside>
  );
}

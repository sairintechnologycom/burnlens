"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import HorizontalBar from "@/components/charts/HorizontalBar";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";

interface ModelData {
  model: string;
  provider: string;
  api_calls: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
}

function ModelsContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [models, setModels] = useState<ModelData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    apiFetch(`/api/v1/usage/by-model?days=${days}`, session.token)
      .then((data) => setModels(data as ModelData[]))
      .catch((err) => {
        if (err instanceof AuthError) logout();
        else setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [session, days, logout]);

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div className="skeleton" style={{ height: 300, marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 200 }} />
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
      {/* Chart */}
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Cost by model</span>
          <span className="section-header-action">{days}d</span>
        </div>
        {models.length > 0 ? (
          <HorizontalBar
            labels={models.map((m) => m.model)}
            data={models.map((m) => m.total_cost)}
            height={Math.max(200, models.length * 36)}
          />
        ) : (
          <div style={{ padding: 32, textAlign: "center", fontSize: 11, color: "var(--muted)" }}>
            No model data
          </div>
        )}
      </div>

      {/* Detail table */}
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Model breakdown</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Model</th>
              <th>Provider</th>
              <th>Requests</th>
              <th>Tokens in</th>
              <th>Tokens out</th>
              <th>Total cost</th>
              <th>Avg / req</th>
            </tr>
          </thead>
          <tbody>
            {models.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                  No data yet
                </td>
              </tr>
            ) : (
              models.map((m) => (
                <tr key={m.model}>
                  <td style={{ fontWeight: 500 }}>{m.model}</td>
                  <td><span className="provider-badge">{m.provider}</span></td>
                  <td>{m.api_calls.toLocaleString()}</td>
                  <td>{(m.input_tokens || 0).toLocaleString()}</td>
                  <td>{(m.output_tokens || 0).toLocaleString()}</td>
                  <td style={{ fontWeight: 500 }}>${m.total_cost.toFixed(2)}</td>
                  <td>${(m.api_calls > 0 ? m.total_cost / m.api_calls : 0).toFixed(4)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function ModelsPage() {
  return (
    <Shell>
      <ModelsContent />
    </Shell>
  );
}

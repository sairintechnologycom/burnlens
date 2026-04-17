"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import BarChart from "@/components/charts/BarChart";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";

interface FeatureRow {
  feature: string;
  total_cost: number;
  api_calls: number;
}

function formatCost(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function FeaturesContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [features, setFeatures] = useState<FeatureRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch(`/api/v1/usage/by-feature?days=${days}`, session.token);
      setFeatures(data as FeatureRow[]);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, days, logout]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const totalCost = features.reduce((s, f) => s + f.total_cost, 0);

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div className="skeleton" style={{ height: 200, marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 200 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={fetchData}>Couldn’t reach server — retry &#x2197;</span>
      </div>
    );
  }

  return (
    <div>
      <div className="stat-strip">
        <div className="stat-cell">
          <div className="stat-label">Features tracked</div>
          <div className="stat-value">{features.length}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Total cost</div>
          <div className="stat-value cyan">${formatCost(totalCost)}</div>
        </div>
      </div>

      {features.length > 0 && (
        <div className="card" style={{ margin: 16, marginBottom: 0 }}>
          <div className="section-header">
            <span className="section-header-title">Cost by feature</span>
            <span className="section-header-action">{days}d</span>
          </div>
          <BarChart
            labels={features.map((f) => f.feature || "untagged")}
            data={features.map((f) => f.total_cost)}
            height={200}
          />
        </div>
      )}

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Feature breakdown</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Feature</th>
              <th>Cost</th>
              <th>Requests</th>
              <th>% of total</th>
            </tr>
          </thead>
          <tbody>
            {features.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                  No feature tags found. Add X-BurnLens-Tag-Feature headers to your requests.
                </td>
              </tr>
            ) : (
              features.map((f, i) => (
                <tr key={i}>
                  <td><span className="tag tag-feature">{f.feature || "untagged"}</span></td>
                  <td style={{ color: "var(--cyan)" }}>${formatCost(f.total_cost)}</td>
                  <td>{f.api_calls.toLocaleString()}</td>
                  <td>{totalCost > 0 ? ((f.total_cost / totalCost) * 100).toFixed(1) : "0.0"}%</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function FeaturesPage() {
  return (
    <Shell>
      <FeaturesContent />
    </Shell>
  );
}

"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import BarChart from "@/components/charts/BarChart";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";

interface TimeseriesPoint {
  date: string;
  provider: string;
  cost: number;
  calls: number;
}

function formatCost(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function TimelineContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [timeseries, setTimeseries] = useState<{ label: string; cost: number; calls: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const ts = await apiFetch(`/api/v1/usage/timeseries?days=${days}&granularity=day`, session.apiKey);
      const byDate: Record<string, { cost: number; calls: number }> = {};
      (ts as TimeseriesPoint[]).forEach((p) => {
        if (!byDate[p.date]) byDate[p.date] = { cost: 0, calls: 0 };
        byDate[p.date].cost += p.cost || 0;
        byDate[p.date].calls += p.calls || 0;
      });
      const sorted = Object.entries(byDate)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, v]) => ({
          label: new Date(date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
          cost: v.cost,
          calls: v.calls,
        }));
      setTimeseries(sorted);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, days, logout]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const totalCost = timeseries.reduce((s, d) => s + d.cost, 0);
  const totalCalls = timeseries.reduce((s, d) => s + d.calls, 0);

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div className="skeleton" style={{ height: 300 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={fetchData}>Failed to load — retry &#x2197;</span>
      </div>
    );
  }

  return (
    <div>
      <div className="stat-strip">
        <div className="stat-cell">
          <div className="stat-label">Period total</div>
          <div className="stat-value cyan">${formatCost(totalCost)}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Total requests</div>
          <div className="stat-value">{totalCalls.toLocaleString()}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Daily avg</div>
          <div className="stat-value">${formatCost(timeseries.length > 0 ? totalCost / timeseries.length : 0)}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Days</div>
          <div className="stat-value">{timeseries.length}</div>
        </div>
      </div>

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Cost timeline</span>
          <span className="section-header-action">{days}d</span>
        </div>
        {timeseries.length > 0 ? (
          <BarChart
            labels={timeseries.map((d) => d.label)}
            data={timeseries.map((d) => d.cost)}
            height={300}
          />
        ) : (
          <div style={{ padding: 32, textAlign: "center", fontSize: 11, color: "var(--muted)" }}>
            No spend data for this period
          </div>
        )}
      </div>

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Daily breakdown</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Cost</th>
              <th>Requests</th>
              <th>Avg / req</th>
            </tr>
          </thead>
          <tbody>
            {timeseries.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                  No data
                </td>
              </tr>
            ) : (
              [...timeseries].reverse().map((d, i) => (
                <tr key={i}>
                  <td>{d.label}</td>
                  <td style={{ color: "var(--cyan)" }}>${d.cost.toFixed(4)}</td>
                  <td>{d.calls}</td>
                  <td>${d.calls > 0 ? (d.cost / d.calls).toFixed(4) : "0.0000"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function TimelinePage() {
  return (
    <Shell>
      <TimelineContent />
    </Shell>
  );
}

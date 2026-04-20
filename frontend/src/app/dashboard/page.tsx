"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Shell from "@/components/Shell";
import BarChart from "@/components/charts/BarChart";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";

interface SummaryData {
  total_cost: number;
  total_tokens: number;
  total_calls: number;
  by_provider: any[];
  by_model: any[];
}

interface TimeseriesPoint {
  date: string;
  cost: number;
}

interface RequestRecord {
  timestamp: string;
  model: string;
  feature?: string;
  team?: string;
  cost: number;
  latency_ms?: number;
}

function formatCost(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function latencyClass(ms: number): string {
  if (ms < 1000) return "latency-fast";
  if (ms <= 3000) return "latency-mid";
  return "latency-slow";
}

function DashboardContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [timeseries, setTimeseries] = useState<{ label: string; cost: number }[]>([]);
  const [requests, setRequests] = useState<RequestRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [requestLimit, setRequestLimit] = useState(20);

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [sum, ts, reqs] = await Promise.all([
        apiFetch(`/api/v1/usage/summary?days=${days}`, session.token),
        apiFetch(`/api/v1/usage/timeseries?days=${days}&granularity=day`, session.token).catch(() => []),
        apiFetch(`/api/v1/requests?days=${days}&limit=${requestLimit}`, session.token).catch(() => []),
      ]);
      setSummary(sum);

      // Aggregate timeseries by date
      const byDate: Record<string, number> = {};
      (ts as any[]).forEach((p: any) => {
        byDate[p.date] = (byDate[p.date] || 0) + (p.cost || 0);
      });
      const sorted = Object.entries(byDate)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, cost]) => ({
          label: new Date(date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
          cost,
        }));
      setTimeseries(sorted);
      setRequests(reqs as RequestRecord[]);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, days, requestLimit, logout]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const totalCost = summary?.total_cost ?? 0;
  const totalCalls = summary?.total_calls ?? 0;
  const wasteAmount = totalCost * 0.15; // estimate
  const avgPerReq = totalCalls > 0 ? totalCost / totalCalls : 0;

  if (loading && !summary) {
    return (
      <div>
        <div className="stat-strip">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="stat-cell">
              <div className="skeleton" style={{ height: 12, width: 60, marginBottom: 8 }} />
              <div className="skeleton" style={{ height: 24, width: 100 }} />
            </div>
          ))}
        </div>
        <div style={{ padding: 16 }}>
          <div className="skeleton" style={{ height: 200, marginBottom: 16 }} />
          <div className="skeleton" style={{ height: 300 }} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={fetchData}>
          Couldn’t reach server — retry &#x2197;
        </span>
      </div>
    );
  }

  const hasData = totalCalls > 0;

  return (
    <div>
      {/* Stat strip */}
      <div className="stat-strip">
        <div className="stat-cell">
          <div className="stat-label">Total spend</div>
          <div className="stat-value">
            {hasData ? `$${formatCost(summary?.total_cost ?? 0)}` : <span style={{ color: "var(--dim)" }}>—</span>}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Requests</div>
          <div className="stat-value">
            {hasData ? (summary?.total_calls ?? 0).toLocaleString() : <span style={{ color: "var(--dim)" }}>—</span>}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Avg / req</div>
          <div className="stat-value">
            {hasData ? `$${formatCost(avgPerReq)}` : <span style={{ color: "var(--dim)" }}>—</span>}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Waste</div>
          <div className={`stat-value${wasteAmount > 0 ? " amber" : ""}`}>
            {hasData ? `$${formatCost(wasteAmount)}` : <span style={{ color: "var(--dim)" }}>—</span>}
          </div>
        </div>
      </div>

      {!hasData && (
        <div className="card" style={{ margin: 16, padding: 32 }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, textAlign: "center" }}>
            <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text)" }}>
              Connect your first provider
            </div>
            <div style={{ fontSize: 13, color: "var(--muted)", maxWidth: 480, lineHeight: 1.5 }}>
              Install BurnLens locally, point your SDK at the proxy, and spend shows up here within seconds.
              No code changes, no account required to start.
            </div>
            <div className="empty-state-code" style={{ marginTop: 8 }}>
              <span className="empty-state-code-prompt">$</span>pip install burnlens &amp;&amp; burnlens start
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <Link href="/setup" className="upgrade-btn" style={{ textDecoration: "none" }}>Setup guide</Link>
              <Link href="/connections" className="period-btn" style={{ textDecoration: "none" }}>Connections</Link>
            </div>
          </div>
        </div>
      )}

      {/* Daily spend chart */}
      {hasData && (
        <div className="card" style={{ margin: 16, marginBottom: 0 }}>
          <div className="section-header">
            <span className="section-header-title">Daily spend</span>
            <span className="section-header-action">{days}d</span>
          </div>
          {timeseries.length > 0 ? (
            <BarChart
              labels={timeseries.map((d) => d.label)}
              data={timeseries.map((d) => d.cost)}
              height={180}
            />
          ) : (
            <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "var(--muted)" }}>
              No spend data for this period
            </div>
          )}
        </div>
      )}

      {/* Recent requests table */}
      {hasData && (
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Recent requests</span>
          <span className="section-header-action">{requests.length} shown</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Model</th>
              <th>Feature</th>
              <th>Team</th>
              <th>Cost</th>
              <th>ms</th>
            </tr>
          </thead>
          <tbody>
            {requests.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                  No requests yet
                </td>
              </tr>
            ) : (
              requests.map((r, i) => (
                <tr key={i}>
                  <td>{new Date(r.timestamp).toLocaleTimeString()}</td>
                  <td>{r.model}</td>
                  <td>
                    {r.feature ? (
                      <span className="tag tag-feature">{r.feature}</span>
                    ) : (
                      <span style={{ color: "var(--dim)" }}>—</span>
                    )}
                  </td>
                  <td>
                    {r.team ? (
                      <span className="tag tag-team">{r.team}</span>
                    ) : (
                      <span style={{ color: "var(--dim)" }}>—</span>
                    )}
                  </td>
                  <td style={{ color: r.cost > 0.01 ? "var(--amber)" : undefined }}>
                    ${r.cost.toFixed(4)}
                  </td>
                  <td className={r.latency_ms ? latencyClass(r.latency_ms) : ""}>
                    {r.latency_ms ? `${r.latency_ms}` : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {requests.length >= requestLimit && (
          <button className="load-more" onClick={() => setRequestLimit((l) => l + 20)}>
            load more
          </button>
        )}
      </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Shell>
      <DashboardContent />
    </Shell>
  );
}

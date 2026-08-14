"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */


import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";
import type { RequestRow } from "@/lib/contracts";

function latencyClass(ms: number): string {
  if (ms < 1000) return "latency-fast";
  if (ms <= 3000) return "latency-mid";
  return "latency-slow";
}

function RequestsContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [limit, setLimit] = useState(50);

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch(`/api/v1/requests?days=${days}&limit=${limit}`, session.token);
      setRequests(data as RequestRow[]);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, days, limit, logout]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading && requests.length === 0) {
    return (
      <div style={{ padding: 16 }}>
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="skeleton" style={{ height: 32, marginBottom: 4 }} />
        ))}
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
          <div className="stat-label">Showing</div>
          <div className="stat-value">{requests.length} requests</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Total cost</div>
          <div className="stat-value cyan">
            ${requests.reduce((s, r) => s + (r.cost_usd ?? 0), 0).toFixed(4)}
          </div>
        </div>
      </div>

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Request log</span>
          <span className="section-header-action">{days}d</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Provider</th>
              <th>Model</th>
              <th>Feature</th>
              <th>Team</th>
              <th>In tokens</th>
              <th>Out tokens</th>
              <th>Cost</th>
              <th>Latency</th>
            </tr>
          </thead>
          <tbody>
            {requests.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                  No requests yet
                </td>
              </tr>
            ) : (
              requests.map((r, i) => (
                <tr key={i}>
                  <td>{new Date(r.timestamp).toLocaleString()}</td>
                  <td>{r.provider}</td>
                  <td>{r.model}</td>
                  <td>
                    {r.tags?.feature ? (
                      <span className="tag tag-feature">{r.tags.feature}</span>
                    ) : (
                      <span style={{ color: "var(--dim)" }}>—</span>
                    )}
                  </td>
                  <td>
                    {r.tags?.team ? (
                      <span className="tag tag-team">{r.tags.team}</span>
                    ) : (
                      <span style={{ color: "var(--dim)" }}>—</span>
                    )}
                  </td>
                  <td>{r.input_tokens?.toLocaleString() ?? "—"}</td>
                  <td>{r.output_tokens?.toLocaleString() ?? "—"}</td>
                  <td style={{ color: (r.cost_usd ?? 0) > 0.01 ? "var(--amber)" : undefined }}>
                    ${(r.cost_usd ?? 0).toFixed(4)}
                  </td>
                  <td className={r.duration_ms ? latencyClass(r.duration_ms) : ""}>
                    {r.duration_ms ? `${r.duration_ms}ms` : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {requests.length >= limit && (
          <button className="load-more" onClick={() => setLimit((l) => l + 50)}>
            load more
          </button>
        )}
      </div>
    </div>
  );
}

export default function RequestsPage() {
  return (
    <Shell>
      <RequestsContent />
    </Shell>
  );
}

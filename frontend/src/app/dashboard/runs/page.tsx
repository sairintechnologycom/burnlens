"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";

interface Run {
  run_id: string;
  step_count: number;
  cost_usd: number;
  prompt_tokens: number;
  cached_tokens: number;
  input_tokens: number;
  output_tokens: number;
  started_at: string;
  ended_at: string;
  models: string[];
  source: string | null;
  key_kind: "session" | "trace";
}

interface Step {
  timestamp: string;
  model: string | null;
  prompt_tokens: number;
  cached_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  duration_ms: number | null;
  status_code: number | null;
  parent_span_id: string | null;
}

function RunsContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [runs, setRuns] = useState<Run[]>([]);
  const [detail, setDetail] = useState<{ run: Run; steps: Step[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [order, setOrder] = useState<"cost" | "recent">("cost");

  const fetchRuns = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch(`/api/v1/runs?days=${days}&order=${order}`, session.token);
      setRuns(data as Run[]);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, days, order, logout]);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  const openRun = useCallback(async (runId: string) => {
    if (!session) return;
    try {
      const data = await apiFetch(
        `/api/v1/runs/${encodeURIComponent(runId)}?days=${days}`,
        session.token,
      );
      setDetail(data as { run: Run; steps: Step[] });
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    }
  }, [session, days, logout]);

  if (loading && runs.length === 0) {
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
        <span className="error-inline" onClick={fetchRuns}>Couldn’t reach server — retry &#x2197;</span>
      </div>
    );
  }

  if (detail) {
    const { run, steps } = detail;
    return (
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">{run.run_id}</span>
          <span className="section-header-action" onClick={() => setDetail(null)} style={{ cursor: "pointer" }}>
            ← all runs
          </span>
        </div>
        <div className="stat-strip">
          <div className="stat-cell">
            <div className="stat-label">Cost</div>
            <div className="stat-value cyan">${run.cost_usd.toFixed(4)}</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Steps</div>
            <div className="stat-value">{run.step_count}</div>
          </div>
          {/* Prompt, not "in": coding agents cache nearly the whole prompt, so
              input_tokens alone reads as a handful of tokens against a real bill. */}
          <div className="stat-cell">
            <div className="stat-label">Prompt tokens</div>
            <div className="stat-value">{run.prompt_tokens.toLocaleString()}</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Cached</div>
            <div className="stat-value">{run.cached_tokens.toLocaleString()}</div>
          </div>
          <div className="stat-cell">
            <div className="stat-label">Output</div>
            <div className="stat-value">{run.output_tokens.toLocaleString()}</div>
          </div>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Model</th>
              <th>Prompt</th>
              <th>Cached</th>
              <th>Out</th>
              <th>Cost</th>
              <th>Latency</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((s, i) => (
              <tr key={i}>
                <td>{new Date(s.timestamp).toLocaleTimeString()}</td>
                <td>{s.model ?? "—"}</td>
                <td>{s.prompt_tokens.toLocaleString()}</td>
                <td>{s.cached_tokens.toLocaleString()}</td>
                <td>{s.output_tokens.toLocaleString()}</td>
                <td>${s.cost_usd.toFixed(4)}</td>
                <td>{s.duration_ms ? `${s.duration_ms}ms` : "—"}</td>
                <td style={{ color: s.status_code && s.status_code >= 400 ? "var(--amber)" : undefined }}>
                  {s.status_code ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="card" style={{ margin: 16 }}>
      <div className="section-header">
        <span className="section-header-title">Agent runs</span>
        <span
          className="section-header-action"
          onClick={() => setOrder((o) => (o === "cost" ? "recent" : "cost"))}
          style={{ cursor: "pointer" }}
        >
          by {order} · {days}d
        </span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Run</th>
            <th>Source</th>
            <th>Steps</th>
            <th>Prompt</th>
            <th>Cached</th>
            <th>Out</th>
            <th>Cost</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {runs.length === 0 ? (
            <tr>
              {/* Not a generic empty state: no historical row carries a run key,
                  and there is no backfill, so say what the user has to do. */}
              <td colSpan={8} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                No runs yet. Runs need burnlens 1.22.0 or newer on the proxy —
                earlier versions never sent the session id, and there is no backfill.
              </td>
            </tr>
          ) : (
            runs.map((r) => (
              <tr key={r.run_id} onClick={() => openRun(r.run_id)} style={{ cursor: "pointer" }}>
                <td title={r.run_id}>{r.run_id.slice(0, 12)}</td>
                <td>{r.source ?? (r.key_kind === "trace" ? "otel" : "—")}</td>
                <td>{r.step_count}</td>
                <td>{r.prompt_tokens.toLocaleString()}</td>
                <td>{r.cached_tokens.toLocaleString()}</td>
                <td>{r.output_tokens.toLocaleString()}</td>
                <td style={{ color: r.cost_usd > 1 ? "var(--amber)" : undefined }}>
                  ${r.cost_usd.toFixed(4)}
                </td>
                <td>{new Date(r.started_at).toLocaleString()}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function RunsPage() {
  return (
    <Shell>
      <RunsContent />
    </Shell>
  );
}

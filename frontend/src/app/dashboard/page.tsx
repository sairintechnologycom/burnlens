"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */


import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Shell from "@/components/Shell";
import BarChart from "@/components/charts/BarChart";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";
import type {
  UsageSummary,
  RequestRow,
  CostTimelinePoint,
  ProviderReconciliation,
  EconomicsOverview,
} from "@/lib/contracts";

function formatCost(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Same formatter as /waste so the Overview Waste KPI and detected_waste_usd match.
function formatWaste(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

// Why a number can legitimately disagree with the bill. Shown on hover so drift
// reads as a diagnosis, not a failure.
const DRIFT_CAUSES =
  "Common causes: calls that bypassed the proxy, a provider pricing change we " +
  "haven't picked up yet, an unpriced model, and rounding.";

function ReconciliationBadge({ r }: { r: ProviderReconciliation }) {
  const drift = r.drift_pct;
  const color =
    r.status === "reconciled" ? "var(--green)" : r.status === "drifted" ? "var(--amber)" : "var(--muted)";

  let label: string;
  let title: string;
  if (r.status === "unreconciled") {
    label = `${r.provider} · unreconciled`;
    title = "Billing key stored, but no daily comparison has run yet.";
  } else {
    const amount = drift === null ? "n/a" : `${drift > 0 ? "+" : ""}${drift.toFixed(1)}%`;
    label =
      r.status === "reconciled"
        ? `${r.provider} · reconciled ✓ ${amount} drift`
        : `${r.provider} · ${amount} drift`;
    title =
      `${r.day}: provider billed $${(r.provider_cost_usd ?? 0).toFixed(2)}, ` +
      `BurnLens computed $${(r.burnlens_cost_usd ?? 0).toFixed(2)}. ${DRIFT_CAUSES}`;
  }

  return (
    <span className="tag" title={title} style={{ background: "var(--bg3)", color }}>
      {label}
    </span>
  );
}

function latencyClass(ms: number): string {
  if (ms < 1000) return "latency-fast";
  if (ms <= 3000) return "latency-mid";
  return "latency-slow";
}

function DashboardContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [timeseries, setTimeseries] = useState<{ label: string; cost: number }[]>([]);
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [reconciliation, setReconciliation] = useState<ProviderReconciliation[]>([]);
  const [economics, setEconomics] = useState<EconomicsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [requestLimit, setRequestLimit] = useState(20);

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [sum, ts, reqs, recon, econ] = await Promise.all([
        apiFetch(`/api/v1/usage/summary?days=${days}`, session.token),
        apiFetch(`/api/v1/usage/timeseries?days=${days}&granularity=day`, session.token).catch(() => []),
        apiFetch(`/api/v1/requests?days=${days}&limit=${requestLimit}`, session.token).catch(() => []),
        apiFetch(`/api/v1/reconciliation`, session.token).catch(() => []),
        apiFetch(`/api/v1/economics?days=${days}`, session.token).catch(() => null),
      ]);
      setSummary(sum);
      setEconomics(econ as EconomicsOverview | null);

      // Aggregate timeseries by date
      const byDate: Record<string, number> = {};
      (ts as CostTimelinePoint[]).forEach((p) => {
        byDate[p.date] = (byDate[p.date] || 0) + (p.total_cost_usd || 0);
      });
      const sorted = Object.entries(byDate)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, cost]) => ({
          label: new Date(date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
          cost,
        }));
      setTimeseries(sorted);
      setRequests(reqs as RequestRow[]);
      setReconciliation(recon as ProviderReconciliation[]);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, days, requestLimit, logout]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => { document.title = "Overview | BurnLens"; }, []);

  const totalCost = summary?.total_cost_usd ?? 0;
  const totalCalls = summary?.total_requests ?? 0;
  const wasteAmount = economics?.detected_waste_usd ?? null;
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
      <div className="stat-strip cols-5">
        <div className="stat-cell">
          <div className="stat-label">Total spend</div>
          <div className="stat-value">
            {hasData ? `$${formatCost(summary?.total_cost_usd ?? 0)}` : <span style={{ color: "var(--dim)" }}>—</span>}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Requests</div>
          <div className="stat-value">
            {hasData ? (summary?.total_requests ?? 0).toLocaleString() : <span style={{ color: "var(--dim)" }}>—</span>}
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
          <div className={`stat-value${wasteAmount != null && wasteAmount > 0 ? " amber" : ""}`}>
            {wasteAmount == null ? (
              <span style={{ color: "var(--dim)" }}>—</span>
            ) : (
              `$${formatWaste(wasteAmount)}`
            )}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Cache saved</div>
          <div className="stat-value" style={(summary?.cache_saved_usd ?? 0) > 0 ? { color: "var(--green)" } : undefined}>
            {hasData ? `$${formatCost(summary?.cache_saved_usd ?? 0)}` : <span style={{ color: "var(--dim)" }}>—</span>}
          </div>
        </div>
      </div>

      {/* Trust badge: does our number match the provider's bill? */}
      {reconciliation.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: "12px 16px 0" }}>
          {reconciliation.map((r) => (
            <ReconciliationBadge key={r.provider} r={r} />
          ))}
        </div>
      )}

      {!hasData && (
        <div className="card" style={{ margin: 16, padding: 32 }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, textAlign: "center" }}>
            <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text)" }}>
              Connect this workspace
            </div>
            <div style={{ fontSize: 13, color: "var(--muted)", maxWidth: 520, lineHeight: 1.5 }}>
              Install the local proxy, log in with the ingest key from signup, and point your SDK at it.
              Spend appears within ~60s of the first synced request.
            </div>
            <div className="empty-state-code" style={{ marginTop: 8, textAlign: "left" }}>
              <div><span className="empty-state-code-prompt">$</span> pip install burnlens</div>
              <div><span className="empty-state-code-prompt">$</span> burnlens start</div>
              <div><span className="empty-state-code-prompt">$</span> burnlens login --api-key bl_live_...</div>
              <div><span className="empty-state-code-prompt">$</span> export OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai</div>
            </div>
            <div style={{ fontSize: 13, color: "var(--muted)", maxWidth: 520, lineHeight: 1.5 }}>
              Using Claude Code, Cursor, Codex, or Gemini CLI? Run{" "}
              <code>burnlens scan</code> instead — reads local logs, no proxy needed.{" "}
              <Link href="/scan">Scan guide</Link>
            </div>
            <div style={{ fontSize: 13, color: "var(--muted)", maxWidth: 520, lineHeight: 1.5 }}>
              Google needs one extra line —{" "}
              <code>import burnlens.patch; burnlens.patch.patch_google()</code>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <a
                href="https://github.com/sairintechnologycom/burnlens#readme"
                className="upgrade-btn"
                style={{ textDecoration: "none" }}
              >
                Install docs
              </a>
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
                  <td style={{ color: (r.cost_usd ?? 0) > 0.01 ? "var(--amber)" : undefined }}>
                    ${(r.cost_usd ?? 0).toFixed(4)}
                  </td>
                  <td className={r.duration_ms ? latencyClass(r.duration_ms) : ""}>
                    {r.duration_ms ? `${r.duration_ms}` : "—"}
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

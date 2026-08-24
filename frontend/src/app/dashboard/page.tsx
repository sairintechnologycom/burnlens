"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */


import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Shell from "@/components/Shell";
import BarChart from "@/components/charts/BarChart";
import { apiFetch, apiDownload, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";
import type {
  UsageSummary,
  RequestRow,
  CostTimelinePoint,
  ProviderReconciliation,
  EconomicsOverview,
  CostConfidence,
  OutcomeCoverage,
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

/** The month finance is closing when they open this — never the in-progress one. */
function previousMonth(): string {
  const now = new Date();
  const prev = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1));
  return prev.toISOString().slice(0, 7);
}

function MonthEndExport({ token }: { token: string }) {
  const [month, setMonth] = useState(previousMonth);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const download = async () => {
    setBusy(true);
    setError("");
    try {
      await apiDownload(
        `/api/v1/usage/monthly-export?month=${month}`,
        token,
        `burnlens-costs-${month}.csv`
      );
    } catch (err: any) {
      // A failed export is blocking, not incidental: the reason has to stay on
      // screen, because "nothing downloaded" is otherwise indistinguishable
      // from "that month had no spend".
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title">Month-end export</span>
        <span className="section-header-action">CSV</span>
      </div>
      <div style={{ padding: 16, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <input
          type="month"
          value={month}
          max={previousMonth()}
          onChange={(e) => setMonth(e.target.value)}
          aria-label="Month to export"
        />
        <button onClick={download} disabled={busy || !month}>
          {busy ? "Preparing…" : "Download CSV"}
        </button>
        <span style={{ fontSize: 13, color: "var(--muted)" }}>
          One row per provider and model, with a total to reconcile against the invoice.
        </span>
      </div>
      {error && (
        <div style={{ padding: "0 16px 16px", fontSize: 13, color: "var(--red, #e5484d)" }}>
          {error}
        </div>
      )}
    </div>
  );
}

// Confidence counts requests, not dollars. Unpriced rows cost $0, so a
// dollar-weighted bar would show a full green line on a workspace whose most
// expensive model has no price — the exact failure this panel exists to expose.
// `reconciled_spend_pct` carries the dollar side, shown beside it.
const CONFIDENCE_CLASSES = [
  { key: "reconciled", label: "Provider verified", color: "var(--green)",
    help: "Compared against the provider's own bill and inside the drift threshold." },
  { key: "calculated", label: "Pricing calculated", color: "var(--blue, #4c8dff)",
    help: "Priced from the pricing table. Never checked against a bill." },
  { key: "estimated", label: "Estimated", color: "var(--amber)",
    help: "Rebuilt from a coding agent's local logs. Token counts are the agent's own." },
  { key: "unpriced", label: "Unpriced", color: "var(--red, #e5484d)",
    help: "Tokens were used and we have no price for the model, so these count as $0." },
] as const;

function CostConfidencePanel({ c }: { c: CostConfidence }) {
  if (c.total_requests === 0) return null;

  return (
    <div className="card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title">Cost confidence</span>
        <span className="section-header-action" title="Share of requests BurnLens can classify economically — every class except unpriced. A plain ratio, not a weighted score.">
          {c.confidence_pct.toFixed(0)}%
        </span>
      </div>
      <div style={{ padding: 16 }}>
        <div
          role="img"
          aria-label={`Cost confidence ${c.confidence_pct.toFixed(0)} percent`}
          style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: "var(--bg3)" }}
        >
          {CONFIDENCE_CLASSES.map(({ key, label, color }) => {
            const pct = (c[key].requests / c.total_requests) * 100;
            if (pct <= 0) return null;
            return <div key={key} title={`${label}: ${pct.toFixed(1)}% of requests`}
                        style={{ width: `${pct}%`, background: color }} />;
          })}
        </div>

        {/* The two questions are different: "are we pricing the workload
            comprehensively" (requests) and "how much known exposure is verified"
            (dollars). One unpriced call can outweigh 99,000 priced ones. */}
        <div style={{ display: "flex", gap: 24, marginTop: 12, fontSize: 12, color: "var(--muted)" }}>
          <span>{c.confidence_pct.toFixed(0)}% of requests classified</span>
          <span>{c.reconciled_spend_pct.toFixed(0)}% of known spend provider-verified</span>
        </div>

        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 14, fontSize: 13 }}>
          {CONFIDENCE_CLASSES.map(({ key, label, color, help }) => {
            const b = c[key];
            if (b.requests === 0) return null;
            return (
              <div key={key} title={help}>
                <div style={{ color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
                  {label}
                </div>
                <div style={{ color: "var(--text)", marginTop: 2 }}>
                  {/* Unpriced dollars are unknowable by definition — showing $0.00 would
                      read as "this cost nothing", which is the opposite of the point. */}
                  {key === "unpriced" ? "$ unknown" : `$${formatCost(b.cost_usd)}`}
                  <span style={{ color: "var(--dim)" }}>
                    {" · "}{b.requests.toLocaleString()} req
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {c.gaps.length > 0 && (
          <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>Coverage gaps</div>
            {c.gaps.map((g, i) => (
              <div key={i} style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.7 }}>
                <span style={{ color: "var(--amber)" }}>⚠</span>{" "}
                <span style={{ color: "var(--text)" }}>
                  {g.provider}{g.model ? ` · ${g.model}` : ""}
                </span>{" "}
                {g.detail}
                {g.requests > 0 && (
                  <span style={{ color: "var(--dim)" }}> ({g.requests.toLocaleString()} req)</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// Dollar-weighted, unlike cost confidence — the question here is what share of
// the money bought something we can name. The three tiers must sum to the total
// or the bar is lying; the backend enforces that, this just renders it.
const COVERAGE_CLASSES = [
  { key: "cost_attributed_usd", label: "Linked to an outcome", color: "var(--green)",
    help: "An outcome was recorded for this spend inside the allocation window." },
  { key: "cost_unattributed_usd", label: "Tagged, no outcome", color: "var(--amber)",
    help: "The request carried a workflow_id but no outcome followed. Post the outcome and this moves." },
  { key: "cost_untagged_usd", label: "No workflow tag", color: "var(--red, #e5484d)",
    help: "No workflow_id on the request, so it can never be attributed. Cost-per-outcome is blind to this spend entirely." },
] as const;

function OutcomeCoveragePanel({ c }: { c: OutcomeCoverage }) {
  if (c.cost_total_usd <= 0) return null;

  return (
    <div className="card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title">Outcome coverage</span>
        <span
          className="section-header-action"
          title="Share of spend, by dollar, that reaches a recorded business outcome."
        >
          {c.coverage_pct.toFixed(0)}%
        </span>
      </div>
      <div style={{ padding: 16 }}>
        <div
          role="img"
          aria-label={`Outcome coverage ${c.coverage_pct.toFixed(0)} percent of spend`}
          style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: "var(--bg3)" }}
        >
          {COVERAGE_CLASSES.map(({ key, label, color }) => {
            const pct = (c[key] / c.cost_total_usd) * 100;
            if (pct <= 0) return null;
            return <div key={key} title={`${label}: $${formatCost(c[key])}`}
                        style={{ width: `${pct}%`, background: color }} />;
          })}
        </div>

        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 14, fontSize: 13 }}>
          {COVERAGE_CLASSES.map(({ key, label, color, help }) => {
            if (c[key] <= 0) return null;
            return (
              <div key={key} title={help}>
                <div style={{ color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
                  {label}
                </div>
                <div style={{ color: "var(--text)", marginTop: 2 }}>${formatCost(c[key])}</div>
              </div>
            );
          })}
        </div>

        {c.cost_untagged_usd > 0 && (
          <div style={{ marginTop: 14, fontSize: 13, color: "var(--muted)", lineHeight: 1.6 }}>
            <span style={{ color: "var(--amber)" }}>⚠</span>{" "}
            <span style={{ color: "var(--text)" }}>${formatCost(c.cost_untagged_usd)}</span> of spend
            carries no <code>workflow_id</code> tag, so cost-per-outcome is computed
            without it. <Link href="/docs">Tagging guide</Link>
          </div>
        )}

        {c.by_workflow.length > 0 && (
          <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            {c.by_workflow.map((w, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, lineHeight: 1.9 }}>
                <span style={{ color: w.workflow_id ? "var(--text)" : "var(--dim)" }}>
                  {w.workflow_id ?? "untagged"}
                </span>
                <span style={{ color: "var(--muted)" }}>
                  ${formatCost(w.cost_total_usd)}
                  <span style={{ color: w.coverage_pct >= 90 ? "var(--green)" : "var(--amber)", marginLeft: 12 }}>
                    {w.coverage_pct.toFixed(0)}%
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DashboardContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [timeseries, setTimeseries] = useState<{ label: string; cost: number }[]>([]);
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [reconciliation, setReconciliation] = useState<ProviderReconciliation[]>([]);
  const [economics, setEconomics] = useState<EconomicsOverview | null>(null);
  const [confidence, setConfidence] = useState<CostConfidence | null>(null);
  const [coverage, setCoverage] = useState<OutcomeCoverage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [requestLimit, setRequestLimit] = useState(20);

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [sum, ts, reqs, recon, econ, conf, cov] = await Promise.all([
        apiFetch(`/api/v1/usage/summary?days=${days}`, session.token),
        apiFetch(`/api/v1/usage/timeseries?days=${days}&granularity=day`, session.token).catch(() => []),
        apiFetch(`/api/v1/requests?days=${days}&limit=${requestLimit}`, session.token).catch(() => []),
        apiFetch(`/api/v1/reconciliation`, session.token).catch(() => []),
        apiFetch(`/api/v1/economics?days=${days}`, session.token).catch(() => null),
        apiFetch(`/api/v1/cost-confidence?days=${days}`, session.token).catch(() => null),
        apiFetch(`/api/v1/outcomes/coverage?days=${days}`, session.token).catch(() => null),
      ]);
      setSummary(sum);
      setEconomics(econ as EconomicsOverview | null);
      setConfidence(conf as CostConfidence | null);
      setCoverage(cov as OutcomeCoverage | null);

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

      {confidence && <CostConfidencePanel c={confidence} />}
      {coverage && <OutcomeCoveragePanel c={coverage} />}

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
                href="/docs"
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

      {/* Month-end finance export */}
      {hasData && session && <MonthEndExport token={session.token} />}

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

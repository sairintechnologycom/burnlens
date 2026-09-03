"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";
import { apiFetch, AuthError, errorMessageFrom } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";
import type { ProviderConcentration, WorkflowEconomics } from "@/lib/contracts";
import { OutcomesTable, formatPerAccepted, formatUsd } from "./OutcomesTable";
import { ConcentrationTable } from "./ConcentrationTable";
import { EconomicsNav } from "@/components/EconomicsNav";

function KpiStrip({ rows }: { rows: WorkflowEconomics[] }) {
  const accepted = rows.reduce((s, r) => s + r.accepted_count, 0);
  const total = rows.reduce((s, r) => s + r.cost_total_usd, 0);
  const rework = rows.reduce((s, r) => s + r.cost_rework_usd, 0);
  const unattributed = rows.reduce((s, r) => s + r.cost_unattributed_usd, 0);
  const perAccepted = accepted > 0 ? total / accepted : null;

  return (
    <div className="stat-strip cols-5">
      <div className="stat-cell">
        <div className="stat-label">Accepted</div>
        <div className="stat-value">{accepted.toLocaleString()}</div>
      </div>
      <div className="stat-cell">
        <div className="stat-label">Total cost</div>
        <div className="stat-value">${formatUsd(total)}</div>
      </div>
      <div className="stat-cell">
        <div className="stat-label">Rework</div>
        <div className={`stat-value${rework > 0 ? " amber" : ""}`}>${formatUsd(rework)}</div>
      </div>
      <div className="stat-cell">
        <div className="stat-label">Unattributed</div>
        <div className="stat-value">${formatUsd(unattributed)}</div>
        <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
          spend with no outcome in the 24h window
        </div>
      </div>
      <div className="stat-cell">
        <div className="stat-label">Cost / accepted</div>
        <div className="stat-value">{formatPerAccepted(perAccepted)}</div>
      </div>
    </div>
  );
}

function OutcomesContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [rows, setRows] = useState<WorkflowEconomics[]>([]);
  const [concentration, setConcentration] = useState<ProviderConcentration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [data, conc] = await Promise.all([
        apiFetch(`/api/v1/outcomes/summary?days=${days}`, session.token),
        apiFetch(`/api/v1/outcomes/concentration?days=${days}`, session.token),
      ]);
      setRows(Array.isArray(data) ? (data as WorkflowEconomics[]) : []);
      setConcentration(Array.isArray(conc) ? (conc as ProviderConcentration[]) : []);
    } catch (err: unknown) {
      if (err instanceof AuthError) logout();
      else if (err instanceof Error) setError(err.message);
      else setError(errorMessageFrom(err, 500));
    } finally {
      setLoading(false);
    }
  }, [session, days, logout]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    document.title = "Outcomes | BurnLens";
  }, []);

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div className="skeleton" style={{ height: 80, marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 240 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={fetchData}>
          {error} — retry &#x2197;
        </span>
      </div>
    );
  }

  return (
    <div>
      <EconomicsNav current="/outcomes" />
      {rows.length > 0 && <KpiStrip rows={rows} />}
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Cost per accepted outcome</span>
          <span className="section-header-action">{days}d</span>
        </div>
        {rows.length === 0 ? (
          <EmptyState
            title="No workflow economics yet"
            description="This page divides spend tagged with a workflow_id by accepted results. Failed and rejected attempts are charged to the successes. Scan-derived spend shows as repo:<name> after you derive merged PRs."
            code={"burnlens outcome derive\nburnlens outcome show"}
          />
        ) : (
          <OutcomesTable rows={rows} />
        )}
        <p
          style={{
            margin: "12px 16px 16px",
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--muted)",
          }}
        >
          A request is charged to the first outcome of its workflow that follows
          it within 24 hours. Spend with no such outcome stays in Unattributed.
          Per accepted is total workflow spend ÷ accepted count —{" "}
          <code>—</code> when a workflow has spend and nothing accepted yet.
          Outcomes recorded locally sync to this workspace when cloud sync is on.
        </p>
      </div>

      {concentration.length > 0 && (
        <div className="card" style={{ margin: 16 }}>
          <div className="section-header">
            <span className="section-header-title">Provider dependency</span>
            <span className="section-header-action">{days}d</span>
          </div>
          <ConcentrationTable rows={concentration} />
          <p
            style={{
              margin: "12px 16px 16px",
              fontSize: 12,
              lineHeight: 1.5,
              color: "var(--muted)",
            }}
          >
            Spend share says who is expensive. <strong>Sole provider on</strong>{" "}
            says who you cannot leave: workflows where this provider is the only
            one spending, so nothing else has been shown to do that work. A
            provider with a small spend share and a high sole-provider count is
            the harder dependency of the two. Outcome shares can add up to more
            than 100% — an accepted outcome that several providers contributed
            to counts for each of them.
          </p>
        </div>
      )}
    </div>
  );
}

export default function OutcomesPage() {
  return (
    <Shell>
      <OutcomesContent />
    </Shell>
  );
}

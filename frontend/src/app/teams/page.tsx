"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import HorizontalBar from "@/components/charts/HorizontalBar";
import LockedPanel from "@/components/LockedPanel";
import {
  apiFetch,
  AuthError,
  PaymentRequiredError,
  type PaymentRequiredBody,
} from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";

interface TeamData {
  team: string;
  api_calls: number;
  total_cost: number;
  pct_of_total: number;
  budget?: number;
  budget_status?: "ok" | "warning" | "critical";
}

// D-06: Per-page skeleton with the recognizable shape of the real page
// (HorizontalBar-shaped placeholder + table-shaped placeholder).
// D-05: Used both as the loading state (no blur) AND as LockedPanel children
// (frosted via .locked-panel-content) so there is no flash-of-real-data for
// Free/Cloud users nor flash-of-locked for Teams users.
function TeamsSkeleton() {
  const barWidths = [70, 62, 54, 46, 38, 30];
  return (
    <div className="teams-skeleton">
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Cost by team</span>
        </div>
        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
          {barWidths.map((w, i) => (
            <div
              key={i}
              className="skeleton"
              style={{ height: 18, width: `${w}%` }}
            />
          ))}
        </div>
      </div>
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Team breakdown</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Team</th>
              <th>Requests</th>
              <th>Cost</th>
              <th>% of total</th>
              <th>Budget</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {[0, 1, 2, 3, 4].map((i) => (
              <tr key={i}>
                <td>
                  <div className="skeleton" style={{ width: 120, height: 14 }} />
                </td>
                <td>
                  <div className="skeleton" style={{ width: 60, height: 14 }} />
                </td>
                <td>
                  <div className="skeleton" style={{ width: 60, height: 14 }} />
                </td>
                <td>
                  <div className="skeleton" style={{ width: 40, height: 14 }} />
                </td>
                <td>
                  <div className="skeleton" style={{ width: 40, height: 14 }} />
                </td>
                <td>
                  <div className="skeleton" style={{ width: 50, height: 14 }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TeamsContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [teams, setTeams] = useState<TeamData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // D-03: store the full 402 body so both required_feature AND required_plan
  // flow into LockedPanel — no hardcoded values in this file.
  const [locked, setLocked] = useState<PaymentRequiredBody | null>(null);

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    setLocked(null);
    apiFetch(`/api/v1/usage/by-team?days=${days}`, session.token)
      .then((data) => setTeams(data as TeamData[]))
      .catch((err) => {
        if (err instanceof AuthError) logout();
        else if (err instanceof PaymentRequiredError) setLocked(err.data);
        else setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [session, days, logout]);

  // D-05: skeleton serves as the loading state — same DOM as LockedPanel
  // children — so Teams-plan users do not flash through a "locked" frame.
  if (loading) {
    return <TeamsSkeleton />;
  }

  if (locked) {
    return (
      <LockedPanel
        featureKey={locked.required_feature ?? "teams_view"}
        requiredPlan={locked.required_plan ?? "teams"}
      >
        <TeamsSkeleton />
      </LockedPanel>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={() => window.location.reload()}>
          Couldn’t reach server — retry &#x2197;
        </span>
      </div>
    );
  }

  const statusClass = (s?: string) => {
    if (s === "critical") return "budget-critical";
    if (s === "warning") return "budget-warning";
    return "budget-ok";
  };

  return (
    <div>
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Cost by team</span>
          <span className="section-header-action">{days}d</span>
        </div>
        {teams.length > 0 ? (
          <HorizontalBar
            labels={teams.map((t) => t.team)}
            data={teams.map((t) => t.total_cost)}
            height={Math.max(200, teams.length * 36)}
          />
        ) : (
          <div style={{ padding: 32, textAlign: "center", fontSize: 11, color: "var(--muted)" }}>
            No team data
          </div>
        )}
      </div>

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Team breakdown</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Team</th>
              <th>Requests</th>
              <th>Cost</th>
              <th>% of total</th>
              <th>Budget</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {teams.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                  No team data
                </td>
              </tr>
            ) : (
              teams.map((t) => (
                <tr key={t.team}>
                  <td style={{ fontWeight: 500 }}>{t.team}</td>
                  <td>{t.api_calls.toLocaleString()}</td>
                  <td>${t.total_cost.toFixed(2)}</td>
                  <td>{(t.pct_of_total * 100).toFixed(1)}%</td>
                  <td>{t.budget ? `$${t.budget.toFixed(0)}` : "—"}</td>
                  <td>
                    <span className={statusClass(t.budget_status)} style={{ fontWeight: 500, textTransform: "uppercase", fontSize: 10 }}>
                      {t.budget_status || "—"}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function TeamsPage() {
  return (
    <Shell>
      <TeamsContent />
    </Shell>
  );
}

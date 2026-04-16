"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";

interface BudgetStatus {
  budget_usd: number | null;
  spent_usd: number;
  remaining_usd: number | null;
  forecast_usd: number;
  pct_used: number | null;
  is_over_budget: boolean;
  is_on_pace_to_exceed: boolean;
  period_days: number;
  elapsed_days: number;
}

interface TeamBudget {
  team: string;
  spent: number;
  limit: number;
  pct_used: number;
  status: string;
}

function formatCost(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function statusColor(status: string): string {
  if (status === "CRITICAL" || status === "EXCEEDED") return "var(--red)";
  if (status === "WARNING") return "var(--amber)";
  return "var(--green)";
}

function BudgetsContent() {
  const { session, logout } = useAuth();
  const [budget, setBudget] = useState<BudgetStatus | null>(null);
  const [teams, setTeams] = useState<TeamBudget[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [b, t] = await Promise.all([
        apiFetch("/api/budget", session.apiKey).catch(() => null),
        apiFetch("/api/team-budgets", session.apiKey).catch(() => []),
      ]);
      setBudget(b);
      setTeams(t as TeamBudget[]);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div className="skeleton" style={{ height: 100, marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 200 }} />
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
      {budget && (
        <>
          <div className="stat-strip">
            <div className="stat-cell">
              <div className="stat-label">Spent</div>
              <div className="stat-value cyan">${formatCost(budget.spent_usd)}</div>
            </div>
            <div className="stat-cell">
              <div className="stat-label">Budget</div>
              <div className="stat-value">{budget.budget_usd != null ? `$${formatCost(budget.budget_usd)}` : "Not set"}</div>
            </div>
            <div className="stat-cell">
              <div className="stat-label">Forecast</div>
              <div className="stat-value" style={{ color: budget.is_on_pace_to_exceed ? "var(--red)" : undefined }}>
                ${formatCost(budget.forecast_usd)}
              </div>
            </div>
            <div className="stat-cell">
              <div className="stat-label">Used</div>
              <div className="stat-value" style={{ color: budget.is_over_budget ? "var(--red)" : undefined }}>
                {budget.pct_used != null ? `${budget.pct_used}%` : "—"}
              </div>
            </div>
          </div>

          {budget.budget_usd != null && (
            <div className="card" style={{ margin: 16 }}>
              <div className="section-header">
                <span className="section-header-title">Budget progress</span>
                <span className="section-header-action">Day {budget.elapsed_days} / {budget.period_days}</span>
              </div>
              <div style={{ padding: 16 }}>
                <div style={{ background: "var(--surface)", borderRadius: 4, height: 24, overflow: "hidden" }}>
                  <div
                    style={{
                      width: `${Math.min(budget.pct_used ?? 0, 100)}%`,
                      height: "100%",
                      background: budget.is_over_budget ? "var(--red)" : budget.is_on_pace_to_exceed ? "var(--amber)" : "var(--cyan)",
                      transition: "width 0.3s",
                    }}
                  />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 11, color: "var(--muted)" }}>
                  <span>${formatCost(budget.spent_usd)} spent</span>
                  <span>{budget.remaining_usd != null ? `$${formatCost(budget.remaining_usd)} remaining` : ""}</span>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Team budgets</span>
        </div>
        {teams.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", fontSize: 11, color: "var(--muted)" }}>
            No team budgets configured. Add team budgets in burnlens.yaml.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Team</th>
                <th>Spent</th>
                <th>Limit</th>
                <th>Used</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {teams.map((t) => (
                <tr key={t.team}>
                  <td><span className="tag tag-team">{t.team}</span></td>
                  <td>${formatCost(t.spent)}</td>
                  <td>${formatCost(t.limit)}</td>
                  <td>{t.pct_used}%</td>
                  <td style={{ color: statusColor(t.status), fontWeight: 600 }}>{t.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default function BudgetsPage() {
  return (
    <Shell>
      <BudgetsContent />
    </Shell>
  );
}

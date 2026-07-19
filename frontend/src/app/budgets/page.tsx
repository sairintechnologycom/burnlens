"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */


import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import type { TeamBudgetRow as TeamBudget } from "@/lib/contracts";

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
  const [budgetInput, setBudgetInput] = useState("");
  const [savingBudget, setSavingBudget] = useState(false);
  const [teamInput, setTeamInput] = useState("");
  const [teamAmountInput, setTeamAmountInput] = useState("");
  const [savingTeam, setSavingTeam] = useState(false);

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [b, t] = await Promise.all([
        apiFetch("/api/v1/budget", session.token).catch(() => null),
        apiFetch("/api/v1/team-budgets", session.token).catch(() => []),
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

  const canEditBudget = session?.role === "owner" || session?.role === "admin";

  const saveBudget = useCallback(async (clear: boolean) => {
    if (!session) return;
    setError("");
    const value = clear ? null : parseFloat(budgetInput);
    if (!clear && (!Number.isFinite(value as number) || (value as number) <= 0)) {
      setError("Enter a budget amount greater than 0.");
      return;
    }
    setSavingBudget(true);
    try {
      await apiFetch("/settings/budget", session.token, {
        method: "PUT",
        body: JSON.stringify({ monthly_budget_usd: value }),
      });
      setBudgetInput("");
      await fetchData();
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message || "Couldn't save budget.");
    } finally {
      setSavingBudget(false);
    }
  }, [session, budgetInput, fetchData, logout]);

  const saveTeamBudget = useCallback(async (team: string, amount: number | null) => {
    if (!session) return;
    setError("");
    if (amount !== null && (!Number.isFinite(amount) || amount <= 0)) {
      setError("Enter a team budget amount greater than 0.");
      return;
    }
    setSavingTeam(true);
    try {
      await apiFetch("/settings/team-budget", session.token, {
        method: "PUT",
        body: JSON.stringify({ team, monthly_budget_usd: amount }),
      });
      setTeamInput("");
      setTeamAmountInput("");
      await fetchData();
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message || "Couldn't save team budget.");
    } finally {
      setSavingTeam(false);
    }
  }, [session, fetchData, logout]);

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
        <span className="error-inline" onClick={fetchData}>Couldn’t reach server — retry &#x2197;</span>
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

          {canEditBudget && (
            <div className="card" style={{ margin: 16 }}>
              <div className="section-header">
                <span className="section-header-title">
                  {budget.budget_usd != null ? "Monthly budget" : "Set a monthly budget"}
                </span>
              </div>
              <div style={{ padding: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ color: "var(--muted)" }}>$</span>
                <input
                  type="number"
                  min={0}
                  step={1}
                  inputMode="decimal"
                  aria-label="Monthly budget in USD"
                  placeholder={budget.budget_usd != null ? String(budget.budget_usd) : "500"}
                  value={budgetInput}
                  onChange={(e) => setBudgetInput(e.target.value)}
                  style={{ width: 120 }}
                />
                <button className="btn btn-cyan" disabled={savingBudget} onClick={() => saveBudget(false)}>
                  {savingBudget ? "Saving…" : "Save"}
                </button>
                {budget.budget_usd != null && (
                  <button className="btn" disabled={savingBudget} onClick={() => saveBudget(true)}>
                    Clear
                  </button>
                )}
                <span style={{ color: "var(--muted)", fontSize: 11 }}>
                  Enforced at 100% — ingest is blocked past the cap.
                </span>
              </div>
            </div>
          )}

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
          <EmptyState
            title="No team budgets configured"
            description="Set a monthly budget per team below. Spend is attributed via the team tag on each request; teams show WARNING at 80% and EXCEEDED at 100%."
          />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Team</th>
                <th>Spent</th>
                <th>Limit</th>
                <th>Used</th>
                <th>Status</th>
                {canEditBudget && <th></th>}
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
                  {canEditBudget && (
                    <td>
                      <button
                        className="btn"
                        style={{ padding: "2px 8px", fontSize: 10 }}
                        disabled={savingTeam}
                        onClick={() => saveTeamBudget(t.team, null)}
                      >
                        Clear
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {canEditBudget && (
          <div style={{ padding: 16, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", borderTop: "1px solid var(--border)" }}>
            <input
              aria-label="Team name"
              placeholder="team name"
              value={teamInput}
              onChange={(e) => setTeamInput(e.target.value)}
              style={{ width: 140 }}
            />
            <span style={{ color: "var(--muted)" }}>$</span>
            <input
              type="number"
              min={0}
              step={1}
              inputMode="decimal"
              aria-label="Team monthly budget in USD"
              placeholder="500"
              value={teamAmountInput}
              onChange={(e) => setTeamAmountInput(e.target.value)}
              style={{ width: 120 }}
            />
            <button
              className="btn btn-cyan"
              disabled={savingTeam || !teamInput.trim()}
              onClick={() => saveTeamBudget(teamInput.trim(), parseFloat(teamAmountInput))}
            >
              {savingTeam ? "Saving…" : "Set team budget"}
            </button>
            <span style={{ color: "var(--muted)", fontSize: 11 }}>
              Tracked against the team tag — warns at 80%, flags at 100%.
            </span>
          </div>
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

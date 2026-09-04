"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */


import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import EmptyState from "@/components/EmptyState";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import type { RecommendationRow as Recommendation, SavingsRollup } from "@/lib/contracts";
import { VerifiedSavingsPanel } from "./VerifiedSavingsView";
import { EconomicsNav } from "@/components/EconomicsNav";

function formatCost(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function SavingsContent() {
  const { session, logout } = useAuth();
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [rollup, setRollup] = useState<SavingsRollup | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const [data, roll] = await Promise.all([
        apiFetch("/api/v1/recommendations", session.token),
        apiFetch("/api/v1/findings/savings", session.token).catch(() => null),
      ]);
      setRecs(data as Recommendation[]);
      setRollup(roll as SavingsRollup | null);
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const totalSaving = recs.reduce((s, r) => s + r.projected_saving, 0);

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        {[1, 2, 3].map((i) => (
          <div key={i} className="skeleton" style={{ height: 80, marginBottom: 8 }} />
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
      <EconomicsNav current="/savings" />
      <div className="stat-strip">
        <div className="stat-cell">
          <div className="stat-label">Recommendations</div>
          <div className="stat-value">{recs.length}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Potential savings</div>
          <div className="stat-value" style={{ color: "var(--green)" }}>${formatCost(totalSaving)}</div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Verified Savings</div>
          <div className="stat-value" style={rollup && rollup.verified_monthly_usd > 0 ? { color: "var(--green)" } : undefined}>
            {(() => {
              if (!rollup) return <span style={{ color: "var(--dim)" }}>—</span>;
              const judged = (rollup.counts.verified ?? 0) + (rollup.counts.missed ?? 0);
              if (judged === 0 && rollup.verified_monthly_usd === 0) {
                return <span style={{ color: "var(--dim)" }}>No verified changes yet</span>;
              }
              return `$${formatCost(rollup.verified_monthly_usd)}`;
            })()}
          </div>
        </div>
      </div>

      {rollup && <VerifiedSavingsPanel r={rollup} />}

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Model switch recommendations</span>
        </div>
        {recs.length === 0 ? (
          <EmptyState
            title="No savings opportunities yet"
            description="We need ~500 requests per feature to confidently recommend a cheaper model. Install the local proxy or connect a provider to start collecting data."
            code={"pip install burnlens\nburnlens start"}
            action={{ label: "View install docs", href: "/docs" }}
          />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Current model</th>
                <th>Suggested</th>
                <th>Requests</th>
                <th>Current cost</th>
                <th>Projected</th>
                <th>Saving</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {recs.map((r, i) => (
                <tr key={i}>
                  <td>
                    {r.feature_tag ? (
                      <span className="tag tag-feature">{r.feature_tag}</span>
                    ) : (
                      <span style={{ color: "var(--dim)" }}>all</span>
                    )}
                  </td>
                  <td>{r.current_model}</td>
                  <td style={{ color: "var(--green)" }}>{r.suggested_model}</td>
                  <td>{r.request_count.toLocaleString()}</td>
                  <td>${formatCost(r.current_cost)}</td>
                  <td>${formatCost(r.projected_cost)}</td>
                  <td style={{ color: "var(--green)" }}>
                    -${formatCost(r.projected_saving)} ({r.saving_pct}%)
                  </td>
                  <td>{r.confidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {recs.length > 0 && (
        <div className="card" style={{ margin: 16 }}>
          <div className="section-header">
            <span className="section-header-title">Rationale</span>
          </div>
          {recs.map((r, i) => (
            <div key={i} style={{ padding: "8px 16px", fontSize: 11, borderBottom: "1px solid var(--border)" }}>
              <strong>{r.current_model} &rarr; {r.suggested_model}</strong>: {r.reason}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SavingsPage() {
  return (
    <Shell>
      <SavingsContent />
    </Shell>
  );
}

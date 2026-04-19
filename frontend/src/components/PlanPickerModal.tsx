"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePaddleCheckout, type CheckoutPlan } from "@/lib/hooks/usePaddleCheckout";

type PlanRow = {
  plan: string;
  monthly_request_cap: number | null;
  seat_count: number | null;
  retention_days: number | null;
  api_key_count: number | null;
  paddle_price_id: string | null;
  paddle_product_id: string | null;
  gated_features: Record<string, boolean>;
};

type Props = {
  open: boolean;
  onClose: () => void;
};

// Display prices — source of truth is Paddle; this is presentational only.
// Matches paddle_product_spec.md (cloud=$29/mo, teams=$99/mo).
const DISPLAY_PRICE: Record<string, string> = {
  cloud: "$29/mo",
  teams: "$99/mo",
};

function fmt(v: number | null): string {
  if (v === null || v === undefined) return "Unlimited";
  return v.toLocaleString();
}

function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function PlanPickerModal({ open, onClose }: Props) {
  const { session, logout } = useAuth();
  const { loading: checkoutLoading, startCheckout } = usePaddleCheckout();
  const [plans, setPlans] = useState<PlanRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/billing/plans", session.token);
      setPlans(Array.isArray(data?.plans) ? data.plans : []);
    } catch (err: unknown) {
      if (err instanceof AuthError) {
        logout();
        return;
      }
      setError("Couldn't load plans");
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  if (!open) return null;

  const handleChoose = (plan: string) => {
    if (plan !== "cloud" && plan !== "teams") return;
    startCheckout({ plan: plan as CheckoutPlan });
  };

  const featureKeys = Array.from(
    new Set((plans || []).flatMap((p) => Object.keys(p.gated_features || {})))
  ).sort();

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="plan-picker-title"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="card" style={{ width: 720, maxWidth: "94vw", padding: 0 }}>
        <div
          className="section-header"
          style={{ display: "flex", justifyContent: "space-between" }}
        >
          <span
            id="plan-picker-title"
            className="section-header-title"
            style={{ fontWeight: 600 }}
          >
            Compare paid plans
          </span>
          <button
            aria-label="Close"
            className="btn"
            style={{ padding: "2px 10px" }}
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div style={{ padding: 18 }}>
          {loading && (
            <div className="skeleton" style={{ height: 120, borderRadius: 4 }} />
          )}
          {error && (
            <div style={{ fontSize: 13, color: "var(--muted)" }}>
              {error}{" "}
              <button
                onClick={load}
                style={{
                  background: "transparent",
                  border: "none",
                  padding: 0,
                  color: "var(--cyan)",
                  textDecoration: "underline",
                  cursor: "pointer",
                  fontSize: 13,
                }}
              >
                Retry
              </button>
            </div>
          )}
          {!loading && !error && plans && plans.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)", fontSize: 12 }}>
                  <th style={{ padding: "8px 12px", fontWeight: 500 }}> </th>
                  {plans.map((p) => (
                    <th
                      key={p.plan}
                      style={{ padding: "8px 12px", fontWeight: 600, color: "var(--text)" }}
                    >
                      {titleCase(p.plan)}
                      <div style={{ fontSize: 11, fontWeight: 400, color: "var(--muted)" }}>
                        {DISPLAY_PRICE[p.plan] || ""}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 12px", color: "var(--muted)" }}>Monthly requests</td>
                  {plans.map((p) => (
                    <td key={p.plan} style={{ padding: "10px 12px" }}>
                      {fmt(p.monthly_request_cap)}
                    </td>
                  ))}
                </tr>
                <tr style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 12px", color: "var(--muted)" }}>Seats</td>
                  {plans.map((p) => (
                    <td key={p.plan} style={{ padding: "10px 12px" }}>
                      {fmt(p.seat_count)}
                    </td>
                  ))}
                </tr>
                <tr style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 12px", color: "var(--muted)" }}>Retention</td>
                  {plans.map((p) => (
                    <td key={p.plan} style={{ padding: "10px 12px" }}>
                      {p.retention_days === null ? "Unlimited" : `${p.retention_days} days`}
                    </td>
                  ))}
                </tr>
                <tr style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 12px", color: "var(--muted)" }}>API keys</td>
                  {plans.map((p) => (
                    <td key={p.plan} style={{ padding: "10px 12px" }}>
                      {fmt(p.api_key_count)}
                    </td>
                  ))}
                </tr>
                {featureKeys.map((fk) => (
                  <tr key={fk} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "10px 12px", color: "var(--muted)" }}>{fk}</td>
                    {plans.map((p) => (
                      <td key={p.plan} style={{ padding: "10px 12px" }}>
                        {p.gated_features?.[fk] ? "\u2713" : "\u2014"}
                      </td>
                    ))}
                  </tr>
                ))}
                <tr style={{ borderTop: "1px solid var(--border)" }}>
                  <td />
                  {plans.map((p) => (
                    <td key={p.plan} style={{ padding: "12px" }}>
                      <button
                        className="btn btn-cyan"
                        onClick={() => handleChoose(p.plan)}
                        disabled={checkoutLoading}
                      >
                        {checkoutLoading ? "Loading\u2026" : `Choose ${titleCase(p.plan)}`}
                      </button>
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

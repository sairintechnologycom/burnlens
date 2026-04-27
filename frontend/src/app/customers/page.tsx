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

interface CustomerData {
  customer: string;
  api_calls: number;
  total_cost: number;
  budget_cap?: number;
}

// D-06: Per-page skeleton with the recognizable shape of the real Customers
// page (HorizontalBar-shaped placeholder + table-shaped placeholder).
// D-05: Used both as the loading state (no blur) AND as LockedPanel children
// (frosted via .locked-panel-content) so there is no flash-of-real-data for
// Free/Cloud users nor flash-of-locked for Teams users.
function CustomersSkeleton() {
  const barWidths = [78, 64, 52, 42, 32, 24];
  return (
    <div className="customers-skeleton">
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Cost by customer</span>
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
          <span className="section-header-title">Customer breakdown</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Customer</th>
              <th>Requests</th>
              <th>Total cost</th>
              <th>Budget cap</th>
            </tr>
          </thead>
          <tbody>
            {[0, 1, 2, 3, 4].map((i) => (
              <tr key={i}>
                <td>
                  <div className="skeleton" style={{ width: 140, height: 14 }} />
                </td>
                <td>
                  <div className="skeleton" style={{ width: 60, height: 14 }} />
                </td>
                <td>
                  <div className="skeleton" style={{ width: 60, height: 14 }} />
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

function CustomersContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [customers, setCustomers] = useState<CustomerData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // D-03: store the full 402 body so both required_feature AND required_plan
  // flow into LockedPanel — no hardcoded values in this file.
  const [locked, setLocked] = useState<PaymentRequiredBody | null>(null);

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    setLocked(null);
    apiFetch(`/api/v1/usage/by-customer?days=${days}`, session.token)
      .then((data) => setCustomers(data as CustomerData[]))
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
    return <CustomersSkeleton />;
  }

  if (locked) {
    return (
      <LockedPanel
        featureKey={locked.required_feature ?? "customers_view"}
        requiredPlan={locked.required_plan ?? "teams"}
      >
        <CustomersSkeleton />
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

  return (
    <div>
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Cost by customer</span>
          <span className="section-header-action">{days}d</span>
        </div>
        {customers.length > 0 ? (
          <HorizontalBar
            labels={customers.map((c) => c.customer)}
            data={customers.map((c) => c.total_cost)}
            height={Math.max(200, customers.length * 36)}
          />
        ) : (
          <div style={{ padding: 32, textAlign: "center", fontSize: 11, color: "var(--muted)" }}>
            No customer data
          </div>
        )}
      </div>

      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Customer breakdown</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Customer</th>
              <th>Requests</th>
              <th>Total cost</th>
              <th>Budget cap</th>
            </tr>
          </thead>
          <tbody>
            {customers.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                  No data
                </td>
              </tr>
            ) : (
              customers.map((c) => (
                <tr key={c.customer}>
                  <td style={{ fontWeight: 500 }}>{c.customer}</td>
                  <td>{c.api_calls.toLocaleString()}</td>
                  <td>${c.total_cost.toFixed(2)}</td>
                  <td>{c.budget_cap ? `$${c.budget_cap.toFixed(0)}` : "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function CustomersPage() {
  return (
    <Shell>
      <CustomersContent />
    </Shell>
  );
}

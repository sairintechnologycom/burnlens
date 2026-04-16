"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import HorizontalBar from "@/components/charts/HorizontalBar";
import UpgradePrompt from "@/components/UpgradePrompt";
import { apiFetch, AuthError, PaymentRequiredError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePeriod } from "@/lib/contexts/PeriodContext";

interface CustomerData {
  customer: string;
  api_calls: number;
  total_cost: number;
  budget_cap?: number;
}

function CustomersContent() {
  const { session, logout } = useAuth();
  const { days } = usePeriod();
  const [customers, setCustomers] = useState<CustomerData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [needsUpgrade, setNeedsUpgrade] = useState(false);

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    setNeedsUpgrade(false);
    apiFetch(`/api/v1/usage/by-customer?days=${days}`, session.apiKey)
      .then((data) => setCustomers(data as CustomerData[]))
      .catch((err) => {
        if (err instanceof AuthError) logout();
        else if (err instanceof PaymentRequiredError) setNeedsUpgrade(true);
        else setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [session, days, logout]);

  if (needsUpgrade) {
    return <UpgradePrompt feature="Customer breakdowns" />;
  }

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div className="skeleton" style={{ height: 250, marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 200 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <span className="error-inline" onClick={() => window.location.reload()}>
          Failed to load — retry &#x2197;
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

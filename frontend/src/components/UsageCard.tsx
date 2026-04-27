"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useBilling } from "@/lib/contexts/BillingContext";
import VerticalBar from "@/components/charts/VerticalBar";

// Phase 10 Plan 04 — Settings → Usage card.
// The card's outer anchor (#usage on the .card div) matches the sidebar
// UsageMeter href "/settings#usage" deep link (METER-03).
// Cumulative-threshold coloring (D-19): bar color is computed against the
// running cumulative sum vs the static cycle cap, NOT each day's per-bar
// volume. The chart tells the quota story; per-day volume already lives in
// /dashboard/timeline.

interface UsageDailyEntry {
  date: string;
  requests: number;
}

interface UsageDailyResponse {
  cycle_start: string;
  cycle_end: string;
  cap: number;
  current: number;
  daily: UsageDailyEntry[];
}

export default function UsageCard() {
  const { session, logout } = useAuth();
  const { billing } = useBilling();
  const [data, setData] = useState<UsageDailyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDaily = useCallback(async () => {
    if (!session?.token) return;
    setLoading(true);
    setError(null);
    try {
      const r = (await apiFetch(
        "/billing/usage/daily",
        session.token,
      )) as UsageDailyResponse;
      setData(r);
    } catch (e) {
      if (e instanceof AuthError) {
        logout();
        return;
      }
      setError("Failed to load daily breakdown.");
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => {
    fetchDaily();
  }, [fetchDaily]);

  // Cumulative-threshold coloring. Static cap from cycle start (D-19 — the
  // chart story is "when did we cross 80%", not daily volume).
  const cap = data?.cap ?? 0;
  let cumulative = 0;
  const labels = (data?.daily ?? []).map((d) =>
    new Date(d.date).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
  );
  const values = (data?.daily ?? []).map((d) => d.requests);
  const barColors = (data?.daily ?? []).map((d) => {
    cumulative += d.requests;
    const pct = cap > 0 ? (cumulative / cap) * 100 : 0;
    if (pct > 100) return "var(--red)";
    if (pct >= 80) return "var(--amber)";
    return "var(--cyan)";
  });

  // Summary numbers — prefer the daily endpoint values, fall back to the
  // BillingContext usage subobject so the row never renders dashes when the
  // /billing/summary poll has data but /usage/daily is mid-flight.
  const current =
    data?.current ?? billing?.usage?.current_cycle?.request_count ?? 0;
  const capDisplay =
    data?.cap ?? billing?.usage?.current_cycle?.monthly_request_cap ?? 0;
  const resetDate = data?.cycle_end
    ? new Date(data.cycle_end).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      })
    : "";
  const pct = capDisplay > 0 ? (current / capDisplay) * 100 : 0;
  const over = pct > 100;

  return (
    <div
      id="usage"
      className="card usage-card"
      style={{ margin: 16, marginBottom: 0 }}
    >
      <div className="section-header">
        <span className="section-header-title" style={{ fontWeight: 600 }}>
          Usage
        </span>
      </div>
      <div
        className={`usage-card-summary ${
          over ? "usage-card-summary-over" : ""
        }`}
      >
        {current.toLocaleString()} / {capDisplay.toLocaleString()}
        {over ? ` (${Math.round(pct)}%)` : ""} requests this cycle · resets{" "}
        {resetDate}
      </div>
      <div className="chart-container" style={{ height: 200, padding: 16 }}>
        {loading && (
          <div
            className="skeleton"
            style={{ width: "100%", height: "100%", borderRadius: 4 }}
          />
        )}
        {!loading && error && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              gap: 8,
              fontSize: 13,
              color: "var(--muted)",
            }}
          >
            <span>Failed to load daily breakdown.</span>
            <button
              onClick={fetchDaily}
              className="error-inline"
              style={{
                background: "transparent",
                border: "none",
                padding: 0,
                cursor: "pointer",
                fontFamily: "var(--font-sans)",
                fontSize: 13,
              }}
            >
              Retry
            </button>
          </div>
        )}
        {!loading && !error && values.length === 0 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              color: "var(--muted)",
              fontSize: 13,
            }}
          >
            No requests yet this cycle.
          </div>
        )}
        {!loading && !error && values.length > 0 && (
          <VerticalBar labels={labels} values={values} barColors={barColors} />
        )}
      </div>
    </div>
  );
}

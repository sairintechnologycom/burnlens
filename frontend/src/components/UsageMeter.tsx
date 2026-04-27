"use client";

// Phase 10 D-12..D-17: sidebar-footer usage meter.
// Reads from BillingContext, which polls /billing/summary at 60s
// visibility-gated cadence (set in Plan 10-02 Task 1, D-17 override of
// Phase 7 D-18's 30s). Do NOT add a second poller here.
//
// Threat: T-10-07 (XSS via API-derived numeric fields).
// Mitigation: every value (cap, request_count, end-date) is rendered as a
// React text child (auto-escaped). No raw-HTML escape hatches are used.

import Link from "next/link";
import { useBilling } from "@/lib/contexts/BillingContext";

const ONE_DAY_MS = 24 * 60 * 60 * 1000;

function formatResetDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "next cycle";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function UsageMeter() {
  const { billing } = useBilling();
  // Backend returns the cycle fields flat on `usage` — see BillingContext.tsx.
  const cycle = billing?.usage ?? null;

  // Loading state — no billing payload yet.
  if (!cycle) {
    return (
      <Link
        href="/settings#usage"
        className="usage-meter"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={0}
        aria-label="Usage: loading"
      >
        <div className="usage-meter-bar">
          <div className="usage-meter-fill skeleton" style={{ width: "0%" }} />
        </div>
        <div className="usage-meter-numeric">— / —</div>
        <div className="usage-meter-reset">loading…</div>
      </Link>
    );
  }

  const current = Number(cycle.request_count) || 0;
  const cap = Number(cycle.monthly_request_cap) || 0;
  const pct = cap > 0 ? (current / cap) * 100 : 0;
  const widthPct = Math.min(100, pct); // D-14: clamp bar width at 100%
  const band: "green" | "amber" | "red" =
    pct > 100 ? "red" : pct >= 80 ? "amber" : "green"; // "green" class uses cyan token per UI-SPEC

  // Empty-cycle state: brand-new cycle (< 24h old) with zero usage.
  const cycleStartMs = new Date(cycle.start).getTime();
  const isEmptyCycle =
    current === 0 &&
    !Number.isNaN(cycleStartMs) &&
    Date.now() - cycleStartMs < ONE_DAY_MS;

  const resetDate = formatResetDate(cycle.end);
  const subtitle = isEmptyCycle ? "first cycle" : `resets ${resetDate}`;
  const ariaLive: "polite" | undefined =
    band === "amber" || band === "red" ? "polite" : undefined;

  const ariaLabel = `Usage: ${current.toLocaleString()} of ${cap.toLocaleString()} requests this cycle. Resets ${resetDate}.`;

  return (
    <Link
      href="/settings#usage"
      className="usage-meter"
      role="progressbar"
      aria-valuenow={current}
      aria-valuemin={0}
      aria-valuemax={cap}
      aria-label={ariaLabel}
    >
      <div className="usage-meter-bar">
        {!isEmptyCycle && (
          <div
            className={`usage-meter-fill usage-meter-fill--${band}`}
            style={{ width: `${widthPct}%` }}
          />
        )}
      </div>
      <div className="usage-meter-numeric" aria-live={ariaLive}>
        {current.toLocaleString()} / {cap.toLocaleString()}
        {pct > 100 && (
          <span className="usage-meter-numeric-over">({Math.round(pct)}%)</span>
        )}
      </div>
      <div className="usage-meter-reset">{subtitle}</div>
    </Link>
  );
}

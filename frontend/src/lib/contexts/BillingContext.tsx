"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */


import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import type {
  BillingSummary,
  UsageCurrentCycle,
  AvailablePlan,
  ApiKeysSummary,
} from "@/lib/contracts";

// Billing response shapes now live in @/lib/contracts as the single source of
// truth, paired with field manifests the frontend↔API contract test enforces
// (burnlens_cloud/models.py: BillingSummary / UsageCurrentCycle / AvailablePlan /
// ApiKeysSummary). The W5 status-is-loose-string resolution and the additive,
// optional usage/available_plans/api_keys fields are documented there. NOTE: the
// api_keys table is scoped on workspace_id (not org_id) — see 10-01-SUMMARY.md
// decision #2. Re-exported here so existing importers (settings/page.tsx,
// CancelSubscriptionModal.tsx) keep resolving these from BillingContext.
export type { BillingSummary, UsageCurrentCycle, AvailablePlan, ApiKeysSummary };

interface BillingContextValue {
  billing: BillingSummary | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setBilling: (next: BillingSummary) => void;
}

const DEFAULT_VALUE: BillingContextValue = {
  billing: null,
  loading: true,
  error: null,
  refresh: async () => {},
  setBilling: () => {},
};

const BillingContext = createContext<BillingContextValue>(DEFAULT_VALUE);

// Phase 10 D-17: bumped from Phase 7 D-18's 30_000ms to 60_000ms.
// Rationale: the sidebar usage meter is the most prominent live counter and
// it just needs "freshish" — a 60s tick is plenty for a million-request-per-
// month cap and halves the polling load. The visibility-gating below
// (document.visibilityState === "visible") is unchanged.
const POLL_INTERVAL_MS = 60_000;
const REFRESH_ON_FOCUS_STALENESS_MS = 10_000;

// W5 runtime guard: known Paddle states. Unknown values fall back to "active"
// so the UI never renders a broken pill for a future Paddle state before we
// add first-class support for it.
const KNOWN_STATUSES = new Set<string>([
  "active",
  "trialing",
  "past_due",
  "canceled",
  "paused",
]);

export function BillingProvider({ children }: { children: React.ReactNode }) {
  const { session, logout } = useAuth();
  const [billing, setBillingState] = useState<BillingSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const lastFetchRef = useRef(0);

  const refresh = useCallback(async () => {
    if (!session) return;
    try {
      const data = (await apiFetch("/billing/summary", session.token)) as BillingSummary;
      // W5 runtime guard: coerce unknown Paddle states to "active" so the
      // UI is never broken by a new backend state.
      const safe: BillingSummary = {
        ...data,
        status: KNOWN_STATUSES.has(data.status) ? data.status : "active",
      };
      setBillingState(safe);
      setError(null);
      lastFetchRef.current = Date.now();
    } catch (err: any) {
      if (err instanceof AuthError) {
        logout();
        return;
      }
      setError(err?.message || "Failed to load billing");
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  // D-22 escape hatch: mutation endpoints return a fresh BillingSummary in their
  // response body. Callers pass that body straight to setBilling() so the UI
  // flips without a separate /summary round-trip. Applies the same W5
  // KNOWN_STATUSES coercion as refresh(), clears any stale error, and bumps
  // lastFetchRef so the focus-staleness logic does not immediately re-fetch.
  const applyBilling = useCallback((next: BillingSummary) => {
    const safe: BillingSummary = {
      ...next,
      status: KNOWN_STATUSES.has(next.status) ? next.status : "active",
    };
    setBillingState(safe);
    setError(null);
    lastFetchRef.current = Date.now();
  }, []);

  // Initial fetch + polling interval (paused when tab is hidden).
  useEffect(() => {
    if (!session) return;
    refresh();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") {
        refresh();
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [session, refresh]);

  // Refetch on window focus if stale (> 10s since last successful fetch).
  useEffect(() => {
    if (!session) return;
    const onFocus = () => {
      if (Date.now() - lastFetchRef.current > REFRESH_ON_FOCUS_STALENESS_MS) {
        refresh();
      }
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [session, refresh]);

  return (
    <BillingContext.Provider value={{ billing, loading, error, refresh, setBilling: applyBilling }}>
      {children}
    </BillingContext.Provider>
  );
}

// BLOCKER 3 — useBilling MUST NEVER raise. The hook body is a single
// useContext call. Do NOT add `if (!ctx) raise...` — the default
// value wired into createContext() above IS the out-of-provider fallback.
// This mirrors PeriodContext and keeps route transitions + error boundaries
// from cascade-breaking when a component renders briefly outside Shell.tsx.
export function useBilling(): BillingContextValue {
  return useContext(BillingContext);
}

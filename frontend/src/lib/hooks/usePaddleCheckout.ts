"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckoutEventNames, initializePaddle, type Paddle } from "@paddle/paddle-js";

import { apiFetch, AuthError } from "@/lib/api";
import { useBilling } from "@/lib/contexts/BillingContext";
import { useToast } from "@/lib/contexts/ToastContext";
import { useAuth } from "@/lib/hooks/useAuth";

const PADDLE_ENV = (process.env.NEXT_PUBLIC_PADDLE_ENV || "sandbox") as
  | "sandbox"
  | "production";
const PADDLE_TOKEN = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN || "";

export type CheckoutPlan = "cloud" | "teams";
export type CheckoutPeriod = "monthly" | "annual";

export interface StartCheckoutOptions {
  plan: CheckoutPlan;
  period?: CheckoutPeriod;
}

export interface UsePaddleCheckout {
  /** true once initializePaddle has resolved (or skipped because token is missing). */
  ready: boolean;
  /** true while a /billing/checkout request is in flight. */
  loading: boolean;
  /**
   * Launch checkout for the given plan.
   *
   * Flow (matches D-02 canonical pattern):
   *   1. POST /billing/checkout { plan } → { transaction_id, url }
   *   2. If Paddle.js initialized AND transaction_id present: Paddle.Checkout.open({ transactionId })
   *   3. Else if data.url present: window.location.href = data.url
   *   4. Else: showToast error so the user knows the click failed.
   *
   * Never throws. On any error, surfaces a toast so the user isn't silently stranded.
   */
  startCheckout: (opts: StartCheckoutOptions) => Promise<void>;
}

// The plan flip is driven by Paddle's `subscription.activated` webhook, which lands
// server-side some seconds after the buyer sees "transaction completed". Without
// these nudges the only thing that notices is BillingContext's 60s poll, so a paying
// user watches a stale "Free" plan with no acknowledgement that anything happened.
// ponytail: fixed retry ladder rather than polling until the plan actually changes —
// swap for a real until-changed loop if the webhook ever lags past 30s.
const POST_CHECKOUT_REFRESH_DELAYS_MS = [0, 2_000, 5_000, 10_000, 20_000, 30_000];

/**
 * Which refreshes a Paddle checkout event should schedule. Exported so the money
 * path is testable without a DOM: every other checkout event (`checkout.closed`,
 * `checkout.payment.error`, …) must schedule nothing, or a user who abandons the
 * form gets told their plan is activating.
 */
export function activationRefreshDelays(eventName: string | undefined): number[] {
  return eventName === CheckoutEventNames.CHECKOUT_COMPLETED
    ? POST_CHECKOUT_REFRESH_DELAYS_MS
    : [];
}

export function usePaddleCheckout(): UsePaddleCheckout {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const { refresh } = useBilling();
  const paddleRef = useRef<Paddle | undefined>(undefined);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);

  // initializePaddle runs once on mount, so its eventCallback closes over the first
  // render's `refresh`/`showToast`. Read them through a ref so the callback always
  // calls the current ones.
  const handlersRef = useRef({ refresh, showToast });
  handlersRef.current = { refresh, showToast };

  useEffect(() => {
    if (!PADDLE_TOKEN) {
      // No client token configured — we'll rely entirely on the hosted URL fallback.
      setReady(true);
      return;
    }
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    initializePaddle({
      environment: PADDLE_ENV,
      token: PADDLE_TOKEN,
      eventCallback: (event) => {
        const delays = activationRefreshDelays(event.name);
        if (cancelled || delays.length === 0) return;
        handlersRef.current.showToast(
          "Payment received — activating your plan. This can take a few seconds.",
          "success",
        );
        for (const delay of delays) {
          timers.push(setTimeout(() => handlersRef.current.refresh(), delay));
        }
      },
    })
      .then((p) => {
        if (cancelled) return;
        paddleRef.current = p;
        setReady(true);
      })
      .catch(() => {
        // Paddle.js failed to load — ready=true anyway so startCheckout falls back to data.url.
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, []);

  const startCheckout = useCallback(
    async ({ plan, period = "monthly" }: StartCheckoutOptions) => {
      if (!session || loading) return;
      setLoading(true);
      try {
        const data = await apiFetch("/billing/checkout", session.token, {
          method: "POST",
          body: JSON.stringify({ plan, period }),
        });

        if (data?.transaction_id && paddleRef.current) {
          paddleRef.current.Checkout.open({
            transactionId: data.transaction_id,
          });
          return;
        }

        if (data?.url) {
          window.location.href = data.url;
          return;
        }

        showToast(
          "Couldn't open checkout. Please try again or email contact@sairintechnology.com.",
          "error",
        );
      } catch (err) {
        if (err instanceof AuthError) {
          logout();
          return;
        }
        const detail =
          err instanceof Error && err.message ? err.message : "Unknown error";
        showToast(`Couldn't open checkout: ${detail}`, "error");
      } finally {
        setLoading(false);
      }
    },
    [session, loading, logout, showToast],
  );

  return { ready, loading, startCheckout };
}

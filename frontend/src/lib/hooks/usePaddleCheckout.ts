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

// The plan flip is driven by Paddle's subscription webhooks, which land server-side
// some seconds after the buyer sees "transaction completed". Without these nudges the
// only thing that notices is BillingContext's 60s poll, so a paying user watches a
// stale plan with no acknowledgement that anything happened.
//
// This was first written as a fixed 0/2/5/10/20/30s ladder. A live Cloud→Teams upgrade
// on 2026-08-15 then flipped on the *last* rung, i.e. the real lag reached ~30s and the
// ladder had no margin left. So poll until the plan actually changes instead of
// guessing when it will.
const ACTIVATION_POLL_INTERVAL_MS = 2_000;
const ACTIVATION_POLL_TIMEOUT_MS = 180_000;

/**
 * True for the one checkout event that means money moved. Exported so the money path
 * is testable without a DOM: every other checkout event (`checkout.closed`,
 * `checkout.payment.error`, …) must do nothing, or a user who abandons the form gets
 * told their plan is activating.
 */
export function isActivationEvent(eventName: string | undefined): boolean {
  return eventName === CheckoutEventNames.CHECKOUT_COMPLETED;
}

/**
 * Whether to stop polling for the post-checkout plan flip.
 *
 * `targetPlan` is what the buyer just paid for. Comparing against it — rather than
 * "changed from what it was" — is what makes this correct for a Cloud→Teams upgrade,
 * where the pre-checkout plan is already a paid one.
 */
export function activationPollDone(
  currentPlan: string | undefined,
  targetPlan: string,
  elapsedMs: number,
): boolean {
  if (currentPlan?.toLowerCase() === targetPlan.toLowerCase()) return true;
  // Give up eventually rather than polling a dead webhook forever. BillingContext's
  // own 60s poll still runs, so a very late webhook is picked up regardless.
  return elapsedMs >= ACTIVATION_POLL_TIMEOUT_MS;
}

export function usePaddleCheckout(): UsePaddleCheckout {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const { billing, refresh } = useBilling();
  const paddleRef = useRef<Paddle | undefined>(undefined);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);

  // The plan the buyer is currently paying for, set by startCheckout. Read inside the
  // eventCallback, which has no other way to know what was purchased.
  const targetPlanRef = useRef<CheckoutPlan | null>(null);

  // initializePaddle runs once on mount, so its eventCallback closes over the first
  // render's values. Read them through a ref so the callback always sees the current
  // ones — `billing` in particular changes on every refresh, and the poll below is
  // reading it to decide when to stop.
  const handlersRef = useRef({ refresh, showToast, billing });
  handlersRef.current = { refresh, showToast, billing };

  useEffect(() => {
    if (!PADDLE_TOKEN) {
      // No client token configured — we'll rely entirely on the hosted URL fallback.
      setReady(true);
      return;
    }
    let cancelled = false;
    let pollTimer: ReturnType<typeof setInterval> | undefined;
    initializePaddle({
      environment: PADDLE_ENV,
      token: PADDLE_TOKEN,
      eventCallback: (event) => {
        if (cancelled || !isActivationEvent(event.name)) return;
        const targetPlan = targetPlanRef.current;
        handlersRef.current.showToast(
          "Payment received — activating your plan. This can take a few seconds.",
          "success",
        );
        handlersRef.current.refresh();
        if (!targetPlan) return;

        // Poll until the webhook has actually landed and the plan reads back as the
        // one just bought.
        const startedAt = Date.now();
        clearInterval(pollTimer);
        pollTimer = setInterval(() => {
          const done = activationPollDone(
            handlersRef.current.billing?.plan,
            targetPlan,
            Date.now() - startedAt,
          );
          if (done || cancelled) {
            clearInterval(pollTimer);
            return;
          }
          handlersRef.current.refresh();
        }, ACTIVATION_POLL_INTERVAL_MS);
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
      clearInterval(pollTimer);
    };
  }, []);

  const startCheckout = useCallback(
    async ({ plan, period = "monthly" }: StartCheckoutOptions) => {
      if (!session || loading) return;
      setLoading(true);
      targetPlanRef.current = plan;
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

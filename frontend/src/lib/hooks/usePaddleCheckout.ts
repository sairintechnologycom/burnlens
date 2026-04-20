"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { initializePaddle, type Paddle } from "@paddle/paddle-js";

import { apiFetch, AuthError } from "@/lib/api";
import { useToast } from "@/lib/contexts/ToastContext";
import { useAuth } from "@/lib/hooks/useAuth";

const PADDLE_ENV = (process.env.NEXT_PUBLIC_PADDLE_ENV || "sandbox") as
  | "sandbox"
  | "production";
const PADDLE_TOKEN = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN || "";

export type CheckoutPlan = "cloud" | "teams";

export interface StartCheckoutOptions {
  plan: CheckoutPlan;
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

export function usePaddleCheckout(): UsePaddleCheckout {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const paddleRef = useRef<Paddle | undefined>(undefined);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!PADDLE_TOKEN) {
      // No client token configured — we'll rely entirely on the hosted URL fallback.
      setReady(true);
      return;
    }
    let cancelled = false;
    initializePaddle({ environment: PADDLE_ENV, token: PADDLE_TOKEN })
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
    };
  }, []);

  const startCheckout = useCallback(
    async ({ plan }: StartCheckoutOptions) => {
      if (!session || loading) return;
      setLoading(true);
      try {
        const data = await apiFetch("/billing/checkout", session.token, {
          method: "POST",
          body: JSON.stringify({ plan }),
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

"use client";

import { useEffect, useRef, useState } from "react";
import { initializePaddle, type Paddle } from "@paddle/paddle-js";

import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";

const PADDLE_ENV = (process.env.NEXT_PUBLIC_PADDLE_ENV || "sandbox") as
  | "sandbox"
  | "production";
const PADDLE_TOKEN = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN || "";

export default function UpgradePrompt({ feature }: { feature: string }) {
  const { session } = useAuth();
  const paddleRef = useRef<Paddle | undefined>(undefined);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!PADDLE_TOKEN) return;
    let cancelled = false;
    initializePaddle({ environment: PADDLE_ENV, token: PADDLE_TOKEN })
      .then((p) => {
        if (!cancelled) paddleRef.current = p;
      })
      .catch(() => {
        // Paddle.js failed to load — we'll fall back to the hosted checkout URL
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleUpgrade = async () => {
    if (!session || loading) return;
    setLoading(true);
    try {
      const data = await apiFetch("/billing/checkout", session.token, {
        method: "POST",
        body: JSON.stringify({ plan: "cloud" }),
      });

      if (data.transaction_id && paddleRef.current) {
        paddleRef.current.Checkout.open({
          transactionId: data.transaction_id,
        });
        return;
      }

      if (data.url) {
        window.location.href = data.url;
        return;
      }

      window.location.href = "/settings";
    } catch {
      window.location.href = "/settings";
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="upgrade-prompt">
      <svg className="upgrade-prompt-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
        <rect x="3" y="7" width="10" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
        <path d="M5 7V5a3 3 0 116 0v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <div className="upgrade-prompt-title">
        {feature} requires Team plan
      </div>
      <div className="upgrade-prompt-sub">
        Upgrade to unlock team breakdowns, 90-day history, and budget enforcement
      </div>
      <button
        className="upgrade-prompt-btn"
        onClick={handleUpgrade}
        disabled={loading}
      >
        {loading ? "Loading..." : "Upgrade — $29/mo"}
      </button>
    </div>
  );
}

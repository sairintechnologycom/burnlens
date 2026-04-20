"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { initializePaddle, type Paddle } from "@paddle/paddle-js";

const PADDLE_ENV = (process.env.NEXT_PUBLIC_PADDLE_ENV || "sandbox") as
  | "sandbox"
  | "production";
const PADDLE_TOKEN = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN || "";

function CheckoutFallback() {
  const router = useRouter();
  const params = useSearchParams();
  const transactionId = params.get("_ptxn");
  const [status, setStatus] = useState<"loading" | "launching" | "missing" | "failed">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!transactionId) {
      setStatus("missing");
      return;
    }
    if (!PADDLE_TOKEN) {
      setStatus("failed");
      setError("Paddle client token not configured.");
      return;
    }

    let paddle: Paddle | undefined;
    initializePaddle({ environment: PADDLE_ENV, token: PADDLE_TOKEN })
      .then((p) => {
        paddle = p;
        if (!paddle) {
          setStatus("failed");
          setError("Failed to initialize Paddle.");
          return;
        }
        setStatus("launching");
        paddle.Checkout.open({
          transactionId,
          settings: {
            successUrl: `${window.location.origin}/settings?checkout=success`,
          },
        });
      })
      .catch((e: unknown) => {
        setStatus("failed");
        setError(e instanceof Error ? e.message : "Unknown error");
      });
  }, [transactionId]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
        gap: 16,
        background: "var(--bg)",
        color: "var(--text)",
        fontFamily: "var(--font-sans), system-ui, sans-serif",
        padding: 24,
        textAlign: "center",
      }}
    >
      {status === "loading" && <p>Loading checkout…</p>}
      {status === "launching" && <p>Launching Paddle checkout…</p>}
      {status === "missing" && (
        <>
          <p>No transaction to continue.</p>
          <button
            className="btn btn-cyan"
            onClick={() => router.push("/settings#billing")}
          >
            Back to billing
          </button>
        </>
      )}
      {status === "failed" && (
        <>
          <p>Checkout couldn&apos;t open.</p>
          {error && (
            <code style={{ fontSize: 12, color: "var(--muted)", maxWidth: 480 }}>
              {error}
            </code>
          )}
          <button
            className="btn btn-cyan"
            onClick={() => router.push("/settings#billing")}
          >
            Back to billing
          </button>
        </>
      )}
    </div>
  );
}

export default function CheckoutPage() {
  return (
    <Suspense fallback={<div style={{ padding: 48, textAlign: "center" }}>Loading…</div>}>
      <CheckoutFallback />
    </Suspense>
  );
}

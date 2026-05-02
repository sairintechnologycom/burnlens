"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, Mail } from "lucide-react";
import { useBilling } from "@/lib/contexts/BillingContext";
import type { AuthSession } from "@/lib/hooks/useAuth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8420";

/**
 * Billing and email-verification status banners.
 *
 * Renders up to two stacked banners immediately below <Topbar />:
 * 1. Past-due billing banner (amber) — preserved from Phase 7 UI-SPEC.
 * 2. Email verification reminder banner (amber) — new in Phase 11.
 *
 * Call sites that do not pass `session` are safe — the prop defaults to
 * `undefined` so `showVerify` evaluates to `false`.
 */

interface Props {
  billing?: { status: string } | null;
  session?: AuthSession | null;
}

export function BillingStatusBanner({ billing, session }: Props) {
  const showPastDue = billing?.status === "past_due";
  const showVerify = session?.emailVerified === false && session?.isLocal === false;
  const [resendStatus, setResendStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");

  async function handleResend() {
    if (resendStatus !== "idle") return;
    setResendStatus("sending");
    try {
      await fetch(`${API_BASE}/auth/resend-verification`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: session?.ownerEmail ?? "" }),
        credentials: "include",
      });
      setResendStatus("sent");
    } catch {
      setResendStatus("error");
    }
  }

  if (!showPastDue && !showVerify) return null;

  return (
    <>
      {showPastDue && (
        <div
          role="status"
          aria-live="polite"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            height: 40,
            padding: "0 24px",
            background: "color-mix(in srgb, var(--amber) 12%, var(--bg2))",
            borderLeft: "3px solid var(--amber)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <AlertTriangle size={14} color="var(--amber)" aria-hidden="true" />
          <p style={{ margin: 0, fontSize: 12, lineHeight: 1.4, color: "var(--text)" }}>
            Payment failed —{" "}
            <Link
              href="/settings#billing"
              style={{
                color: "var(--amber)",
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              update billing
            </Link>
          </p>
        </div>
      )}
      {showVerify && (
        <div
          role="status"
          aria-label="Email verification required"
          aria-live="polite"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            height: 40,
            padding: "0 24px",
            background: "color-mix(in srgb, var(--amber) 12%, var(--bg2))",
            borderLeft: "3px solid var(--amber)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <Mail size={14} color="var(--amber)" aria-hidden="true" />
          <p style={{ margin: 0, fontSize: 12, lineHeight: 1.4, color: "var(--text)" }}>
            Verify your email to secure your account —{" "}
            {resendStatus === "sent" ? (
              <span style={{ color: "var(--amber)", fontWeight: 600 }}>email sent!</span>
            ) : (
              <button
                onClick={handleResend}
                disabled={resendStatus !== "idle"}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  color: "var(--amber)",
                  fontWeight: 600,
                  fontSize: "inherit",
                  cursor: resendStatus === "idle" ? "pointer" : "default",
                  textDecoration: "none",
                }}
              >
                {resendStatus === "sending" ? "sending…" : resendStatus === "error" ? "try again" : "resend verification email"}
              </button>
            )}
          </p>
        </div>
      )}
    </>
  );
}

/**
 * Connected wrapper for use in Shell.tsx — reads billing from context.
 * Accepts optional `session` to also show the email verification banner.
 */
export default function BillingStatusBannerConnected({
  session,
}: {
  session?: AuthSession | null;
}) {
  const { billing } = useBilling();
  return <BillingStatusBanner billing={billing} session={session} />;
}

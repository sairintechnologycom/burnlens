"use client";

import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { useBilling } from "@/lib/contexts/BillingContext";

/**
 * Past-due banner — renders only when `billing.status === "past_due"`.
 * Mounted inside Shell.tsx just below <Topbar /> so it appears above every
 * authenticated page's content. Copy and visuals are locked by
 * .planning/phases/07-paddle-lifecycle-sync/07-UI-SPEC.md (D-14, D-21).
 */
export default function BillingStatusBanner() {
  const { billing } = useBilling();
  if (billing?.status !== "past_due") return null;

  return (
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
  );
}

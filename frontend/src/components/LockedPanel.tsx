"use client";

import { useEffect, useRef } from "react";
import { useBilling } from "@/lib/contexts/BillingContext";
import { usePaddleCheckout } from "@/lib/hooks/usePaddleCheckout";

// D-03: FEATURE_LABELS maps the Phase 9 402 body's `required_feature`
// slug → human display name. If a required_feature is not in this map,
// fall back to the raw slug so the UI still renders (graceful
// degradation — backend may add a new gated feature before the frontend
// learns about it). T-10-12: rendered as a React text child (auto-escaped),
// never via raw-HTML injection sinks.
const FEATURE_LABELS: Record<string, string> = {
  teams_view: "Team breakdowns",
  customers_view: "Customer attribution",
  custom_signatures: "Custom provider signatures",
  otel_export: "OTEL export",
};

export interface LockedPanelProps {
  /** e.g., "teams_view" — matches the 402 body's `required_feature`. */
  featureKey: string;
  /** From the 402 body — e.g., "teams" or "cloud". */
  requiredPlan?: string;
  /** Escape hatch for callers that need a custom heading. */
  titleOverride?: string;
  /** Page-specific shape-preserving skeleton (rendered behind frosted overlay). */
  children: React.ReactNode;
}

export default function LockedPanel({
  featureKey,
  requiredPlan = "teams",
  titleOverride,
  children,
}: LockedPanelProps) {
  const { billing } = useBilling();
  const { startCheckout, loading } = usePaddleCheckout();
  const cardRef = useRef<HTMLDivElement>(null);

  // D-03: derive copy from the 402 body + BillingContext.available_plans.
  const featureDisplay = FEATURE_LABELS[featureKey] ?? featureKey;
  const planLabel =
    requiredPlan.charAt(0).toUpperCase() + requiredPlan.slice(1);
  const priceCents = billing?.available_plans?.find(
    (p) => p.plan === requiredPlan,
  )?.price_cents;
  const priceDollars =
    typeof priceCents === "number" ? Math.round(priceCents / 100) : null;

  const title = titleOverride ?? `${featureDisplay} requires ${planLabel} plan`;
  const body =
    priceDollars !== null
      ? `Upgrade to ${planLabel} — $${priceDollars}/mo`
      : `Upgrade to ${planLabel}`;
  const ctaLabel = loading ? "Loading…" : `Upgrade to ${planLabel}`;

  // Accessibility: focus the overlay card on mount so keyboard users land
  // on the CTA context. tabIndex={-1} makes the dialog programmatically
  // focusable without becoming a tab stop itself.
  useEffect(() => {
    cardRef.current?.focus();
  }, []);

  const handleUpgrade = () => {
    // D-04: direct Paddle overlay — no router hop, no <a href>. Narrow
    // requiredPlan to the supported CheckoutPlan set here rather than at
    // the hook boundary (the hook's type forbids arbitrary strings).
    if (requiredPlan === "cloud" || requiredPlan === "teams") {
      startCheckout({ plan: requiredPlan });
    }
  };

  return (
    <div className="locked-panel">
      <div className="locked-panel-content" aria-hidden="true">
        {children}
      </div>
      <div className="locked-panel-overlay">
        <div
          ref={cardRef}
          className="locked-panel-card"
          role="dialog"
          aria-labelledby="lp-title"
          aria-describedby="lp-body"
          tabIndex={-1}
        >
          {/* Inline lock SVG — same approach as the legacy UpgradePrompt
              (D-11). Sized 32×32 for the larger frosted-overlay card. */}
          <svg
            className="locked-panel-lock"
            width="32"
            height="32"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          <h2 id="lp-title" className="locked-panel-title">
            {title}
          </h2>
          <p id="lp-body" className="locked-panel-body">
            {body}
          </p>
          <button
            className="upgrade-prompt-btn"
            onClick={handleUpgrade}
            disabled={loading}
            type="button"
          >
            {ctaLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

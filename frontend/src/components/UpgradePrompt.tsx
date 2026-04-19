"use client";

import { usePaddleCheckout } from "@/lib/hooks/usePaddleCheckout";

export default function UpgradePrompt({ feature }: { feature: string }) {
  const { loading, startCheckout } = usePaddleCheckout();

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
        onClick={() => startCheckout({ plan: "cloud" })}
        disabled={loading}
      >
        {loading ? "Loading..." : "Upgrade — $29/mo"}
      </button>
    </div>
  );
}

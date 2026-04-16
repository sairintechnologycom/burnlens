"use client";

import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";

export default function UpgradePrompt({ feature }: { feature: string }) {
  const { session } = useAuth();

  const handleUpgrade = async () => {
    if (!session) return;
    try {
      const data = await apiFetch("/api/v1/billing/checkout", session.token, { method: "POST" });
      if (data.url) window.location.href = data.url;
    } catch {
      // fallback
      window.location.href = "/settings";
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
      <button className="upgrade-prompt-btn" onClick={handleUpgrade}>
        Upgrade — $49/mo
      </button>
    </div>
  );
}

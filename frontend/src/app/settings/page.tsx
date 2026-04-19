"use client";

import { useState, useEffect } from "react";
import Shell from "@/components/Shell";
import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useToast } from "@/lib/contexts/ToastContext";
import { useBilling } from "@/lib/contexts/BillingContext";

function SettingsContent() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const { billing, loading: billingLoading, error: billingError, refresh: refreshBilling } = useBilling();
  const [copied, setCopied] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    document.title = "Settings | BurnLens";
  }, []);

  // Phase 7 D-20: post-checkout refresh handoff for Phase 8.
  // When Settings mounts with ?checkout=success in the URL, invalidate the
  // billing query immediately and strip the param so reloads don't re-trigger.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") === "success") {
      refreshBilling();
      params.delete("checkout");
      const qs = params.toString();
      const next =
        window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash;
      window.history.replaceState({}, "", next);
    }
  }, [refreshBilling]);

  const handleCopy = () => {
    if (!session) return;
    navigator.clipboard.writeText(session.apiKey);
    setCopied(true);
    showToast("API key copied", "success");
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRegenerate = async () => {
    if (!session) return;
    if (!confirm("Regenerate your API key? The old key will stop working immediately.")) return;
    setRegenerating(true);
    try {
      const data = await apiFetch("/api/v1/orgs/regenerate-key", session.token, { method: "POST" });
      localStorage.setItem("burnlens_api_key", data.api_key);
      showToast("API key regenerated", "success");
      window.location.reload();
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else showToast("Failed: " + err.message, "error");
    } finally {
      setRegenerating(false);
    }
  };

  const handleSync = async () => {
    if (!session) return;
    setSyncing(true);
    try {
      await apiFetch("/api/v1/sync/trigger", session.token, { method: "POST" });
      showToast("Sync triggered", "success");
    } catch (err: any) {
      if (err instanceof AuthError) logout();
      else showToast("Sync failed: " + err.message, "error");
    } finally {
      setSyncing(false);
    }
  };

  const maskedKey = session?.apiKey
    ? `${session.apiKey.slice(0, 12)}${"•".repeat(8)}`
    : "—";

  return (
    <div>
      {/* Billing — Phase 7 */}
      <div id="billing" className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title" style={{ fontWeight: 600 }}>
            Billing
          </span>
        </div>
        <div style={{ padding: 16 }}>
          <BillingCardBody
            billing={billing}
            loading={billingLoading}
            error={billingError}
            onRetry={refreshBilling}
          />
        </div>
      </div>
      {/* /Billing — Phase 7 */}

      {/* Organization */}
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Organization</span>
        </div>
        <div style={{ padding: 18 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 16, marginBottom: 16 }}>
            <div>
              <label className="form-label">Org name</label>
              <input
                className="form-input"
                defaultValue={session?.workspaceName}
                style={{ fontFamily: "var(--font-sans)" }}
              />
            </div>
          </div>

          <div>
            <label className="form-label">API key</label>
            <div style={{ display: "flex", gap: 8 }}>
              <div className="form-input" style={{ flex: 1, color: "var(--muted)", userSelect: "none" }}>
                {maskedKey}
              </div>
              <button className="btn" onClick={handleCopy}>
                {copied ? "Copied" : "Copy"}
              </button>
              <button
                className="btn btn-red"
                onClick={handleRegenerate}
                disabled={regenerating}
              >
                {regenerating ? "..." : "Regenerate"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Cloud sync */}
      <div className="card" style={{ margin: 16, marginBottom: 0 }}>
        <div className="section-header">
          <span className="section-header-title">Cloud sync</span>
        </div>
        <div style={{ padding: 18 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <div>
              <label className="form-label">Status</label>
              <div style={{
                padding: "8px 12px",
                background: "var(--bg3)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "var(--green)",
              }}>
                Enabled
              </div>
            </div>
            <div>
              <label className="form-label">Endpoint</label>
              <div className="form-input" style={{ color: "var(--muted)" }}>
                {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}
              </div>
            </div>
          </div>
          <button className="btn btn-cyan" onClick={handleSync} disabled={syncing}>
            {syncing ? "Syncing..." : "Sync now"}
          </button>
        </div>
      </div>

      {/* Connections */}
      <div className="card" style={{ margin: 16 }}>
        <div className="section-header">
          <span className="section-header-title">Connections</span>
        </div>
        <div style={{ padding: 18, fontSize: 12, color: "var(--muted)" }}>
          Provider connections are managed via the Connections page.
        </div>
      </div>
    </div>
  );
}

// -- Billing card body -------------------------------------------------------
type BillingCardBodyProps = {
  billing: import("@/lib/contexts/BillingContext").BillingSummary | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
};

function formatPrice(
  priceCents: number | null,
  currency: string | null
): string {
  if (priceCents === null || priceCents === undefined) return "$0";
  const amount = priceCents / 100;
  const cur = (currency || "USD").toUpperCase();
  if (cur === "USD") {
    return `$${Number.isInteger(amount) ? amount : amount.toFixed(2)}/mo`;
  }
  try {
    return (
      new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: cur,
      }).format(amount) + "/mo"
    );
  } catch {
    return `${amount} ${cur}/mo`;
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "";
  }
}

// W2: explicit canceled/paused branch BEFORE the fall-through Active. Webhook
// races can leave plan='free' with status='canceled' for a short window —
// render them as Active per D-22/D-23 intent (the Plan-free state IS the
// post-cancellation steady state in our model).
function statusDisplay(
  status: string
): { label: string; dot: string; labelColor: string } {
  // dot + label colors are read from CSS tokens via var(--...)
  if (status === "past_due") {
    return { label: "Past due", dot: "var(--amber)", labelColor: "var(--text)" };
  }
  if (status === "trialing") {
    return { label: "Trialing", dot: "var(--amber)", labelColor: "var(--text)" };
  }
  if (status === "canceled" || status === "paused") {
    // D-22 / D-23: the workspace has already been downgraded to plan='free'
    // by the webhook. Render as Active so the free-tier card is coherent.
    return { label: "Active", dot: "var(--cyan)", labelColor: "var(--text)" };
  }
  // active | unknown future state (W5-coerced upstream) → Active
  return { label: "Active", dot: "var(--cyan)", labelColor: "var(--text)" };
}

function BillingCardBody({ billing, loading, error, onRetry }: BillingCardBodyProps) {
  if (loading && !billing) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="skeleton" style={{ width: 140, height: 14, borderRadius: 3 }} />
          <div
            className="skeleton"
            style={{ width: 72, height: 24, borderRadius: 999 }}
          />
        </div>
        <div className="skeleton" style={{ width: 160, height: 13, borderRadius: 3 }} />
        <button
          className="btn"
          disabled
          aria-disabled="true"
          title="Coming soon — self-serve billing ships in Phase 8"
          style={{ opacity: 0.6, cursor: "not-allowed", alignSelf: "flex-start" }}
        >
          Manage billing →
        </button>
      </div>
    );
  }

  if (error || !billing) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ fontSize: 12, color: "var(--muted)" }}>
          Billing info unavailable
        </div>
        <div>
          <button
            onClick={onRetry}
            style={{
              background: "transparent",
              border: "none",
              padding: 0,
              fontSize: 12,
              color: "var(--cyan)",
              textDecoration: "underline",
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
        <button
          className="btn"
          disabled
          aria-disabled="true"
          title="Coming soon — self-serve billing ships in Phase 8"
          style={{ opacity: 0.6, cursor: "not-allowed", alignSelf: "flex-start" }}
        >
          Manage billing →
        </button>
      </div>
    );
  }

  const planKey = (billing.plan || "free").toLowerCase();
  const planLabel =
    planKey.charAt(0).toUpperCase() + planKey.slice(1); // "Free" | "Cloud" | "Teams"
  const isFree = planKey === "free";
  const { label, dot } = statusDisplay(billing.status);

  const isTrialing = billing.status === "trialing" && !!billing.trial_ends_at;
  const row2 = isFree
    ? null
    : isTrialing
    ? (
        <div style={{ fontSize: 13, lineHeight: 1.5, color: "var(--amber)" }}>
          Trial ends: {formatDate(billing.trial_ends_at)}
        </div>
      )
    : billing.current_period_ends_at
    ? (
        <div style={{ fontSize: 13, lineHeight: 1.5, color: "var(--muted)" }}>
          Next billing: {formatDate(billing.current_period_ends_at)}
        </div>
      )
    : null;

  const ctaLabel = isFree ? "Upgrade to Cloud" : "Manage billing →";
  const ctaTitle = isFree
    ? "Coming soon — checkout ships in Phase 8"
    : "Coming soon — self-serve billing ships in Phase 8";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Row 1: plan+price (left) + status pill (right) */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 8,
        }}
      >
        <div style={{ fontSize: 13, lineHeight: 1.5 }}>
          <span style={{ fontWeight: 600, color: "var(--text)" }}>{planLabel}</span>
          <span style={{ color: "var(--text)" }}> · </span>
          <span style={{ fontWeight: 600, color: "var(--text)" }}>
            {isFree ? "$0" : formatPrice(billing.price_cents, billing.currency)}
          </span>
        </div>
        <span
          aria-label={`Subscription status: ${label}`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            height: 24,
            padding: "0 8px",
            background: "var(--bg3)",
            border: "1px solid var(--border)",
            borderRadius: 999,
            fontSize: 10,
            fontWeight: 600,
            lineHeight: 1,
            color: "var(--text)",
          }}
        >
          <span aria-hidden="true" style={{ color: dot }}>●</span>
          {label}
        </span>
      </div>
      {/* Row 2: next billing OR trial ends OR (hidden for free) */}
      {row2}
      {/* Row 3: disabled CTA */}
      <button
        className="btn"
        disabled
        aria-disabled="true"
        title={ctaTitle}
        style={{ opacity: 0.6, cursor: "not-allowed", alignSelf: "flex-start" }}
      >
        {ctaLabel}
      </button>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Shell>
      <SettingsContent />
    </Shell>
  );
}

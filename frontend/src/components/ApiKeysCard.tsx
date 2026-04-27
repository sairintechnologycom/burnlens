"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch, AuthError, PaymentRequiredError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import { useBilling } from "@/lib/contexts/BillingContext";
import { usePaddleCheckout } from "@/lib/hooks/usePaddleCheckout";
import { nextPlanFor } from "@/lib/hooks/usePlanSatisfies";
import NewApiKeyModal from "@/components/NewApiKeyModal";
import EmptyState from "@/components/EmptyState";

// Phase 10 Plan 04 — Settings → API Keys card.
//
// Substantive contracts (all enforced by SUMMARY grep checks):
// - Plaintext-once (D-24): the freshly minted API key plaintext lives
//   ONLY in this component's plaintextKey state cell while the modal is
//   mounted. dismissPlaintext() sets it back to null. No off-state stash,
//   no global writes, no persistent storage, no diagnostic output.
// - Pre-emptive at-cap (D-26): the Create-key header button is disabled
//   BEFORE any 402 is seen, by reading
//   billing.api_keys.{active_count, limit} (Plan 10-01 backend wiring).
// - Plan-derivation (D-26): the cap-banner upgrade target is derived from
//   the nextPlanFor helper when the 402 lacks an explicit required_plan.
//   Cloud user gets Teams CTA, never Cloud.
// - Typed-name revoke confirm (D-25): exact, case-sensitive equality
//   between the input and the key name — no trim, no lowercase.

interface ApiKeyRow {
  id: string;
  name: string;
  last4: string;
  created_at: string;
  revoked_at?: string | null;
}

interface CapInfo {
  limit: number;
  required_plan: string;
}

function isActive(k: ApiKeyRow): boolean {
  return !k.revoked_at;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

export default function ApiKeysCard() {
  const { session, logout } = useAuth();
  const { billing } = useBilling();
  const { startCheckout } = usePaddleCheckout();

  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [nameInput, setNameInput] = useState("");

  // Plaintext lives ONLY in this state cell, ONLY while the modal is open.
  // dismissPlaintext() resets it to null. See file-header contract.
  const [plaintextKey, setPlaintextKey] = useState<string | null>(null);

  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [revokeConfirmText, setRevokeConfirmText] = useState("");
  const [revokingInFlight, setRevokingInFlight] = useState(false);
  const [capFromError, setCapFromError] = useState<CapInfo | null>(null);

  // D-26 / Blocker #2: pre-emptive at-cap. Read directly from
  // billing.api_keys (Plan 10-01 surfaced this on /billing/summary). The
  // 402 path still sets `capFromError` as a defensive race fallback for
  // the "another tab created a key first" case.
  const cap: CapInfo | null = useMemo(() => {
    if (capFromError) return capFromError;
    const ak = billing?.api_keys;
    if (!ak || ak.limit == null) return null; // unlimited or not loaded
    const requiredPlan = nextPlanFor(billing?.plan);
    if (!requiredPlan) return null; // top tier — no upsell banner
    return { limit: ak.limit, required_plan: requiredPlan };
  }, [billing?.api_keys, billing?.plan, capFromError]);

  // Active count: prefer the backend-derived count from billing.api_keys
  // when available (consistent with what the cap was computed against);
  // fall back to local rows.
  const activeCount =
    billing?.api_keys?.active_count ?? keys.filter(isActive).length;
  const atCap = cap !== null && activeCount >= cap.limit;

  const fetchKeys = useCallback(async () => {
    if (!session?.token) return;
    setLoading(true);
    setError(null);
    try {
      const rows = (await apiFetch("/api-keys", session.token)) as ApiKeyRow[];
      // D-28: most-recently-created first, active+revoked intermixed.
      setKeys([...rows].sort((a, b) => b.created_at.localeCompare(a.created_at)));
    } catch (e) {
      if (e instanceof AuthError) {
        logout();
        return;
      }
      setError("Failed to load API keys.");
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const handleCreate = async () => {
    if (!session?.token) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = (await apiFetch("/api-keys", session.token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nameInput || undefined }),
      })) as { id: string; name: string; key: string; last4: string; created_at: string };
      // ↓ plaintext stays in this single state cell only until modal dismiss.
      setPlaintextKey(created.key);
      setShowCreate(false);
      setNameInput("");
      await fetchKeys();
    } catch (e) {
      if (e instanceof AuthError) {
        logout();
        return;
      }
      if (e instanceof PaymentRequiredError) {
        // D-26 / Blocker #1 race-condition fallback:
        //   1. Prefer 402 body's required_plan when present.
        //   2. Else derive via nextPlanFor(billing.plan) — Cloud→Teams,
        //      Free→Cloud, Teams→null.
        //   Never blindly default to "cloud".
        const fallback = nextPlanFor(billing?.plan);
        const requiredPlan = (e.data.required_plan as string | undefined) ?? fallback;
        if (requiredPlan) {
          setCapFromError({
            limit: (e.data.limit as number | undefined) ?? 0,
            required_plan: requiredPlan,
          });
        }
        // If both 402 and fallback are absent (Teams user — top tier),
        // leave capFromError null and surface a generic error.
        setCreateError(
          requiredPlan
            ? "API key limit reached — refresh to see your keys"
            : "API key limit reached — contact support.",
        );
        await fetchKeys();
        return;
      }
      setCreateError("Failed to create key. Please try again.");
    } finally {
      setCreating(false);
    }
  };

  const handleRevokeConfirm = async (id: string) => {
    if (!session?.token) return;
    setRevokingInFlight(true);
    try {
      await apiFetch(`/api-keys/${encodeURIComponent(id)}`, session.token, {
        method: "DELETE",
      });
      setRevokingId(null);
      setRevokeConfirmText("");
      await fetchKeys();
    } catch (e) {
      if (e instanceof AuthError) {
        logout();
        return;
      }
      setError("Failed to revoke key. Please try again.");
    } finally {
      setRevokingInFlight(false);
    }
  };

  // Clears plaintext from React state — the only path that ends the
  // modal's lifetime. Mirror state lifecycle in NewApiKeyModal invariants.
  const dismissPlaintext = () => setPlaintextKey(null);

  const planLabel = billing?.plan
    ? billing.plan.charAt(0).toUpperCase() + billing.plan.slice(1)
    : "Free";

  const capPlanCap = cap?.required_plan ?? "";
  const capPlanLabel = capPlanCap
    ? capPlanCap.charAt(0).toUpperCase() + capPlanCap.slice(1)
    : "";

  return (
    <div className="card api-keys-card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title" style={{ fontWeight: 600 }}>
          API Keys
        </span>
        <button
          className="btn btn-cyan"
          onClick={() => setShowCreate(true)}
          disabled={atCap}
          type="button"
        >
          Create key
        </button>
      </div>

      {atCap && cap && (
        <div className="api-keys-cap-banner" role="status">
          <span>{`Your ${planLabel} plan allows ${cap.limit} API keys. Upgrade to ${capPlanLabel} for more.`}</span>
          <button
            className="btn btn-cyan"
            onClick={() => {
              if (
                cap.required_plan === "cloud" ||
                cap.required_plan === "teams"
              ) {
                startCheckout({ plan: cap.required_plan });
              }
            }}
            type="button"
          >
            Upgrade to {capPlanLabel}
          </button>
        </div>
      )}

      {loading && (
        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 8 }}>
          <div className="skeleton" style={{ height: 32, borderRadius: 4 }} />
          <div className="skeleton" style={{ height: 32, borderRadius: 4 }} />
          <div className="skeleton" style={{ height: 32, borderRadius: 4 }} />
        </div>
      )}

      {!loading && error && (
        <div style={{ padding: 16, fontSize: 13, color: "var(--muted)" }}>
          {error}{" "}
          <button
            onClick={fetchKeys}
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
      )}

      {!loading && !error && keys.length === 0 && (
        <div style={{ padding: 16 }}>
          <EmptyState
            title="No API keys yet."
            description="Create your first key to start syncing to cloud."
            action={{
              label: "Create key",
              onClick: () => {
                if (!atCap) setShowCreate(true);
              },
            }}
          />
        </div>
      )}

      {!loading && !error && keys.length > 0 && (
        <div style={{ overflowX: "auto", padding: "0 16px 16px" }}>
          <table
            className="api-keys-table"
            style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
          >
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted)", fontSize: 12 }}>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Name</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Last 4</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Created</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Status</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "10px 12px" }}>{k.name}</td>
                  <td style={{ padding: "10px 12px" }}>
                    <span className="api-keys-last4">····{k.last4}</span>
                  </td>
                  <td style={{ padding: "10px 12px" }}>{formatDate(k.created_at)}</td>
                  <td style={{ padding: "10px 12px" }}>
                    {isActive(k) ? (
                      <span className="api-keys-status-active">Active</span>
                    ) : (
                      <span className="api-keys-status-revoked">
                        Revoked {k.revoked_at ? formatDate(k.revoked_at) : ""}
                      </span>
                    )}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    {isActive(k) && revokingId !== k.id && (
                      <button
                        className="btn btn-red"
                        onClick={() => {
                          setRevokingId(k.id);
                          setRevokeConfirmText("");
                        }}
                        type="button"
                      >
                        Revoke
                      </button>
                    )}
                    {isActive(k) && revokingId === k.id && (
                      <div className="api-keys-revoke-form">
                        <input
                          className="form-input api-keys-revoke-input"
                          placeholder={`Type ${k.name} to confirm`}
                          value={revokeConfirmText}
                          onChange={(e) => setRevokeConfirmText(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && revokeConfirmText === k.name) {
                              handleRevokeConfirm(k.id);
                            }
                            if (e.key === "Escape") {
                              setRevokingId(null);
                              setRevokeConfirmText("");
                            }
                          }}
                          autoFocus
                          aria-label="Type key name to confirm revocation"
                        />
                        <button
                          className="btn btn-red"
                          disabled={revokeConfirmText !== k.name || revokingInFlight}
                          onClick={() => handleRevokeConfirm(k.id)}
                          type="button"
                        >
                          {revokingInFlight ? "Revoking…" : "Confirm"}
                        </button>
                        <button
                          className="btn"
                          onClick={() => {
                            setRevokingId(null);
                            setRevokeConfirmText("");
                          }}
                          type="button"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create-key inline modal (D-23). NOT blocking — cancel/Escape OK. */}
      {showCreate && (
        <div
          className="api-key-modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowCreate(false);
          }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="ak-create-title"
        >
          <div className="api-key-modal-card">
            <h2 id="ak-create-title" className="api-key-modal-title">
              Create API key
            </h2>
            <label className="form-label">Name</label>
            <input
              className="form-input"
              placeholder="Primary"
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
                if (e.key === "Escape") setShowCreate(false);
              }}
              autoFocus
            />
            {createError && (
              <div
                className="error-inline"
                style={{ marginTop: 8, fontFamily: "var(--font-sans)", fontSize: 12 }}
              >
                {createError}
              </div>
            )}
            <div className="api-key-modal-actions" style={{ marginTop: 16 }}>
              <button
                className="btn"
                onClick={() => setShowCreate(false)}
                type="button"
              >
                Cancel
              </button>
              <button
                className="btn btn-cyan"
                onClick={handleCreate}
                disabled={creating}
                type="button"
              >
                {creating ? "Creating…" : "Create key"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Plaintext reveal — blocking modal (D-24). Three-prop signature only. */}
      {plaintextKey && (
        <NewApiKeyModal
          open={true}
          plaintextKey={plaintextKey}
          onDismiss={dismissPlaintext}
        />
      )}
    </div>
  );
}

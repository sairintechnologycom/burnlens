"use client";
import { useCallback, useEffect, useState } from "react";

import ApiKeysTable, { ApiKeyRow } from "@/components/ApiKeysTable";
import EmptyState from "@/components/EmptyState";
import NewApiKeyModal from "@/components/NewApiKeyModal";
import RevokeKeyModal from "@/components/RevokeKeyModal";
import Shell from "@/components/Shell";
import { apiFetch, AuthError, PaymentRequiredError } from "@/lib/api";
import { useToast } from "@/lib/contexts/ToastContext";
import { useAuth } from "@/lib/hooks/useAuth";

interface CreateKeyResponse extends ApiKeyRow {
  key: string;
}

function ApiKeysContent() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newKeyPlaintext, setNewKeyPlaintext] = useState<string | null>(null);
  const [pendingRevoke, setPendingRevoke] = useState<ApiKeyRow | null>(null);
  const [newKeyName, setNewKeyName] = useState("");

  useEffect(() => {
    document.title = "API Keys | BurnLens";
  }, []);

  const fetchKeys = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch("/account/api-keys", session.token);
      setKeys(Array.isArray(data) ? data : []);
    } catch (err: unknown) {
      if (err instanceof AuthError) logout();
      else
        setError(
          err instanceof Error ? err.message : "Failed to load keys."
        );
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const handleCreate = async () => {
    if (!session || creating) return;
    setCreating(true);
    try {
      const body = newKeyName.trim() ? { name: newKeyName.trim() } : {};
      const created = (await apiFetch("/account/api-keys", session.token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })) as CreateKeyResponse;
      setNewKeyPlaintext(created.key);
      setShowCreate(false);
      setNewKeyName("");
      // Refresh list so the new row appears (without the plaintext).
      fetchKeys();
    } catch (err: unknown) {
      if (err instanceof AuthError) {
        logout();
      } else if (err instanceof PaymentRequiredError) {
        showToast(
          "API key limit reached — upgrade your plan to add more.",
          "error"
        );
      } else {
        showToast("Failed to create key.", "error");
      }
    } finally {
      setCreating(false);
    }
  };

  const handleSaveLabel = async (id: string, newName: string) => {
    if (!session) return;
    const prev = keys.find((k) => k.id === id);
    if (!prev) return;
    setKeys((ks) =>
      ks.map((k) => (k.id === id ? { ...k, name: newName } : k))
    );
    try {
      await apiFetch(`/account/api-keys/${id}`, session.token, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName }),
      });
      showToast("Label updated", "success");
    } catch (err: unknown) {
      setKeys((ks) => ks.map((k) => (k.id === id ? prev : k)));
      if (err instanceof AuthError) logout();
      else showToast("Failed to update label.", "error");
    }
  };

  const handleConfirmRevoke = async () => {
    if (!session || !pendingRevoke) return;
    const target = pendingRevoke;
    try {
      await apiFetch(`/account/api-keys/${target.id}`, session.token, {
        method: "DELETE",
      });
      // Optimistic update: mark this row revoked locally.
      setKeys((ks) =>
        ks.map((k) =>
          k.id === target.id
            ? { ...k, revoked_at: new Date().toISOString() }
            : k
        )
      );
      showToast("Key revoked", "success");
      setPendingRevoke(null);
    } catch (err: unknown) {
      if (err instanceof AuthError) logout();
      else showToast("Failed to revoke key. Please try again.", "error");
      // Keep modal open so user sees the toast and can retry.
    }
  };

  const handlePause = async (key: ApiKeyRow) => {
    if (!session) return;
    try {
      const updated = await apiFetch(`/account/api-keys/${key.id}/pause`, session.token, {
        method: "POST",
      }) as ApiKeyRow;
      setKeys((ks) => ks.map((k) => (k.id === key.id ? updated : k)));
      showToast("Key paused", "success");
    } catch (err: unknown) {
      if (err instanceof AuthError) logout();
      else showToast("Failed to pause key.", "error");
    }
  };

  const handleResume = async (key: ApiKeyRow) => {
    if (!session) return;
    try {
      const updated = await apiFetch(`/account/api-keys/${key.id}/resume`, session.token, {
        method: "POST",
      }) as ApiKeyRow;
      setKeys((ks) => ks.map((k) => (k.id === key.id ? updated : k)));
      showToast("Key resumed", "success");
    } catch (err: unknown) {
      if (err instanceof AuthError) logout();
      else showToast("Failed to resume key.", "error");
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <div className="card">
          <div className="skeleton" style={{ height: 40, marginBottom: 8 }} />
          <div className="skeleton" style={{ height: 40 }} />
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        padding: 24,
        display: "flex",
        flexDirection: "column",
        gap: 24,
      }}
    >
      <div
        className="section-header"
        style={{ paddingLeft: 20, paddingRight: 20 }}
      >
        <div>
          <h1 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>
            API Keys
          </h1>
          <p style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
            Workspace keys for syncing the BurnLens proxy and ingesting usage
            from your apps.
          </p>
        </div>
        <button
          className="btn btn-cyan"
          onClick={() => setShowCreate(true)}
          type="button"
        >
          Create key
        </button>
      </div>

      {error && (
        <div style={{ padding: "0 24px" }}>
          <span
            className="error-inline"
            onClick={fetchKeys}
            style={{ cursor: "pointer" }}
            role="button"
          >
            Failed to load keys. Retry →
          </span>
        </div>
      )}

      <div className="card">
        {keys.length === 0 ? (
          <EmptyState
            title="No API keys yet."
            description="Create your first key to start syncing to cloud."
            action={{
              label: "Create key",
              onClick: () => setShowCreate(true),
            }}
          />
        ) : (
          <ApiKeysTable
            keys={keys}
            onRequestRevoke={(k) => setPendingRevoke(k)}
            onPause={handlePause}
            onResume={handleResume}
            onSaveLabel={handleSaveLabel}
            canMutateRow={() => true /* server enforces role/creator scoping */}
          />
        )}
      </div>

      {/* Create-key modal — lightweight; plaintext display happens in NewApiKeyModal after success */}
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
            <h2
              id="ak-create-title"
              className="api-key-modal-title"
              style={{ fontSize: 16, fontWeight: 600 }}
            >
              Create new key
            </h2>
            <input
              className="form-input"
              placeholder="Label or note"
              value={newKeyName}
              maxLength={128}
              onChange={(e) => setNewKeyName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
                if (e.key === "Escape") setShowCreate(false);
              }}
              autoFocus
              style={{ marginTop: 12, width: "100%" }}
            />
            <div
              className="api-key-modal-actions"
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 16,
              }}
            >
              <button
                className="btn"
                onClick={() => setShowCreate(false)}
                disabled={creating}
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

      <NewApiKeyModal
        open={newKeyPlaintext !== null}
        plaintextKey={newKeyPlaintext ?? ""}
        onDismiss={() => setNewKeyPlaintext(null)}
      />

      <RevokeKeyModal
        open={pendingRevoke !== null}
        keyName={pendingRevoke?.name ?? ""}
        last4={pendingRevoke?.last4 ?? ""}
        onCancel={() => setPendingRevoke(null)}
        onConfirm={handleConfirmRevoke}
      />
    </div>
  );
}

export default function ApiKeysPage() {
  return (
    <Shell>
      <ApiKeysContent />
    </Shell>
  );
}

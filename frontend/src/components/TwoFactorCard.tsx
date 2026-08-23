"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";

// Settings → Two-factor authentication.
//
// Three contracts worth stating, because each is a way this UI could quietly
// lock a user out of their own account:
//
// - Recovery codes are returned by /auth/2fa/confirm exactly once and are
//   stored hashed server-side. They live only in this component's state and
//   cannot be re-fetched. The panel therefore refuses to dismiss them until
//   the user explicitly confirms they have been saved.
// - `enabled` and `pending` are distinct. A secret exists from the moment
//   setup starts, so a half-finished enrollment must render as "finish setup",
//   never as "2FA is on" — the login path only challenges on `enabled`.
// - Disabling requires the password AND a current code, mirroring the backend.
//   The form collects both rather than letting a live session switch it off.

interface TotpStatus {
  enabled: boolean;
  pending: boolean;
  recovery_codes_remaining: number;
}

interface SetupPayload {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

export default function TwoFactorCard() {
  const { session, logout } = useAuth();

  const [status, setStatus] = useState<TotpStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [setupData, setSetupData] = useState<SetupPayload | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [savedAcknowledged, setSavedAcknowledged] = useState(false);

  const [showDisable, setShowDisable] = useState(false);
  const [disablePassword, setDisablePassword] = useState("");
  const [disableCode, setDisableCode] = useState("");

  const refresh = useCallback(async () => {
    if (!session) return;
    try {
      setStatus((await apiFetch("/auth/2fa/status", session.token)) as TotpStatus);
      setError("");
    } catch (err) {
      if (err instanceof AuthError) logout();
      else setError(err instanceof Error ? err.message : "Failed to load 2FA status");
    } finally {
      setLoading(false);
    }
  }, [session, logout]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const startSetup = useCallback(async () => {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      setSetupData(
        (await apiFetch("/auth/2fa/setup", session.token, { method: "POST" })) as SetupPayload,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start setup");
    } finally {
      setBusy(false);
    }
  }, [session]);

  const confirmSetup = useCallback(async () => {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      const res = (await apiFetch("/auth/2fa/confirm", session.token, {
        method: "POST",
        body: JSON.stringify({ code: confirmCode }),
      })) as { enabled: boolean; recovery_codes: string[] };
      setRecoveryCodes(res.recovery_codes);
      setSetupData(null);
      setConfirmCode("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not enable 2FA");
    } finally {
      setBusy(false);
    }
  }, [session, confirmCode, refresh]);

  const disable = useCallback(async () => {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      await apiFetch("/auth/2fa/disable", session.token, {
        method: "POST",
        body: JSON.stringify({ password: disablePassword, code: disableCode }),
      });
      setShowDisable(false);
      setDisablePassword("");
      setDisableCode("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disable 2FA");
    } finally {
      setBusy(false);
    }
  }, [session, disablePassword, disableCode, refresh]);

  if (loading) return <div className="skeleton" style={{ height: 160 }} />;

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-header">
        <h2 className="card-title">Two-factor authentication</h2>
        {status?.enabled && <span className="badge badge-ok">Enabled</span>}
      </div>

      {error && (
        <div role="alert" className="error-banner" style={{ marginBottom: 12 }}>
          {error}
        </div>
      )}

      {/* Recovery codes: shown once, never retrievable again. */}
      {recoveryCodes && (
        <div style={{ marginBottom: 16 }}>
          <p style={{ fontWeight: 600, marginBottom: 4 }}>Save your recovery codes</p>
          <p style={{ fontSize: "var(--fs-13)", color: "var(--s-muted)", marginBottom: 8 }}>
            Each code works once, and this is the only time they are shown. Store them
            somewhere you can reach without your phone.
          </p>
          <pre
            style={{
              background: "var(--bg3)",
              padding: 12,
              borderRadius: 6,
              fontFamily: "monospace",
              lineHeight: 1.8,
              overflowX: "auto",
            }}
          >
            {recoveryCodes.join("\n")}
          </pre>
          <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <input
              type="checkbox"
              checked={savedAcknowledged}
              onChange={(e) => setSavedAcknowledged(e.target.checked)}
            />
            <span style={{ fontSize: "var(--fs-13)" }}>I have saved these codes</span>
          </label>
          <button
            className="btn btn-primary"
            style={{ marginTop: 8 }}
            disabled={!savedAcknowledged}
            onClick={() => {
              setRecoveryCodes(null);
              setSavedAcknowledged(false);
            }}
          >
            Done
          </button>
        </div>
      )}

      {/* Enrollment in progress. */}
      {setupData && !recoveryCodes && (
        <div>
          <p style={{ marginBottom: 8 }}>
            Scan this with your authenticator app, then enter the 6-digit code it shows.
          </p>
          <div
            style={{ width: 180, height: 180, background: "#fff", padding: 8, borderRadius: 6 }}
            /* The SVG is generated server-side from the otpauth URI we just
               requested — not user input — so there is no untrusted markup here. */
            dangerouslySetInnerHTML={{ __html: setupData.qr_svg }}
          />
          <p style={{ fontSize: "var(--fs-13)", color: "var(--s-muted)", marginTop: 8 }}>
            Can&apos;t scan? Enter this key manually:{" "}
            <code style={{ userSelect: "all" }}>{setupData.secret}</code>
          </p>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input
              className="input"
              placeholder="123456"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={confirmCode}
              onChange={(e) => setConfirmCode(e.target.value)}
            />
            <button
              className="btn btn-primary"
              onClick={confirmSetup}
              disabled={busy || confirmCode.length < 6}
            >
              {busy ? "Verifying..." : "Enable"}
            </button>
            <button className="btn" onClick={() => setSetupData(null)} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Steady states. */}
      {!setupData && !recoveryCodes && (
        <>
          {status?.enabled ? (
            <>
              <p style={{ color: "var(--s-muted)", fontSize: "var(--fs-13)" }}>
                Your account asks for a code from your authenticator app at sign-in.{" "}
                {status.recovery_codes_remaining} recovery{" "}
                {status.recovery_codes_remaining === 1 ? "code" : "codes"} remaining.
              </p>
              {!showDisable ? (
                <button
                  className="btn"
                  style={{ marginTop: 12 }}
                  onClick={() => setShowDisable(true)}
                >
                  Disable
                </button>
              ) : (
                <div style={{ marginTop: 12 }}>
                  <p style={{ fontSize: "var(--fs-13)", marginBottom: 8 }}>
                    Confirm with your password and a current code.
                  </p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <input
                      className="input"
                      type="password"
                      placeholder="Password"
                      autoComplete="current-password"
                      value={disablePassword}
                      onChange={(e) => setDisablePassword(e.target.value)}
                    />
                    <input
                      className="input"
                      placeholder="123456"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      value={disableCode}
                      onChange={(e) => setDisableCode(e.target.value)}
                    />
                    <button
                      className="btn btn-danger"
                      onClick={disable}
                      disabled={busy || !disablePassword || !disableCode}
                    >
                      {busy ? "Disabling..." : "Confirm disable"}
                    </button>
                    <button className="btn" onClick={() => setShowDisable(false)} disabled={busy}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <p style={{ color: "var(--s-muted)", fontSize: "var(--fs-13)" }}>
                {status?.pending
                  ? "You started setting up 2FA but never confirmed it. Start again to finish."
                  : "Add a second step at sign-in using an authenticator app."}
              </p>
              <button
                className="btn btn-primary"
                style={{ marginTop: 12 }}
                onClick={startSetup}
                disabled={busy}
              >
                {busy ? "Preparing..." : status?.pending ? "Restart setup" : "Set up 2FA"}
              </button>
            </>
          )}
        </>
      )}
    </section>
  );
}

"use client";

import { useState } from "react";

import { apiFetch, AuthError } from "@/lib/api";
import { useAuth } from "@/lib/hooks/useAuth";
import type { BillingSummary } from "@/lib/contexts/BillingContext";
import { useToast } from "@/lib/contexts/ToastContext";

type Props = {
  open: boolean;
  planLabel: string; // "Cloud" | "Teams"
  currentPeriodEndsAt: string | null; // ISO — may be null (edge: sub with no end date)
  onClose: () => void;
  onSuccess: (next: BillingSummary) => void;
};

// D-10 exact labels — DO NOT reword.
const REASON_OPTIONS: { value: string; label: string }[] = [
  { value: "too_expensive", label: "Too expensive" },
  { value: "missing_feature", label: "Missing a feature" },
  { value: "switching_tools", label: "Switching tools" },
  { value: "not_using_enough", label: "Not using it enough" },
  { value: "other", label: "Other" },
];

function formatDate(iso: string | null): string {
  if (!iso) return "your next billing date";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "your next billing date";
  }
}

export default function CancelSubscriptionModal({
  open,
  planLabel,
  currentPeriodEndsAt,
  onClose,
  onSuccess,
}: Props) {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [reasonCode, setReasonCode] = useState<string | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const endDate = formatDate(currentPeriodEndsAt);

  const handleConfirm = async () => {
    if (!session || submitting) return; // D-31 double-submit guard
    setSubmitting(true);
    try {
      const payload: Record<string, string | null> = {};
      if (reasonCode) payload.reason_code = reasonCode;
      if (reasonText.trim().length > 0) payload.reason_text = reasonText.trim();

      const next = (await apiFetch("/billing/cancel", session.token, {
        method: "POST",
        body: JSON.stringify(payload),
      })) as BillingSummary;

      // Success toast wording is Claude's-discretion within D-28's pattern.
      showToast(
        "Subscription canceled — access continues until period end",
        "success",
      );
      onSuccess(next);
    } catch (err: any) {
      if (err instanceof AuthError) {
        logout();
        return;
      }
      // D-28 exact toast copy — MUST include the literal string "support@burnlens.app".
      showToast(
        "Couldn't cancel subscription — our billing provider didn't respond. Try again in a moment; if it persists, email support@burnlens.app.",
        "error",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="cancel-modal-title"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={(e) => {
        // backdrop click = close (but not while submitting)
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div
        className="card"
        style={{ width: 480, maxWidth: "94vw", padding: 0 }}
      >
        <div className="section-header">
          <span
            id="cancel-modal-title"
            className="section-header-title"
            style={{ fontWeight: 600 }}
          >
            Cancel subscription
          </span>
        </div>
        <div
          style={{
            padding: 18,
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          {/* D-08 exact body copy */}
          <div style={{ fontSize: 13, lineHeight: 1.5 }}>
            You&apos;ll keep {planLabel} until {endDate}. After that, your
            workspace will switch to the Free plan.
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <label className="form-label">
              Why are you canceling? (optional)
            </label>
            {REASON_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                <input
                  type="radio"
                  name="cancel-reason"
                  value={opt.value}
                  checked={reasonCode === opt.value}
                  onChange={() => setReasonCode(opt.value)}
                  disabled={submitting}
                />
                {opt.label}
              </label>
            ))}
            <textarea
              className="form-input"
              placeholder="Anything else? (optional)"
              value={reasonText}
              onChange={(e) => setReasonText(e.target.value)}
              disabled={submitting}
              rows={3}
              style={{ fontFamily: "var(--font-sans)", resize: "vertical" }}
            />
          </div>

          <div
            style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}
          >
            <button
              className="btn"
              onClick={onClose}
              disabled={submitting}
            >
              Keep subscription
            </button>
            <button
              className="btn btn-red"
              onClick={handleConfirm}
              disabled={submitting}
            >
              {submitting ? "Canceling…" : "Confirm cancel"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

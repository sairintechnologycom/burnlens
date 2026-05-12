"use client";
import { useEffect, useRef, useState } from "react";

interface RevokeKeyModalProps {
  open: boolean;
  keyName: string;
  last4: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}

export default function RevokeKeyModal({
  open,
  keyName,
  last4,
  onCancel,
  onConfirm,
}: RevokeKeyModalProps) {
  const cancelBtnRef = useRef<HTMLButtonElement>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setSubmitting(false);
      cancelBtnRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, submitting, onCancel]);

  if (!open) return null;

  const handleConfirm = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      await onConfirm();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="api-key-modal-backdrop"
      onClick={(e) => {
        if (!submitting && e.target === e.currentTarget) onCancel();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="rkm-title"
    >
      <div
        className="api-key-modal-card"
        style={{ width: "clamp(360px, 480px, 90vw)" }}
      >
        <h2
          id="rkm-title"
          className="api-key-modal-title"
          style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}
        >
          Revoke &quot;{keyName}&quot;{" "}
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--muted)" }}>
            (…{last4})
          </span>
          ?
        </h2>
        <p
          style={{
            fontSize: 13,
            color: "var(--muted)",
            marginBottom: 16,
            lineHeight: 1.5,
          }}
        >
          This key will stop working immediately. Apps using it will get 401
          errors until you create a new key.
        </p>
        <div
          className="api-key-modal-actions"
          style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}
        >
          <button
            ref={cancelBtnRef}
            className="btn"
            onClick={onCancel}
            disabled={submitting}
            type="button"
          >
            Keep key
          </button>
          <button
            className="btn btn-red"
            onClick={handleConfirm}
            disabled={submitting}
            type="button"
          >
            {submitting ? "Revoking…" : "Revoke key"}
          </button>
        </div>
      </div>
    </div>
  );
}

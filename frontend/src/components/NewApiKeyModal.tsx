"use client";

import { useEffect, useRef, useState } from "react";

// Phase 10 Plan 04 — Blocking modal that displays a freshly-minted API key
// plaintext exactly once (D-24). Backed by Phase 9 D-13 contract: plaintext
// is emitted once at create time and is never re-fetched.
//
// Contract invariants (T-10-17 / T-10-18 / Blocker #4 — see SUMMARY):
// - props are exactly three; the deprecated name prop is intentionally absent.
// - plaintextKey arrives as a prop reference and is rendered as a React text
//   child inside the code element (auto-escaped). Never set via raw-HTML.
// - No off-state stash; no global writes; no persistent storage.
// - No diagnostic output; plaintext must NEVER reach any logging pipeline.
// - Backdrop click does NOT close. The Esc key does NOT close. The only
//   dismissal path is the primary action button — blocking by design.
// - Parent owns the plaintext in state and clears it via onDismiss.

interface NewApiKeyModalProps {
  open: boolean;
  plaintextKey: string;
  onDismiss: () => void;
}

export default function NewApiKeyModal({
  open,
  plaintextKey,
  onDismiss,
}: NewApiKeyModalProps) {
  const [copied, setCopied] = useState(false);
  const dismissBtnRef = useRef<HTMLButtonElement>(null);

  // Focus the primary dismiss button on mount so SR users land on the
  // dismiss path, and so Enter from anywhere completes the flow.
  useEffect(() => {
    if (open) dismissBtnRef.current?.focus();
  }, [open]);

  // BLOCKING by design — see file-header contract invariants.

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(plaintextKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard may be blocked (http origin / permissions). Fail silently
      // — user can still select/copy the visible <code> text. T-10-25 accept.
    }
  };

  if (!open) return null;

  return (
    <div
      className="api-key-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="nak-title"
    >
      <div className="api-key-modal-card">
        <h2 id="nak-title" className="api-key-modal-title">
          Your new key
        </h2>
        <div className="form-label" style={{ marginBottom: 4 }}>
          Key
        </div>
        <code
          className="api-key-plaintext"
          aria-label="Your new API key — copy it now"
        >
          {plaintextKey}
        </code>
        <button
          className="btn btn-cyan api-key-copy-btn"
          onClick={handleCopy}
          type="button"
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <p className="api-key-warning">
          {"You won't see this key again. Store it now in your password manager or secrets file."}
        </p>
        <div className="api-key-modal-actions">
          <button
            ref={dismissBtnRef}
            className="btn btn-cyan"
            onClick={onDismiss}
            type="button"
          >
            {"I've saved it"}
          </button>
        </div>
      </div>
    </div>
  );
}

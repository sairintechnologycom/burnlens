"use client";

import { useState } from "react";
import { trackEvent } from "@/lib/analytics";

type Props = {
  /** The shell command, rendered inside <code> and copied to clipboard. */
  command: string;
  /** Plausible event name fired on successful copy. */
  eventName: string;
  /** Optional extra props attached to the analytics event. */
  eventProps?: Record<string, string>;
};

export function CopyCommand({ command, eventName, eventProps }: Props) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      trackEvent(eventName, eventProps);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // clipboard blocked — render still works as a normal code block
    }
  }

  return (
    <pre
      style={{
        position: "relative",
        background: "#0e1318",
        border: "1px solid #1e2830",
        padding: "1rem 1.25rem",
        borderRadius: 8,
        overflowX: "auto",
        fontSize: 13,
        lineHeight: 1.7,
      }}
    >
      <code>{command}</code>
      <button
        type="button"
        onClick={handleCopy}
        aria-label={copied ? "Copied" : "Copy command"}
        style={{
          position: "absolute",
          top: 8,
          right: 8,
          padding: "4px 10px",
          background: copied ? "#e07840" : "#131920",
          color: copied ? "#080c10" : "var(--muted, #6b7785)",
          border: "1px solid #1e2830",
          borderRadius: 4,
          fontFamily: "var(--font-mono), monospace",
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          cursor: "pointer",
        }}
      >
        {copied ? "copied" : "copy"}
      </button>
    </pre>
  );
}

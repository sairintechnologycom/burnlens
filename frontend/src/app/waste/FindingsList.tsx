import type { FindingItem } from "@/lib/contracts";

const ACTIONS: Record<string, [string, string][]> = {
  open: [
    ["acknowledged", "Acknowledge"],
    ["resolved", "Mark fixed"],
    ["accepted_risk", "Accept risk"],
  ],
  acknowledged: [
    ["resolved", "Mark fixed"],
    ["accepted_risk", "Accept risk"],
    ["open", "Reopen"],
  ],
  resolved: [["open", "Reopen"]],
  accepted_risk: [["open", "Reopen"]],
};

function formatUsd(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function FindingsList({
  findings,
  onStatus,
  pendingId,
}: {
  findings: FindingItem[];
  onStatus?: (fingerprint: string, status: string) => void;
  pendingId?: string | null;
}) {
  if (findings.length === 0) {
    return (
      <div className="empty-state" data-testid="findings-empty">
        No waste findings in this view.
      </div>
    );
  }

  return (
    <div>
      {findings.map((f) => (
        <article
          key={f.id}
          data-testid="finding-row"
          style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span className={`severity-badge severity-${f.severity}`}>{f.severity}</span>
            <span
              style={{
                fontFamily: "var(--font-sans)",
                fontWeight: 600,
                fontSize: 13,
                color: "var(--text)",
              }}
            >
              {f.title}
            </span>
            <span className={`tag`} style={{ textTransform: "capitalize" }}>
              {f.status.replace("_", " ")}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
            {f.subject_type}: {f.subject_key}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6, lineHeight: 1.4 }}>
            {f.description}
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--amber)", marginBottom: 8 }}>
            ~${formatUsd(f.estimated_waste_usd)} estimated waste · {f.affected_count} request(s) · seen{" "}
            {f.detection_count}×
          </div>
          {Object.keys(f.evidence || {}).length > 0 && (
            <details style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>
              <summary style={{ cursor: "pointer" }}>Evidence</summary>
              <pre style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>
                {JSON.stringify(f.evidence, null, 2)}
              </pre>
            </details>
          )}
          <div style={{ display: "flex", gap: 6 }}>
            {(ACTIONS[f.status] || []).map(([next, label]) => (
              <button
                key={next}
                type="button"
                className="btn"
                style={{ padding: "2px 10px", fontSize: 10 }}
                disabled={pendingId === f.id}
                onClick={() => onStatus?.(f.id, next)}
              >
                {label}
              </button>
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}

import type { FindingItem, SavingsVerdict } from "@/lib/contracts";

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

function VerdictBlock({ verdict }: { verdict?: SavingsVerdict }) {
  if (!verdict) return null;
  const line = verdictLine(verdict);
  if (!line) return null;
  const isRegression = (verdict.projected_monthly_savings_usd ?? 0) < 0;
  return (
    <div
      data-testid="finding-verdict"
      style={{
        fontSize: 12,
        marginBottom: 8,
        color: isRegression ? "var(--red)" : "var(--green)",
      }}
    >
      {line}
    </div>
  );
}

export function verdictLine(v: SavingsVerdict): string | null {
  if (v.status === "pending") {
    const days = v.days_remaining ?? 0;
    return `Verifying — ${days.toFixed(1)} more days of data needed`;
  }
  if (v.status === "no_traffic") {
    return "No traffic since the fix — nothing can be concluded";
  }
  if (v.status === "no_baseline") {
    return "No baseline captured for this fix";
  }
  if (v.status !== "verified") return null;
  const before = v.baseline_cost_per_request ?? 0;
  const after = v.current_cost_per_request ?? 0;
  const proj = v.projected_monthly_savings_usd ?? 0;
  if (proj < 0) {
    return `Regression: $${before.toFixed(2)} → $${after.toFixed(2)} per request, projected $${Math.abs(proj).toFixed(2)}/month more`;
  }
  return `Fix verified: $${before.toFixed(2)} → $${after.toFixed(2)} per request, projected $${proj.toFixed(2)}/month`;
}

function formatUsd(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function FindingsList({
  findings,
  verdicts = {},
  onStatus,
  pendingId,
}: {
  findings: FindingItem[];
  verdicts?: Record<string, SavingsVerdict>;
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
          <VerdictBlock verdict={verdicts[f.id]} />
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

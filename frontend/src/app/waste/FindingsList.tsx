import { useState } from "react";
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
  const isRegression =
    (verdict.projected_monthly_savings_usd ?? 0) < 0 || verdict.outcome_quality === "degraded";
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
  if (v.status === "missed") {
    if (v.outcome_quality === "degraded") {
      const before = ((v.baseline_acceptance_rate ?? 0) * 100).toFixed(1);
      const after = ((v.current_acceptance_rate ?? 0) * 100).toFixed(1);
      return `Outcome quality degraded: accepted rate ${before}% → ${after}%; cost reduction is not counted`;
    }
    return "Cost per request did not fall; projected saving was not realised";
  }
  if (v.status !== "verified") return null;
  const before = v.baseline_cost_per_request ?? 0;
  const after = v.current_cost_per_request ?? 0;
  const proj = v.projected_monthly_savings_usd ?? 0;
  if (proj < 0) {
    return `Regression: $${before.toFixed(2)} → $${after.toFixed(2)} per request, projected $${Math.abs(proj).toFixed(2)}/month more`;
  }
  const quality = v.quality_qualified
    ? "; accepted rate preserved"
    : "; outcome quality unavailable";
  const label = v.quality_qualified ? "Quality-qualified reduction" : "Observed reduction";
  return `${label} (Fix verified): $${before.toFixed(2)} → $${after.toFixed(2)} per request, projected $${proj.toFixed(2)}/month${quality}`;
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
  onStatus?: (
    fingerprint: string,
    status: string,
    metadata?: {
      cohort_key?: string;
      change_reference?: string;
      change_type?: string;
      change_url?: string;
    },
  ) => void;
  pendingId?: string | null;
}) {
  const [metadata, setMetadata] = useState<Record<string, {
    cohort_key: string;
    change_reference: string;
    change_type: string;
    change_url: string;
  }>>({});
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
          {verdicts[f.id] && (
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>
              Cohort: {verdicts[f.id].cohort_key ?? "—"} · Change: {verdicts[f.id].change_reference ?? "not recorded"}
              {verdicts[f.id].change_type ? ` (${verdicts[f.id].change_type})` : ""}
              {verdicts[f.id].change_url ? " · evidence linked" : ""}
              {verdicts[f.id].comparison_rule === "same_subject_equal_windows" && " · same subject, equal windows"}
            </div>
          )}
          <details style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>
            <summary style={{ cursor: "pointer" }}>Verification metadata (optional)</summary>
            <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
              <label>
                Cohort key
                <input
                  className="input"
                  value={metadata[f.id]?.cohort_key ?? ""}
                  placeholder={`workflow:${f.subject_key}`}
                  onChange={(e) => setMetadata((current) => ({
                    ...current,
                    [f.id]: { ...current[f.id], cohort_key: e.target.value },
                  }))}
                />
              </label>
              <label>
                Change reference
                <input
                  className="input"
                  value={metadata[f.id]?.change_reference ?? ""}
                  placeholder="commit, deploy, or config revision"
                  onChange={(e) => setMetadata((current) => ({
                    ...current,
                    [f.id]: { ...current[f.id], change_reference: e.target.value },
                  }))}
                />
              </label>
              <label>
                Change type
                <input
                  className="input"
                  placeholder="commit, deploy, or config"
                  onChange={(e) => setMetadata((current) => ({
                    ...current,
                    [f.id]: { ...current[f.id], change_type: e.target.value },
                  }))}
                />
              </label>
              <label>
                Evidence URL
                <input
                  className="input"
                  type="url"
                  placeholder="https://..."
                  onChange={(e) => setMetadata((current) => ({
                    ...current,
                    [f.id]: { ...current[f.id], change_url: e.target.value },
                  }))}
                />
              </label>
            </div>
          </details>
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
                onClick={() => {
                  const values = metadata[f.id];
                  onStatus?.(f.id, next, next === "resolved" ? {
                    cohort_key: values?.cohort_key.trim() || undefined,
                    change_reference: values?.change_reference.trim() || undefined,
                    change_type: values?.change_type.trim() || undefined,
                    change_url: values?.change_url.trim() || undefined,
                  } : undefined);
                }}
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

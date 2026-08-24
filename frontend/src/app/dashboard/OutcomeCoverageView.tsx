import Link from "next/link";
import type { OutcomeCoverage } from "@/lib/contracts";
import { formatCost } from "@/lib/money";

// Dollar-weighted, unlike cost confidence — the question here is what share of
// the money bought something we can name. The three tiers must sum to the total
// or the bar is lying; the backend enforces that, this just renders it.
const COVERAGE_CLASSES = [
  { key: "cost_attributed_usd", label: "Linked to an outcome", color: "var(--green)",
    help: "An outcome was recorded for this spend inside the allocation window." },
  { key: "cost_unattributed_usd", label: "Tagged, no outcome", color: "var(--amber)",
    help: "The request carried a workflow_id but no outcome followed. Post the outcome and this moves." },
  { key: "cost_untagged_usd", label: "No workflow tag", color: "var(--red, #e5484d)",
    help: "No workflow_id on the request, so it can never be attributed. Cost-per-outcome is blind to this spend entirely." },
] as const;

export function OutcomeCoveragePanel({ c }: { c: OutcomeCoverage }) {
  if (c.cost_total_usd <= 0) return null;

  return (
    <div className="card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title">Outcome coverage</span>
        <span
          className="section-header-action"
          title="Share of spend, by dollar, that reaches a recorded business outcome."
        >
          {c.coverage_pct.toFixed(0)}%
        </span>
      </div>
      <div style={{ padding: 16 }}>
        <div
          role="img"
          aria-label={`Outcome coverage ${c.coverage_pct.toFixed(0)} percent of spend`}
          style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: "var(--bg3)" }}
        >
          {COVERAGE_CLASSES.map(({ key, label, color }) => {
            const pct = (c[key] / c.cost_total_usd) * 100;
            if (pct <= 0) return null;
            return <div key={key} title={`${label}: $${formatCost(c[key])}`}
                        style={{ width: `${pct}%`, background: color }} />;
          })}
        </div>

        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 14, fontSize: 13 }}>
          {COVERAGE_CLASSES.map(({ key, label, color, help }) => {
            if (c[key] <= 0) return null;
            return (
              <div key={key} title={help}>
                <div style={{ color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
                  {label}
                </div>
                <div style={{ color: "var(--text)", marginTop: 2 }}>${formatCost(c[key])}</div>
              </div>
            );
          })}
        </div>

        {c.cost_untagged_usd > 0 && (
          <div style={{ marginTop: 14, fontSize: 13, color: "var(--muted)", lineHeight: 1.6 }}>
            <span style={{ color: "var(--amber)" }}>⚠</span>{" "}
            <span style={{ color: "var(--text)" }}>${formatCost(c.cost_untagged_usd)}</span> of spend
            carries no <code>workflow_id</code> tag, so cost-per-outcome is computed
            without it. <Link href="/docs">Tagging guide</Link>
          </div>
        )}

        {c.by_workflow.length > 0 && (
          <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            {c.by_workflow.map((w, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, lineHeight: 1.9 }}>
                <span style={{ color: w.workflow_id ? "var(--text)" : "var(--dim)" }}>
                  {w.workflow_id ?? "untagged"}
                </span>
                <span style={{ color: "var(--muted)" }}>
                  ${formatCost(w.cost_total_usd)}
                  <span style={{ color: w.coverage_pct >= 90 ? "var(--green)" : "var(--amber)", marginLeft: 12 }}>
                    {w.coverage_pct.toFixed(0)}%
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

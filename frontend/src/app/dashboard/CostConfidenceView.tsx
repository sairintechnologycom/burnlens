import type { CostConfidence } from "@/lib/contracts";
import { formatCost } from "@/lib/money";

// Presentational half of the cost-confidence panel, split out (CacheView
// pattern) so the populated state is testable without hooks or fetches. An
// empty-state page is not a tested page: two dashboard pages once shipped
// zeroed in production because nothing rendered them against real data.
// Confidence counts requests, not dollars. Unpriced rows cost $0, so a
// dollar-weighted bar would show a full green line on a workspace whose most
// expensive model has no price — the exact failure this panel exists to expose.
// `reconciled_spend_pct` carries the dollar side, shown beside it.
const CONFIDENCE_CLASSES = [
  { key: "reconciled", label: "Provider verified", color: "var(--green)",
    help: "Compared against the provider's own bill and inside the drift threshold." },
  { key: "calculated", label: "Pricing calculated", color: "var(--blue, #4c8dff)",
    help: "Priced from the pricing table. Never checked against a bill." },
  { key: "estimated", label: "Estimated", color: "var(--amber)",
    help: "Rebuilt from a coding agent's local logs. Token counts are the agent's own." },
  { key: "unpriced", label: "Unpriced", color: "var(--red, #e5484d)",
    help: "Tokens were used and we have no price for the model, so these count as $0." },
] as const;

export function CostConfidencePanel({ c }: { c: CostConfidence }) {
  if (c.total_requests === 0) return null;

  return (
    <div className="card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title">Cost confidence</span>
        <span className="section-header-action" title="Share of requests BurnLens can classify economically — every class except unpriced. A plain ratio, not a weighted score.">
          {c.confidence_pct.toFixed(0)}%
        </span>
      </div>
      <div style={{ padding: 16 }}>
        <div
          role="img"
          aria-label={`Cost confidence ${c.confidence_pct.toFixed(0)} percent`}
          style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: "var(--bg3)" }}
        >
          {CONFIDENCE_CLASSES.map(({ key, label, color }) => {
            const pct = (c[key].requests / c.total_requests) * 100;
            if (pct <= 0) return null;
            return <div key={key} title={`${label}: ${pct.toFixed(1)}% of requests`}
                        style={{ width: `${pct}%`, background: color }} />;
          })}
        </div>

        {/* The two questions are different: "are we pricing the workload
            comprehensively" (requests) and "how much known exposure is verified"
            (dollars). One unpriced call can outweigh 99,000 priced ones. */}
        <div style={{ display: "flex", gap: 24, marginTop: 12, fontSize: 12, color: "var(--muted)" }}>
          <span>{c.confidence_pct.toFixed(0)}% of requests classified</span>
          <span>{c.reconciled_spend_pct.toFixed(0)}% of known spend provider-verified</span>
        </div>

        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 14, fontSize: 13 }}>
          {CONFIDENCE_CLASSES.map(({ key, label, color, help }) => {
            const b = c[key];
            if (b.requests === 0) return null;
            return (
              <div key={key} title={help}>
                <div style={{ color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
                  {label}
                </div>
                <div style={{ color: "var(--text)", marginTop: 2 }}>
                  {/* Unpriced dollars are unknowable by definition — showing $0.00 would
                      read as "this cost nothing", which is the opposite of the point. */}
                  {key === "unpriced" ? "$ unknown" : `$${formatCost(b.cost_usd)}`}
                  <span style={{ color: "var(--dim)" }}>
                    {" · "}{b.requests.toLocaleString()} req
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {c.gaps.length > 0 && (
          <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>Coverage gaps</div>
            {c.gaps.map((g, i) => (
              <div key={i} style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.7 }}>
                <span style={{ color: "var(--amber)" }}>⚠</span>{" "}
                <span style={{ color: "var(--text)" }}>
                  {g.provider}{g.model ? ` · ${g.model}` : ""}
                </span>{" "}
                {g.detail}
                {g.requests > 0 && (
                  <span style={{ color: "var(--dim)" }}> ({g.requests.toLocaleString()} req)</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

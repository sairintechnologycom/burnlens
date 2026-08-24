import type { SavingsRollup } from "@/lib/contracts";

// Presentational half of the savings rollup, split out (CacheView pattern) so
// the populated state is testable without hooks or fetches.
//
// Four decimals here, not two: a realised saving is often cents per request and
// rounding it to $0.00 would report a real win as nothing.
function formatCost(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

// The credibility panel. "You could save $42K" is a claim; this is the part that
// says how much of that claim has ever shown up in traffic. Missed fixes count
// toward the denominator and contribute nothing to the numerator — that is what
// makes the ratio worth reading rather than a restatement of the projection.
export function VerifiedSavingsPanel({ r }: { r: SavingsRollup }) {
  const judged = (r.counts.verified ?? 0) + (r.counts.missed ?? 0);
  if (judged === 0 && r.open_projected_monthly_usd <= 0) return null;

  const rows = [
    { label: "Projected, not yet acted on", value: r.open_projected_monthly_usd, color: "var(--muted)",
      help: "Open findings. Nothing has been done about them, so nothing can have been realised." },
    { label: "Predicted for fixes made", value: r.resolved_predicted_monthly_usd, color: "var(--muted)",
      help: "What BurnLens predicted for findings that were resolved, scaled to a month." },
    { label: "Verified", value: r.verified_monthly_usd, color: "var(--green)",
      help: "Measured from traffic after the fix: cost per request actually fell." },
    { label: "Missed", value: r.missed_predicted_monthly_usd, color: "var(--red, #e5484d)",
      help: "The fix landed and cost per request did not fall. The prediction did not materialise." },
    { label: "Still verifying", value: r.verifying_predicted_monthly_usd, color: "var(--amber)",
      help: "The measurement window has not elapsed yet." },
    { label: "Inconclusive", value: r.inconclusive_predicted_monthly_usd, color: "var(--dim)",
      help: "Too little traffic after the fix to judge it either way." },
  ];

  return (
    <div className="card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title">Verified savings</span>
        <span
          className="section-header-action"
          title="Of what was predicted for fixes that have since reached a verdict, how much was actually measured."
        >
          {r.realisation_pct === null ? "—" : `${r.realisation_pct.toFixed(0)}% realised`}
        </span>
      </div>
      <div style={{ padding: 16 }}>
        {rows.map(({ label, value, color, help }) =>
          value > 0 ? (
            <div key={label} title={help}
                 style={{ display: "flex", justifyContent: "space-between", fontSize: 13, lineHeight: 2 }}>
              <span style={{ color: "var(--muted)" }}>{label}</span>
              <span style={{ color }}>${formatCost(value)}/mo</span>
            </div>
          ) : null
        )}
        {judged === 0 && (
          <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 10, lineHeight: 1.6 }}>
            No fix has reached a verdict yet. Resolve a finding and BurnLens measures
            cost per request over the following week before claiming anything.
          </div>
        )}
      </div>
    </div>
  );
}

import type {
  CostConfidence,
  EconomicsOverview,
  OutcomeCoverage,
  ProviderReconciliation,
  SavingsRollup,
  UsageSummary,
} from "@/lib/contracts";
import { formatCost } from "@/lib/money";

function dim(text: string) {
  return <span style={{ color: "var(--dim)" }}>{text}</span>;
}

function hasNoBillingEvidence(
  confidence: CostConfidence | null,
  reconciliation: ProviderReconciliation[],
): boolean {
  if (reconciliation.length > 0) return false;
  if (!confidence) return true;
  const reasons = confidence.reasons ?? {};
  return (reasons.no_billing_key ?? 0) > 0 || confidence.reconciled.requests === 0;
}

function verifiedDisplay(savings: SavingsRollup | null): string | null {
  if (!savings) return null;
  const judged = (savings.counts.verified ?? 0) + (savings.counts.missed ?? 0);
  if (judged === 0 && savings.verified_monthly_usd === 0) return null;
  return `$${formatCost(savings.verified_monthly_usd)}`;
}

/** First-viewport economics: spend → outcome → trust. Existing APIs only. */
export function EconomicsHero({
  summary,
  econ,
  confidence,
  coverage,
  reconciliation,
  savings,
}: {
  summary: UsageSummary | null;
  econ: EconomicsOverview | null;
  confidence: CostConfidence | null;
  coverage: OutcomeCoverage | null;
  reconciliation: ProviderReconciliation[];
  savings: SavingsRollup | null;
}) {
  const hasSpend = (summary?.total_requests ?? 0) > 0;
  const accepted = econ?.accepted_count ?? 0;
  const perAccepted = econ?.cost_per_accepted_usd ?? null;
  const noBilling = hasNoBillingEvidence(confidence, reconciliation);
  const verified = verifiedDisplay(savings);

  return (
    <div className="card" style={{ margin: 16, marginBottom: 0 }}>
      <div className="section-header">
        <span className="section-header-title">AI Economics</span>
        <span className="section-header-action">same engines as the pages</span>
      </div>
      <div
        className="stat-strip"
        style={{ borderBottom: "1px solid var(--border)", gridTemplateColumns: "repeat(3, 1fr)" }}
      >
        <div className="stat-cell">
          <div className="stat-label">AI Spend</div>
          <div className="stat-value">
            {hasSpend ? `$${formatCost(summary?.total_cost_usd ?? 0)}` : dim("—")}
          </div>
          <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
            {hasSpend
              ? `${(summary?.total_requests ?? 0).toLocaleString()} requests`
              : "cost trend below when spend exists"}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Accepted outcomes</div>
          <div className="stat-value">
            {accepted > 0 ? accepted.toLocaleString() : dim("No outcome data yet")}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Cost / accepted outcome</div>
          <div className="stat-value">
            {perAccepted == null
              ? dim("Not enough outcome data")
              : `$${formatCost(perAccepted)}`}
          </div>
        </div>
      </div>
      <div
        className="stat-strip"
        style={{ borderBottom: "none", gridTemplateColumns: "repeat(4, 1fr)" }}
      >
        <div className="stat-cell">
          <div className="stat-label">Cost Confidence</div>
          <div className="stat-value">
            {confidence && confidence.total_requests > 0
              ? `${confidence.confidence_pct.toFixed(0)}%`
              : dim("—")}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Outcome Coverage</div>
          <div className="stat-value">
            {coverage && coverage.cost_total_usd > 0
              ? `${coverage.coverage_pct.toFixed(0)}%`
              : dim("No coverage yet")}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Provider Reconciliation</div>
          <div className="stat-value">
            {noBilling
              ? dim("Not reconciled yet")
              : confidence
                ? `${confidence.reconciled_spend_pct.toFixed(0)}%`
                : dim("Not reconciled yet")}
          </div>
        </div>
        <div className="stat-cell">
          <div className="stat-label">Verified Savings</div>
          <div className="stat-value">
            {verified == null ? dim("No verified changes yet") : verified}
          </div>
        </div>
      </div>
    </div>
  );
}

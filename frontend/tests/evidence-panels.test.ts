import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CostConfidencePanel } from "@/app/dashboard/CostConfidenceView";
import { OutcomeCoveragePanel } from "@/app/dashboard/OutcomeCoverageView";
import { VerifiedSavingsPanel } from "@/app/savings/VerifiedSavingsView";
import type { CostConfidence, OutcomeCoverage, SavingsRollup } from "@/lib/contracts";

// These three panels are the evidence layer's whole user-facing surface. An
// empty-state page is not a tested page — two dashboard pages once shipped
// zeroed in production because nothing rendered them against a populated shape.

const CONFIDENCE: CostConfidence = {
  days: 30,
  total_cost_usd: 100.0,
  total_requests: 200,
  confidence_pct: 75.0,
  reconciled_spend_pct: 40.0,
  reconciled: { cost_usd: 40.0, requests: 50, share_pct: 40.0 },
  calculated: { cost_usd: 50.0, requests: 80, share_pct: 50.0 },
  estimated: { cost_usd: 10.0, requests: 20, share_pct: 10.0 },
  unpriced: { cost_usd: 0.0, requests: 50, share_pct: 0.0 },
  reasons: { provider_bill_agreed: 50, model_has_no_price: 50 },
  gaps: [
    {
      provider: "google",
      model: "mystery-model",
      requests: 50,
      reason: "unpriced",
      detail: "mystery-model has no price in the pricing table — these requests count as $0.",
    },
  ],
};

describe("cost confidence panel", () => {
  it("renders the populated state, not an empty shell", () => {
    const html = renderToStaticMarkup(createElement(CostConfidencePanel, { c: CONFIDENCE }));
    expect(html).toContain("75%");
    expect(html).toContain("mystery-model");
    expect(html).toContain("Provider verified");
  });

  it("never prints $0.00 for unpriced spend", () => {
    // The whole point of the class: those dollars are unknown, not zero.
    // "$0.00" would read as "this cost nothing", the opposite of the warning.
    const html = renderToStaticMarkup(createElement(CostConfidencePanel, { c: CONFIDENCE }));
    expect(html).toContain("$ unknown");
    const unpricedSection = html.slice(html.indexOf("Unpriced"));
    expect(unpricedSection.slice(0, 200)).not.toContain("$0.00");
  });

  it("shows both weightings, because they answer different questions", () => {
    const html = renderToStaticMarkup(createElement(CostConfidencePanel, { c: CONFIDENCE }));
    expect(html).toContain("75% of requests classified");
    expect(html).toContain("40% of known spend provider-verified");
  });

  it("renders nothing when there is no traffic to be confident about", () => {
    const empty = { ...CONFIDENCE, total_requests: 0 };
    expect(renderToStaticMarkup(createElement(CostConfidencePanel, { c: empty }))).toBe("");
  });
});

const COVERAGE: OutcomeCoverage = {
  days: 30,
  window_seconds: 86400,
  cost_total_usd: 100.0,
  cost_attributed_usd: 10.0,
  cost_unattributed_usd: 5.0,
  cost_untagged_usd: 85.0,
  cost_accepted_usd: 8.0,
  cost_rework_usd: 2.0,
  coverage_pct: 10.0,
  by_workflow: [
    { workflow_id: null, cost_total_usd: 85.0, cost_attributed_usd: 0.0, coverage_pct: 0.0 },
    { workflow_id: "wf-a", cost_total_usd: 10.0, cost_attributed_usd: 10.0, coverage_pct: 100.0 },
  ],
};

describe("outcome coverage panel", () => {
  it("names untagged spend, which cost-per-outcome cannot see at all", () => {
    const html = renderToStaticMarkup(createElement(OutcomeCoveragePanel, { c: COVERAGE }));
    expect(html).toContain("10%");
    expect(html).toContain("$85.00");
    expect(html).toContain("No workflow tag");
    // The two gaps have different fixes and must not be collapsed into one.
    expect(html).toContain("Tagged, no outcome");
  });

  it("labels the null workflow row rather than rendering a blank cell", () => {
    const html = renderToStaticMarkup(createElement(OutcomeCoveragePanel, { c: COVERAGE }));
    expect(html).toContain("untagged");
  });

  it("renders nothing when there is no spend", () => {
    const empty = { ...COVERAGE, cost_total_usd: 0 };
    expect(renderToStaticMarkup(createElement(OutcomeCoveragePanel, { c: empty }))).toBe("");
  });
});

const ROLLUP: SavingsRollup = {
  open_projected_monthly_usd: 120.0,
  resolved_predicted_monthly_usd: 30.0,
  verified_monthly_usd: 18.0,
  missed_predicted_monthly_usd: 12.0,
  verifying_predicted_monthly_usd: 0.0,
  inconclusive_predicted_monthly_usd: 0.0,
  realisation_pct: 60.0,
  counts: { verified: 1, missed: 1, open: 3 },
};

describe("verified savings panel", () => {
  it("separates what was verified from what was merely projected", () => {
    const html = renderToStaticMarkup(createElement(VerifiedSavingsPanel, { r: ROLLUP }));
    expect(html).toContain("60% realised");
    expect(html).toContain("$18.00/mo");
    expect(html).toContain("Missed");
    expect(html).toContain("$12.00/mo");
  });

  it("shows a dash, not 0%, when nothing has been judged", () => {
    // 0% reads as "everything failed"; undefined is the honest state.
    const pending: SavingsRollup = {
      ...ROLLUP,
      verified_monthly_usd: 0,
      missed_predicted_monthly_usd: 0,
      verifying_predicted_monthly_usd: 30.0,
      realisation_pct: null,
      counts: { pending: 1, open: 3 },
    };
    const html = renderToStaticMarkup(createElement(VerifiedSavingsPanel, { r: pending }));
    expect(html).not.toContain("0% realised");
    expect(html).toContain("No fix has reached a verdict yet");
  });
});

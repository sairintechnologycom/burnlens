import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { EconomicsNav, ECONOMICS_PAGES } from "@/components/EconomicsNav";
import { EconomicsLoopPanel } from "@/app/dashboard/EconomicsLoopView";
import type {
  EconomicsOverview,
  RecommendationRow,
  SavingsRollup,
} from "@/lib/contracts";

const ECON: EconomicsOverview = {
  total_spend_usd: 100,
  detected_waste_usd: 12.5,
  waste_rate: 0.125,
  open_finding_count: 3,
  error_spend_usd: 1,
  error_request_count: 2,
  cost_per_accepted_usd: 6.84,
  accepted_count: 10,
  waste_by_detector: {},
  waste_estimate_clamped: false,
  trace_coverage: {
    request_count: 100,
    traced_count: 0,
    parented_count: 0,
    distinct_traces: 0,
    traced_rate: 0,
    columns_missing: false,
  },
};

const SAVINGS: SavingsRollup = {
  open_projected_monthly_usd: 40,
  resolved_predicted_monthly_usd: 20,
  verified_monthly_usd: 8.25,
  missed_predicted_monthly_usd: 2,
  verifying_predicted_monthly_usd: 1,
  inconclusive_predicted_monthly_usd: 0,
  realisation_pct: 80,
  counts: { verified: 2, missed: 1 },
};

const REC: RecommendationRow = {
  current_model: "gpt-4o",
  suggested_model: "gpt-4o-mini",
  feature_tag: "classify",
  request_count: 25,
  avg_output_tokens: 30,
  current_cost: 10,
  projected_cost: 2,
  projected_saving: 8,
  saving_pct: 80,
  confidence: "high",
  reason: "short output",
};

describe("economics IA", () => {
  it("is four pages, one model — Overview, Outcomes, Savings, Waste", () => {
    expect(ECONOMICS_PAGES.map((p) => p.href)).toEqual([
      "/dashboard",
      "/outcomes",
      "/savings",
      "/waste",
    ]);
  });

  it("marks the current economics page", () => {
    const html = renderToStaticMarkup(
      createElement(EconomicsNav, { current: "/savings" }),
    );
    expect(html).toContain('aria-current="page"');
    expect(html).toContain("/outcomes");
    expect(html).toContain("/waste");
    expect(html).toContain('href="/savings"');
  });

  it("overview tiles link to the existing engines, not a new one", () => {
    const html = renderToStaticMarkup(
      createElement(EconomicsLoopPanel, {
        econ: ECON,
        savings: SAVINGS,
        recs: [REC],
      }),
    );
    expect(html).toContain('href="/outcomes"');
    expect(html).toContain('href="/savings"');
    expect(html).toContain('href="/waste"');
    expect(html).toContain("$6.84");
    expect(html).toContain("$8.25");
    expect(html).toContain("$12.50");
    expect(html).toContain("1 recommendation");
  });

  it("renders nothing without an economics payload", () => {
    expect(
      renderToStaticMarkup(
        createElement(EconomicsLoopPanel, {
          econ: null,
          savings: null,
          recs: null,
        }),
      ),
    ).toBe("");
  });
});

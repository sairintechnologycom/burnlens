import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { EconomicsNav, ECONOMICS_PAGES } from "@/components/EconomicsNav";
import { EconomicsLoopPanel } from "@/app/dashboard/EconomicsLoopView";
import { EconomicsHero } from "@/app/dashboard/EconomicsHero";
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
    expect(html).toContain("$8.00");
    expect(html.indexOf("$8.25")).not.toBe(html.indexOf("$8.00"));
    expect(html).toContain("projected");
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

  it("does not present unevaluated savings as $0.00", () => {
    const html = renderToStaticMarkup(
      createElement(EconomicsLoopPanel, {
        econ: ECON,
        savings: {
          ...SAVINGS,
          verified_monthly_usd: 0,
          realisation_pct: null,
          counts: { verified: 0, missed: 0 },
        },
        recs: [],
      }),
    );
    expect(html).toContain("No verified changes yet");
    expect(html).not.toContain("$0.00");
  });
});

describe("economics hero", () => {
  it("answers spend, outcomes, and trust from existing payloads", () => {
    const html = renderToStaticMarkup(
      createElement(EconomicsHero, {
        summary: {
          total_cost_usd: 4588.97,
          total_requests: 1200,
          avg_cost_per_request_usd: 3.82,
          models_used: 4,
          cache_saved_usd: 0,
          cache_hits: 0,
        },
        econ: ECON,
        confidence: {
          days: 30,
          total_cost_usd: 100,
          total_requests: 100,
          confidence_pct: 94,
          reconciled_spend_pct: 71,
          reconciled: { cost_usd: 71, requests: 40, share_pct: 40 },
          calculated: { cost_usd: 20, requests: 40, share_pct: 40 },
          estimated: { cost_usd: 9, requests: 14, share_pct: 14 },
          unpriced: { cost_usd: 0, requests: 6, share_pct: 6 },
          reasons: {},
          gaps: [],
        },
        coverage: {
          days: 30,
          window_seconds: 86400,
          cost_total_usd: 100,
          cost_attributed_usd: 82,
          cost_unattributed_usd: 10,
          cost_untagged_usd: 8,
          cost_accepted_usd: 70,
          cost_rework_usd: 12,
          coverage_pct: 82,
          by_workflow: [],
        },
        reconciliation: [
          {
            provider: "openai",
            status: "reconciled",
            day: "2026-09-01",
            provider_cost_usd: 10,
            burnlens_cost_usd: 10,
            drift_pct: 0,
            computed_at: null,
          },
        ],
        savings: SAVINGS,
      }),
    );
    expect(html).toContain("AI Spend");
    expect(html).toContain("Accepted outcomes");
    expect(html).toContain("Cost / accepted outcome");
    expect(html).toContain("Cost Confidence");
    expect(html).toContain("Outcome Coverage");
    expect(html).toContain("$6.84");
    expect(html).toContain("94%");
    expect(html).toContain("82%");
  });

  it("keeps absent outcomes and verification distinct from zero", () => {
    const html = renderToStaticMarkup(
      createElement(EconomicsHero, {
        summary: {
          total_cost_usd: 12,
          total_requests: 4,
          avg_cost_per_request_usd: 3,
          models_used: 1,
          cache_saved_usd: 0,
          cache_hits: 0,
        },
        econ: { ...ECON, accepted_count: 0, cost_per_accepted_usd: null },
        confidence: null,
        coverage: null,
        reconciliation: [],
        savings: null,
      }),
    );
    expect(html).toContain("No outcome data yet");
    expect(html).toContain("Not enough outcome data");
    expect(html).toContain("Not reconciled yet");
    expect(html).toContain("No verified changes yet");
    expect(html).not.toContain("$0.00");
  });
});

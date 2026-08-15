import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  OutcomesTable,
  formatPerAccepted,
  formatUsd,
} from "@/app/outcomes/OutcomesTable";
import type { WorkflowEconomics } from "@/lib/contracts";

const BASE: WorkflowEconomics = {
  workflow_id: "refund_review",
  accepted_count: 10,
  rejected_count: 2,
  failed_count: 1,
  cost_total_usd: 1.5,
  cost_accepted_usd: 1.0,
  cost_rework_usd: 0.4,
  cost_unattributed_usd: 0.1,
  cost_per_accepted_usd: 0.15,
  business_value_accepted: null,
};

describe("outcomes formatters", () => {
  it("renders real zero as $0.00, not an em dash", () => {
    expect(formatUsd(0)).toMatch(/^0[.,]00/);
    expect(formatPerAccepted(0)).toBe(`$${formatUsd(0)}`);
  });

  it("renders missing unit cost as an em dash", () => {
    expect(formatPerAccepted(null)).toBe("—");
  });
});

describe("outcomes table", () => {
  it("shows — when a workflow has spend and no accepted outcomes", () => {
    const html = renderToStaticMarkup(
      createElement(OutcomesTable, {
        rows: [{
          ...BASE,
          workflow_id: "repo:burnlens",
          accepted_count: 0,
          cost_per_accepted_usd: null,
        }],
      }),
    );
    expect(html).toContain("repo:burnlens");
    expect(html).toContain("—");
    expect(html).not.toContain("$0.00");
    // CLI `outcome show` collapses rejected + failed into one column.
    expect(html).toContain("3");
  });

  it("shows $0.00 when per-accepted is a real zero", () => {
    const html = renderToStaticMarkup(
      createElement(OutcomesTable, {
        rows: [{ ...BASE, cost_per_accepted_usd: 0, cost_total_usd: 0 }],
      }),
    );
    expect(html).toContain("$0.00");
    expect(html).not.toContain("—");
  });
});

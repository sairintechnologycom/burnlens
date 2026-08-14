import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FindingsList, verdictLine } from "@/app/waste/FindingsList";
import type { FindingItem, SavingsVerdict } from "@/lib/contracts";

const SAMPLE: FindingItem = {
  id: "abc123abc123abc123abc123abc123ab",
  fingerprint: "abc123abc123abc123abc123abc123ab",
  detector: "ModelOverkillDetector",
  subject_type: "workflow",
  subject_key: "invoice-gen",
  severity: "high",
  title: "Model Overkill",
  description: "3 request(s) on workflow 'invoice-gen' used an expensive model.",
  estimated_waste_usd: 0.21,
  affected_count: 3,
  evidence: { models: ["claude-opus-5"] },
  status: "open",
  first_seen_at: "2026-08-14T00:00:00+00:00",
  last_seen_at: "2026-08-14T01:00:00+00:00",
  resolved_at: null,
  baseline_waste_usd: null,
  baseline_cost_usd: null,
  baseline_requests: null,
  baseline_window_days: null,
  detection_count: 2,
  detector_version: 1,
};

describe("waste findings list", () => {
  it("renders a real finding row", () => {
    const html = renderToStaticMarkup(
      createElement(FindingsList, { findings: [SAMPLE] }),
    );
    expect(html).toContain("Model Overkill");
    expect(html).toContain("workflow: invoice-gen");
    expect(html).toContain("Acknowledge");
    expect(html).toContain("Mark fixed");
    expect(html).toContain("Accept risk");
    expect(html).toContain("data-testid=\"finding-row\"");
    expect(html).not.toContain("useful + waste + error");
  });

  it("renders a verified verdict card", () => {
    const verdict: SavingsVerdict = {
      fingerprint: SAMPLE.id,
      title: SAMPLE.title,
      subject_type: SAMPLE.subject_type,
      subject_key: SAMPLE.subject_key,
      status: "verified",
      baseline_cost_per_request: 1,
      current_cost_per_request: 0.5,
      delta_per_request: 0.5,
      pct_change: -50,
      projected_monthly_savings_usd: 21.4,
      baseline_requests: 10,
      current_requests: 10,
      days_remaining: null,
      reopened: false,
    };
    const html = renderToStaticMarkup(
      createElement(FindingsList, { findings: [SAMPLE], verdicts: { [SAMPLE.id]: verdict } }),
    );
    expect(html).toContain("Fix verified");
    expect(html).toContain("data-testid=\"finding-verdict\"");
    expect(verdictLine(verdict)).toContain("$1.00 → $0.50");
  });

  it("renders the empty state", () => {
    const html = renderToStaticMarkup(createElement(FindingsList, { findings: [] }));
    expect(html).toContain("No waste findings in this view.");
    expect(html).toContain("data-testid=\"findings-empty\"");
  });
});

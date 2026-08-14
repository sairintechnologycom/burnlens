import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FindingsList } from "@/app/waste/FindingsList";
import type { FindingItem } from "@/lib/contracts";

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

  it("renders the empty state", () => {
    const html = renderToStaticMarkup(createElement(FindingsList, { findings: [] }));
    expect(html).toContain("No waste findings in this view.");
    expect(html).toContain("data-testid=\"findings-empty\"");
  });
});

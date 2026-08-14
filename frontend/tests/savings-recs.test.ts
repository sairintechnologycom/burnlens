import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { RecommendationRow } from "@/lib/contracts";

function SavingsRow({ r }: { r: RecommendationRow }) {
  return createElement(
    "tr",
    { "data-testid": "savings-row" },
    createElement("td", null, r.feature_tag),
    createElement("td", null, r.current_model),
    createElement("td", null, r.suggested_model),
    createElement("td", null, `$${r.projected_saving.toFixed(2)}`),
  );
}

const SAMPLE: RecommendationRow = {
  current_model: "gpt-4o",
  suggested_model: "gpt-4o-mini",
  feature_tag: "chat",
  request_count: 21,
  avg_output_tokens: 40,
  current_cost: 10.5,
  projected_cost: 2.1,
  projected_saving: 8.4,
  saving_pct: 80,
  confidence: "high",
  reason: "Average output is only 40 tokens across 21 requests",
};

describe("savings recommendation row", () => {
  it("renders one recommendation", () => {
    const html = renderToStaticMarkup(createElement(SavingsRow, { r: SAMPLE }));
    expect(html).toContain("gpt-4o");
    expect(html).toContain("gpt-4o-mini");
    expect(html).toContain("chat");
    expect(html).toContain("data-testid=\"savings-row\"");
  });
});

import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import LlmPricing from "../src/app/llm-pricing/page";

describe("pricing evidence on the public catalog", () => {
  it("distinguishes sourced rates from catalog entries without source evidence", () => {
    const html = renderToStaticMarkup(createElement(LlmPricing));

    expect(html).toContain("catalog updated 2026-09-27");
    expect(html).toContain("Not source-verified");
    expect(html).toContain('href="https://developers.openai.com/api/docs/models/gpt-5.6-sol"');
    expect(html).toContain("Provider verified · effective 2026-08-21");
    expect(html).not.toContain("rates verified 2026-09-27");
  });
});

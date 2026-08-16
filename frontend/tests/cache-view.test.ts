import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { CacheView, cacheRatePct } from "@/app/cache/CacheView";
import type { CacheOverview } from "@/lib/contracts";

// Anthropic-style dogfood shape: prompt almost entirely cache reads.
const SAMPLE: CacheOverview = {
  prompt_tokens: 200000,
  cache_read_tokens: 150000,
  cache_write_tokens: 20000,
  uncached_input_tokens: 30000,
  cache_read_rate: 0.75,
  request_count: 40,
  proxy_cache_hits: 3,
  proxy_cache_saved_usd: 0.42,
  by_model: [
    {
      model: "claude-opus-5",
      request_count: 30,
      prompt_tokens: 160000,
      cache_read_tokens: 140000,
      cache_read_rate: 0.875,
    },
  ],
};

describe("cache view", () => {
  it("renders the populated state, not just an empty shell", () => {
    const html = renderToStaticMarkup(
      createElement(CacheView, { data: SAMPLE, days: 7 }),
    );
    expect(html).toContain("200,000");
    expect(html).toContain("75.0%");
    expect(html).toContain("claude-opus-5");
    expect(html).toContain("87.5%");
    expect(html).toContain("$0.42");
    expect(html).toContain("3 hits");
    expect(html).toContain('data-testid="cache-model-row"');
    expect(html).not.toContain("No requests in this window");
  });

  it("renders the empty state when no models", () => {
    const html = renderToStaticMarkup(
      createElement(CacheView, {
        data: { ...SAMPLE, prompt_tokens: 0, cache_read_rate: 0, by_model: [] },
        days: 7,
      }),
    );
    expect(html).toContain("No requests in this window");
  });

  it("formats rates without float noise", () => {
    expect(cacheRatePct(0.875)).toBe("87.5%");
    expect(cacheRatePct(0)).toBe("0.0%");
  });
});

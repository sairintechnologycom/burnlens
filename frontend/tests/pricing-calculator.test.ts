import { describe, expect, it } from "vitest";
import { estimate, providers, type Model } from "../src/app/llm-pricing/estimate";

const TODAY = "2026-08-24";

function model(provider: string, name: string): Model {
  const m = providers.find((p) => p.provider === provider)?.models.find((x) => x.name === name);
  if (!m) throw new Error(`missing fixture model ${provider}/${name}`);
  return m;
}

const base = { promptTokens: 100_000, outputTokens: 1_000, cachedPct: 90, requests: 1 };

describe("estimate", () => {
  // The whole reason this calculator exists: the naive number is the one every
  // other calculator prints, and for an agent workload it is multiples too high.
  it("prices cached prompt tokens below the naive all-input answer", () => {
    const m = model("anthropic", "claude-sonnet-4");
    const r = estimate("anthropic", m, base, TODAY);
    expect(r.perRequest).toBeLessThan(r.naivePerRequest / 2);
    // 10k uncached @ $3 + 90k cache read @ $0.30 + 1k out @ $15
    expect(r.perRequest).toBeCloseTo(0.03 + 0.027 + 0.015, 6);
  });

  it("bills the same tokens on both cache conventions", () => {
    // Anthropic reports cache reads outside its prompt count, OpenAI inside it.
    // The dollar figure must not depend on which convention the provider uses.
    const anthropic = estimate("anthropic", model("anthropic", "claude-sonnet-4"), base, TODAY);
    expect(anthropic.inputTokens).toBe(10_000);
    const openaiModel = model("openai", "gpt-4o");
    const openai = estimate("openai", openaiModel, base, TODAY);
    expect(openai.inputTokens).toBe(100_000);
    const inRate = openaiModel.input_per_million!;
    const cacheRate = openaiModel.cache_read_per_million ?? inRate;
    expect(openai.perRequest).toBeCloseTo(
      (10_000 * inRate + 90_000 * cacheRate + 1_000 * openaiModel.output_per_million!) / 1e6,
      9,
    );
  });

  it("charges full input price when a model has no cache rate", () => {
    const m = providers
      .flatMap((p) => p.models.map((x) => ({ provider: p.provider, m: x })))
      .find((x) => x.m.cache_read_per_million === undefined && x.m.input_per_million)!;
    const r = estimate(x_provider(m), m.m, { ...base, outputTokens: 0 }, TODAY);
    expect(r.cacheAware).toBe(false);
    expect(r.perRequest).toBeCloseTo(r.naivePerRequest, 9);
  });

  it("applies a long-context tier to the whole request", () => {
    const tiered = providers
      .flatMap((p) => p.models.map((m) => ({ provider: p.provider, m })))
      .find((x) => (x.m.tiered ?? []).length > 0);
    if (!tiered) return; // no tiered model in the snapshot; nothing to assert
    const over = tiered.m.tiered![0].over!;
    const under = estimate(tiered.provider, tiered.m, { ...base, promptTokens: over - 1, cachedPct: 0 }, TODAY);
    const above = estimate(tiered.provider, tiered.m, { ...base, promptTokens: over + 1, cachedPct: 0 }, TODAY);
    expect(under.tierApplied).toBe(false);
    expect(above.tierApplied).toBe(true);
    // Whole-request switch, not marginal: doubling one token more than doubles cost.
    expect(above.perRequest).toBeGreaterThan(under.perRequest * 1.2);
  });

  it("switches to a scheduled rate only once its date has arrived", () => {
    const s = providers
      .flatMap((p) => p.models.map((m) => ({ provider: p.provider, m })))
      .find((x) => (x.m.scheduled ?? []).length > 0);
    if (!s) return; // no dated change pending; nothing to assert
    const eff = s.m.scheduled![0].effective!;
    const day = (d: string, delta: number) => {
      const t = new Date(`${d}T00:00:00Z`);
      t.setUTCDate(t.getUTCDate() + delta);
      return t.toISOString().slice(0, 10);
    };
    const before = estimate(s.provider, s.m, { ...base, cachedPct: 0 }, day(eff, -1));
    const after = estimate(s.provider, s.m, { ...base, cachedPct: 0 }, eff);
    expect(after.perRequest).not.toBe(before.perRequest);
  });

  it("scales linearly with request count", () => {
    const m = model("anthropic", "claude-sonnet-4");
    const r = estimate("anthropic", m, { ...base, requests: 250 }, TODAY);
    expect(r.total).toBeCloseTo(r.perRequest * 250, 9);
  });
});

function x_provider(x: { provider: string }): string {
  return x.provider;
}

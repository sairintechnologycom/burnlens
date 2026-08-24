import pricing from "@/data/llm-pricing.json";

export type Rate = {
  effective?: string;
  over?: number;
  input_per_million?: number;
  output_per_million?: number;
  cache_read_per_million?: number;
  cache_write_per_million?: number;
};

export type Model = Rate & {
  name: string;
  scheduled?: Rate[];
  tiered?: Rate[];
};

export type Provider = { provider: string; updated: string | null; models: Model[] };

export const providers = pricing.providers as Provider[];

/**
 * Providers whose reported prompt count already contains the cached tokens.
 * Generated from the Python registry by scripts/build_pricing_snapshot.py —
 * never hand-edit the list here, the two conventions are a registry property.
 */
const INCLUSIVE = new Set(pricing.inclusive_prompt_tokens as string[]);

/** Mirror of burnlens.cost.pricing._apply_scheduled: latest tier already in effect wins. */
function applyScheduled(m: Model, today: string): Rate {
  const active = (m.scheduled ?? [])
    .filter((s) => (s.effective ?? "") <= today)
    .sort((a, b) => (a.effective! < b.effective! ? -1 : 1))
    .pop();
  const { scheduled: _s, tiered: _t, ...base } = m;
  return { ...base, ...(active ?? {}) };
}

/** Mirror of burnlens.cost.pricing.apply_tiered: highest `over` the prompt EXCEEDS wins. */
function applyTiered(rate: Rate, tiers: Rate[], inputTokens: number): Rate {
  const active = tiers
    .filter((t) => inputTokens > (t.over ?? 0))
    .sort((a, b) => (a.over ?? 0) - (b.over ?? 0))
    .pop();
  const { over: _o, effective: _e, ...merged } = { ...rate, ...(active ?? {}) };
  return merged;
}

export type Inputs = {
  promptTokens: number;
  outputTokens: number;
  /** Share of the prompt served from cache, 0–100. */
  cachedPct: number;
  requests: number;
};

export type Estimate = {
  perRequest: number;
  total: number;
  /** Same request priced with the whole prompt at the input rate — the naive answer. */
  naivePerRequest: number;
  inputTokens: number;
  cacheReadTokens: number;
  cacheAware: boolean;
  tierApplied: boolean;
};

/**
 * Cost for one request and for `requests` of them, mirroring
 * burnlens.cost.calculator.calculate_cost for the text-only path.
 *
 * ponytail: models steady state — no cache writes, no reasoning or audio
 * tokens, no per-unit fees. A first request that populates the cache costs
 * more; the page says so. Add the write leg if anyone asks for turn-one cost.
 */
export function estimate(
  provider: string,
  model: Model,
  { promptTokens, outputTokens, cachedPct, requests }: Inputs,
  today: string,
): Estimate {
  const prompt = Math.max(0, promptTokens);
  const cacheRead = Math.round((prompt * Math.min(100, Math.max(0, cachedPct))) / 100);
  const inclusive = INCLUSIVE.has(provider);

  // Inclusive providers report the full prompt and bill the cached share at the
  // cache rate; disjoint providers (Anthropic, Bedrock) report only the uncached
  // remainder. Either way the billable input is the uncached part.
  const inputTokens = inclusive ? prompt : prompt - cacheRead;
  const billableInput = prompt - cacheRead;

  const base = applyScheduled(model, today);
  const tiers = model.tiered ?? [];
  const rate = tiers.length ? applyTiered(base, tiers, inputTokens) : base;
  const tierApplied = tiers.some((t) => inputTokens > (t.over ?? 0));

  const M = 1_000_000;
  const cacheRate = rate.cache_read_per_million;
  const inRate = rate.input_per_million ?? 0;
  const outRate = rate.output_per_million ?? 0;

  // No cache_read rate means the provider does not discount cached tokens, so
  // they cost full input price — not zero, which is what dropping them implies.
  const perRequest =
    (billableInput * inRate + cacheRead * (cacheRate ?? inRate) + Math.max(0, outputTokens) * outRate) / M;
  const naivePerRequest = (prompt * inRate + Math.max(0, outputTokens) * outRate) / M;

  return {
    perRequest,
    total: perRequest * Math.max(0, requests),
    naivePerRequest,
    inputTokens,
    cacheReadTokens: cacheRead,
    cacheAware: cacheRate !== undefined,
    tierApplied,
  };
}

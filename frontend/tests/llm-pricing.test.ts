import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import snapshot from "../src/data/llm-pricing.json";
import sitemap from "../src/app/sitemap";

// The Next app builds from `frontend/` as its own Vercel root and cannot read the
// Python package at build time, so /llm-pricing renders a committed snapshot of
// burnlens/cost/pricing_data. A snapshot nobody re-generates is a price list that
// silently lies, which is worse than not publishing one — so fail the build when
// it drifts. Regenerate with: python scripts/build_pricing_snapshot.py
const SRC = join(__dirname, "..", "..", "burnlens", "cost", "pricing_data");

function fromSource() {
  return readdirSync(SRC)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => {
      const data = JSON.parse(readFileSync(join(SRC, f), "utf8"));
      const models = Object.entries(data.models ?? {})
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([name, rates]) => ({ name, ...(rates as object) }));
      return { provider: data.provider, updated: data.updated ?? null, models };
    });
}

describe("llm-pricing snapshot", () => {
  it("matches burnlens/cost/pricing_data", () => {
    expect(snapshot.providers).toEqual(fromSource());
  });

  it("counts the models it claims to", () => {
    const actual = snapshot.providers.reduce((n, p) => n + p.models.length, 0);
    expect(snapshot.model_count).toBe(actual);
  });

  it("prices every model on both sides of the request", () => {
    for (const p of snapshot.providers) {
      for (const m of p.models) {
        expect(m, `${p.provider}/${m.name}`).toHaveProperty("input_per_million");
        expect(m, `${p.provider}/${m.name}`).toHaveProperty("output_per_million");
      }
    }
  });

  it("is in the sitemap", () => {
    expect(sitemap().map((e) => e.url)).toContain("https://burnlens.app/llm-pricing");
  });
});

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import snapshot from "../src/data/cost-per-outcome.json";
import sitemap from "../src/app/sitemap";

// /cost-per-outcome renders a committed snapshot of the dogfood database, built
// by scripts/build_outcome_snapshot.py. Unlike the pricing snapshot there is no
// checked-in source to diff against -- the source is one machine's SQLite file,
// which CI cannot see. So this suite checks the two things that can still go
// wrong without anyone noticing:
//
//   1. The published numbers stop agreeing with each other, because someone
//      hand-edited the JSON or changed a formula in the page but not the script.
//   2. A private repository name reaches a public page, because someone widened
//      PUBLISHABLE in the script and regenerated.
//
// Deliberately NOT asserted: freshness. A staleness check would need the
// database, and a test that silently cannot fail is worse than no test.
const SCRIPT = join(__dirname, "..", "..", "scripts", "build_outcome_snapshot.py");

/** The disclosure decision, restated where a reviewer of a frontend diff sees it.
 *  Widened from repo:burnlens alone to every repository on 2026-08-23. */
const PUBLISHABLE = [
  "repo:deploymentlab",
  "repo:manan",
  "repo:zeroslateUI",
  "repo:burnlens",
  "repo:pkgsafe",
  "repo:strata",
  "repo:mediaOS",
  "repo:sutra",
  "repo:DermaLens",
  "repo:ShubhLifafa",
  "repo:SiteHQ",
  "repo:Infracanvas",
  "repo:interview_copilot",
];

const round = (v: number, digits: number) =>
  Number(Math.round(Number(`${v}e${digits}`)) + `e-${digits}`);

describe("cost-per-outcome snapshot", () => {
  it("publishes only the allowlisted workflows", () => {
    for (const w of snapshot.workflows) {
      expect(PUBLISHABLE, `${w.workflow_id} is not cleared for publication`).toContain(
        w.workflow_id,
      );
    }
  });

  it("keeps the frontend allowlist in step with the generator's", () => {
    // Widening one side only is how a private repo name ships. Both must move.
    const py = readFileSync(SCRIPT, "utf8");
    const block = py.match(/PUBLISHABLE = \(([^)]*)\)/);
    expect(block, "PUBLISHABLE tuple not found in build_outcome_snapshot.py").not.toBeNull();
    const generator = [...block![1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(generator).toEqual(PUBLISHABLE);
  });

  it("divides total spend by accepted outcomes", () => {
    for (const w of snapshot.workflows) {
      if (w.accepted === 0) {
        // A workflow burning money with nothing accepted has no unit cost;
        // reporting 0 or Infinity there would be worse than reporting nothing.
        expect(w.cost_per_accepted_usd).toBeNull();
        continue;
      }
      expect(w.cost_per_accepted_usd).toBeCloseTo(w.cost_usd / w.accepted, 4);
    }
  });

  it("counts tokens per accepted outcome across all four token classes", () => {
    for (const w of snapshot.workflows) {
      if (w.accepted === 0) continue;
      const total =
        w.input_tokens + w.output_tokens + w.cache_read_tokens + w.cache_write_tokens;
      // Within half a token rather than an exact Math.round match: the
      // generator is Python, whose round() breaks ties to even while JS rounds
      // half up. One repo lands exactly on .5 and the two disagree by 1, which
      // is a rounding convention, not a counting error.
      expect(Math.abs(w.tokens_per_accepted! - total / w.accepted)).toBeLessThanOrEqual(0.5);
    }
  });

  it("measures cache share against prompt tokens, not all tokens", () => {
    // Output tokens are not prompt tokens. Folding them into the denominator
    // would understate the share that makes input-only estimates wrong.
    for (const w of snapshot.workflows) {
      const prompt = w.input_tokens + w.cache_read_tokens;
      if (prompt === 0) {
        expect(w.cache_read_share).toBeNull();
        continue;
      }
      expect(w.cache_read_share).toBeCloseTo(w.cache_read_tokens / prompt, 4);
    }
  });

  it("reports a spend window the outcomes could actually fall inside", () => {
    for (const w of snapshot.workflows) {
      expect(new Date(w.window_start).getTime()).toBeLessThan(
        new Date(w.window_end).getTime(),
      );
    }
  });

  it("has model spend that sums to the workflow total", () => {
    for (const w of snapshot.workflows) {
      const summed = w.models.reduce((n, m) => n + m.cost_usd, 0);
      expect(round(summed, 2)).toBe(round(w.cost_usd, 2));
    }
  });

  it("accounts for every dollar in the attribution disclosure", () => {
    const { total_cost_usd, attributed_cost_usd, unattributed_cost_usd } = snapshot.database;
    expect(round(attributed_cost_usd + unattributed_cost_usd, 4)).toBe(
      round(total_cost_usd, 4),
    );
    // Published workflows are a subset of attributed spend, never more than it.
    const published = snapshot.workflows.reduce((n, w) => n + w.cost_usd, 0);
    expect(published).toBeLessThanOrEqual(attributed_cost_usd);
  });

  it("aggregates the published block over exactly the published rows", () => {
    const p = snapshot.published;
    expect(p.repos).toBe(snapshot.workflows.length);
    expect(round(snapshot.workflows.reduce((n, w) => n + w.cost_usd, 0), 4)).toBe(
      round(p.cost_usd, 4),
    );
    expect(snapshot.workflows.reduce((n, w) => n + w.accepted, 0)).toBe(p.accepted);
    expect(snapshot.workflows.reduce((n, w) => n + w.requests, 0)).toBe(p.requests);
  });

  it("blends spend-weighted, not as a mean of the per-repo rates", () => {
    // A mean of ratios would weight a 2-PR repo the same as a 104-PR one, and
    // on this data it lands roughly 1.3x higher than the truth.
    const p = snapshot.published;
    if (p.accepted === 0) {
      expect(p.cost_per_accepted_usd).toBeNull();
      return;
    }
    expect(p.cost_per_accepted_usd).toBeCloseTo(p.cost_usd / p.accepted, 4);
  });

  it("takes cheapest and dearest from the rows that actually have a unit cost", () => {
    const rates = snapshot.workflows
      .map((w) => w.cost_per_accepted_usd)
      .filter((v): v is number => v !== null);
    const p = snapshot.published;
    expect(p.repos_with_unit_cost).toBe(rates.length);
    if (rates.length === 0) {
      expect(p.cheapest_usd).toBeNull();
      expect(p.dearest_usd).toBeNull();
      return;
    }
    expect(p.cheapest_usd).toBe(Math.min(...rates));
    expect(p.dearest_usd).toBe(Math.max(...rates));
  });

  it("distinguishes 'no merged PRs' from 'merged PRs outside the window'", () => {
    // The page renders a different reason per row from this field. If it ever
    // went negative the window filter and the all-time count would be counting
    // different things.
    for (const w of snapshot.workflows) {
      expect(w.accepted_outside_window).toBeGreaterThanOrEqual(0);
    }
  });

  it("is in the sitemap", () => {
    expect(sitemap().map((e) => e.url)).toContain("https://burnlens.app/cost-per-outcome");
  });
});

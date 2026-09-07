import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const read = (...parts: string[]) =>
  readFileSync(join(__dirname, "..", ...parts), "utf8");

const contract = JSON.parse(read("src", "lib", "product-contract.json"));

describe("public product contract", () => {
  it("self-service trial is 7 days, card-required, $29 Cloud — not a 14-day SKU", () => {
    expect(contract.cloud_trial.days).toBe(7);
    expect(contract.cloud_trial.card_required).toBe(true);
    expect(contract.cloud_trial.price_monthly).toBe("$29");
    expect(contract.agency_pilot.public_sku).toBe(false);
    expect(contract.agency_pilot.days).toBe(14);
  });

  it("homepage interpolates the contract commands and unknown-pricing rule", () => {
    const homepage = read("src", "app", "page.tsx");
    expect(homepage).toContain('text: "burnlens repos"');
    expect(homepage).toContain("counts as $ unknown");
    expect(homepage).toContain("Start 7-day free trial");
    expect(homepage).not.toContain("Helicone / Langfuse");
  });

  it("agency page states the ladder and does not invent a 14-day public trial", () => {
    const src = read("src", "app", "for", "agencies", "page.tsx");
    expect(src).toContain("Know what each AI-powered client project actually costs");
    expect(src).toContain("Unallocated");
    expect(src).toContain("C.savings_projected");
    expect(src).toContain("C.savings_verified");
    expect(src).toContain("$ unknown");
    expect(src).toContain("7-day");
    expect(src).toContain("$29");
    expect(src.toLowerCase()).not.toContain("14-day free trial");
  });
});

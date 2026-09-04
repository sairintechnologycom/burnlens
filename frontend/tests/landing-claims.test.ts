import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// The landing hero quotes a dogfood cost-per-PR figure. It has gone stale once
// already: $5.03 survived on the live site long after the opus-5 pricing fix and
// the backlog re-cost moved the real number. A number with no measurement date
// reads as permanently current, so require the stamp rather than pinning a value
// that is supposed to change.
const MEASURED = /measured (\d{4})-(\d{2})-(\d{2})/;

const read = (...parts: string[]) =>
  readFileSync(join(__dirname, "..", ...parts), "utf8");

describe("landing dogfood claims", () => {
  it("dates the hero cost-per-PR figure", () => {
    expect(read("src", "app", "page.tsx")).toMatch(MEASURED);
  });

  it("dates the README cost-per-PR figure", () => {
    expect(read("..", "README.md")).toMatch(/on \d{4}-\d{2}-\d{2}/);
  });

  it("no longer quotes the retired pre-recost numbers", () => {
    const sources = read("src", "app", "page.tsx") + read("..", "README.md");
    for (const retired of ["$5.03", "$8.93", "$6.98", "81 merged PRs", "97 merged PRs"]) {
      expect(sources).not.toContain(retired);
    }
  });

  it("post-scan onboarding is burnlens repos, not burnlens top", () => {
    const homepage = read("src", "app", "page.tsx");
    expect(homepage).toContain('text: "burnlens repos"');
    expect(homepage).not.toContain('text: "burnlens top"');
    const install = homepage.slice(homepage.indexOf("Up in 3 commands"));
    expect(install).toContain("burnlens repos");
    expect(install).not.toContain("burnlens top");
  });

  it("attributes coding-agent scan cost per-repo, not per-PR", () => {
    const homepage = read("src", "app", "page.tsx");
    expect(homepage).toContain("per-repo, per-dev attribution");
    expect(homepage).not.toContain("per-PR, per-dev attribution");
    const readme = read("..", "README.md");
    expect(readme).toContain("cost per repo and developer from local logs");
    expect(readme).not.toContain("attribute cost per PR, repo, or developer");
  });
});

import { describe, expect, it } from "vitest";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { DOCS_PAGES } from "../src/lib/docs";
import sitemap from "../src/app/sitemap";

// Splitting docs into separate pages only pays off if search engines are told
// the pages exist. Adding a route and forgetting the sitemap is the silent
// failure that costs the whole exercise, so pin the three things together:
// the nav list, the route on disk, and the sitemap entry.
const APP = join(__dirname, "..", "src", "app");

describe("docs routes", () => {
  const urls = sitemap().map((e) => e.url);

  it.each(DOCS_PAGES.map((p) => p.href))("%s has a page on disk", (href) => {
    const segment = href.replace(/^\/docs\/?/, "");
    const file = segment
      ? join(APP, "docs", segment, "page.tsx")
      : join(APP, "docs", "page.tsx");
    expect(existsSync(file)).toBe(true);
  });

  it.each(DOCS_PAGES.map((p) => p.href))("%s is listed in the sitemap", (href) => {
    expect(urls).toContain(`https://burnlens.app${href}`);
  });

  it("does not disallow /docs in robots", async () => {
    const robots = (await import("../src/app/robots")).default();
    const rules = Array.isArray(robots.rules) ? robots.rules : [robots.rules];
    for (const rule of rules) {
      const disallow = rule.disallow ?? [];
      const list = Array.isArray(disallow) ? disallow : [disallow];
      expect(list.some((d) => d.startsWith("/docs"))).toBe(false);
    }
  });
});

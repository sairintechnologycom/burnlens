import { test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const OUT = join(__dirname, "..", "..", "..", "output", "playwright");

test("capture public economics surfaces", async ({ page }, info) => {
  test.skip(!process.env.BLU_SCREENSHOTS, "opt-in evidence capture");
  mkdirSync(OUT, { recursive: true });
  const tag = info.project.name.replace(/\s+/g, "-").toLowerCase();
  for (const route of ["/", "/demo", "/scan", "/docs/budgets", "/compare/burnlens-vs-litellm"]) {
    await page.goto(route, { waitUntil: "networkidle" });
    const name = route === "/" ? "home" : route.slice(1).replace(/\//g, "-");
    await page.screenshot({
      path: join(OUT, `blu-${name}-${tag}.png`),
      fullPage: true,
    });
  }
});

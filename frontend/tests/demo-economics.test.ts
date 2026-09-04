import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import DemoPage from "@/app/demo/page";

describe("economics demo", () => {
  it("tells the economic loop, not a cost-tracker-only story", () => {
    const html = renderToStaticMarkup(createElement(DemoPage));
    expect(html).toContain("DETERMINISTIC_DEMO_FIXTURE");
    expect(html).toContain("AI Spend");
    expect(html).toContain("Accepted outcomes");
    expect(html).toContain("Cost / accepted outcome");
    expect(html).toContain("Cost Confidence");
    expect(html).toContain("Outcome Coverage");
    expect(html).toContain("What should change?");
    expect(html).toContain("Did it work?");
    expect(html).toContain("Verified Savings");
    expect(html).toContain("No verified changes yet");
    expect(html).toContain("projected is not verified");
    expect(html).toContain("This policy can change the model sent upstream.");
    expect(html).toContain("burnlens repos");
    expect(html).not.toContain("LIVE DEMO");
    expect(html).not.toContain("Total spend");
  });

  it("does not present the fixture as live telemetry", () => {
    const html = renderToStaticMarkup(createElement(DemoPage));
    expect(html).toContain("not live telemetry");
    expect(html).not.toContain("this is the view you get on your own machine");
  });
});

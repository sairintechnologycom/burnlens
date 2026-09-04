import { describe, expect, it } from "vitest";
import { formatRequestCostUsd } from "@/lib/money";

describe("formatRequestCostUsd", () => {
  it("renders unpriced as $ unknown, never a measured zero", () => {
    expect(formatRequestCostUsd(0, "unpriced")).toBe("$ unknown");
    expect(formatRequestCostUsd(0, "unpriced")).not.toContain("$0");
    expect(formatRequestCostUsd(null, "unpriced")).toBe("$ unknown");
  });

  it("renders a known zero-cost request as $0.0000", () => {
    expect(formatRequestCostUsd(0, "calculated")).toBe("$0.0000");
    expect(formatRequestCostUsd(0, "estimated")).toBe("$0.0000");
  });

  it("renders a priced amount with four decimals", () => {
    expect(formatRequestCostUsd(0.0123, "calculated")).toBe("$0.0123");
  });

  it("fails if the unpriced renderer is mutated back to $0.00", () => {
    const rendered = formatRequestCostUsd(0, "unpriced");
    expect(rendered).not.toBe("$0.00");
    expect(rendered).not.toBe("$0.0000");
    expect(rendered).toBe("$ unknown");
  });
});

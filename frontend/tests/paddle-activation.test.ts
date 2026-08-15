/**
 * The plan flip is driven by Paddle's subscription webhooks, which land seconds AFTER
 * the buyer sees "transaction completed".
 *
 * Observed in production 2026-08-15: a real payment succeeded, the checkout overlay
 * said so, and the dashboard kept showing "Free" until BillingContext's 60s poll
 * happened to fire. The buyer got no acknowledgement at all. The first fix used a
 * fixed 0/2/5/10/20/30s ladder; a live Cloud→Teams upgrade then flipped on the LAST
 * rung, so the real lag reached ~30s with no margin left. Hence polling until the plan
 * actually reads back as the one purchased.
 */
import { describe, expect, it } from "vitest";
import { CheckoutEventNames } from "@paddle/paddle-js";

import { activationPollDone, isActivationEvent } from "@/lib/hooks/usePaddleCheckout";

describe("isActivationEvent", () => {
  it("is true only for checkout.completed", () => {
    expect(isActivationEvent(CheckoutEventNames.CHECKOUT_COMPLETED)).toBe(true);
    for (const name of Object.values(CheckoutEventNames)) {
      if (name === CheckoutEventNames.CHECKOUT_COMPLETED) continue;
      expect(isActivationEvent(name)).toBe(false);
    }
  });

  it("matches the wire value Paddle actually sends", () => {
    // Guards a rename/typo drifting the guard away from the real event string.
    expect(isActivationEvent("checkout.completed")).toBe(true);
    expect(isActivationEvent(undefined)).toBe(false);
  });
});

describe("activationPollDone", () => {
  it("keeps polling while the webhook has not landed yet", () => {
    expect(activationPollDone("free", "cloud", 0)).toBe(false);
    expect(activationPollDone("free", "cloud", 30_000)).toBe(false);
    // The old fixed ladder gave up here. The real lag reached ~30s, so anything that
    // stops at 30s has no margin.
    expect(activationPollDone("free", "cloud", 45_000)).toBe(false);
  });

  it("stops once the plan reads back as the one purchased", () => {
    expect(activationPollDone("cloud", "cloud", 4_000)).toBe(true);
    expect(activationPollDone("Cloud", "cloud", 4_000)).toBe(true);
  });

  it("stops on a Cloud->Teams upgrade only when Teams arrives", () => {
    // The regression the target-plan comparison exists for: the pre-checkout plan is
    // already paid, so "plan is not free" would have declared victory immediately.
    expect(activationPollDone("cloud", "teams", 2_000)).toBe(false);
    expect(activationPollDone("teams", "teams", 2_000)).toBe(true);
  });

  it("gives up eventually rather than polling a dead webhook forever", () => {
    expect(activationPollDone("free", "cloud", 180_000)).toBe(true);
  });

  it("treats an unloaded billing summary as not settled", () => {
    expect(activationPollDone(undefined, "cloud", 2_000)).toBe(false);
  });
});

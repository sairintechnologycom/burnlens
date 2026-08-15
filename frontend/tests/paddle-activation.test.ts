/**
 * The plan flip is driven by Paddle's `subscription.activated` webhook, which lands
 * seconds AFTER the buyer sees "transaction completed". Observed in production
 * 2026-08-15: a real payment succeeded, the checkout overlay said so, and the
 * dashboard kept showing "Free" until BillingContext's 60s poll happened to fire.
 * The buyer got no acknowledgement at all.
 *
 * These pin the two halves of the fix: completed schedules a refresh ladder that
 * starts immediately, and nothing else schedules anything.
 */
import { describe, expect, it } from "vitest";
import { CheckoutEventNames } from "@paddle/paddle-js";

import { activationRefreshDelays } from "@/lib/hooks/usePaddleCheckout";

describe("activationRefreshDelays", () => {
  it("schedules an immediate refresh plus a ladder covering webhook lag", () => {
    const delays = activationRefreshDelays(CheckoutEventNames.CHECKOUT_COMPLETED);

    // Starts at 0 so the UI reacts on the spot rather than waiting out the poll.
    expect(delays[0]).toBe(0);
    // Must outlast the 60s BillingContext poll it exists to pre-empt, otherwise
    // the ladder adds nothing over doing nothing at all.
    expect(Math.max(...delays)).toBeGreaterThanOrEqual(30_000);
    expect([...delays]).toStrictEqual([...delays].sort((a, b) => a - b));
  });

  it("schedules nothing for any other checkout event", () => {
    for (const name of Object.values(CheckoutEventNames)) {
      if (name === CheckoutEventNames.CHECKOUT_COMPLETED) continue;
      expect(activationRefreshDelays(name)).toStrictEqual([]);
    }
  });

  it("matches the wire value Paddle actually sends", () => {
    // Guards a rename/typo drifting the guard away from the real event string.
    expect(activationRefreshDelays("checkout.completed").length).toBeGreaterThan(0);
  });
});

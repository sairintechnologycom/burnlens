import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRateLimiter } from "@/lib/support/rate-limit";

describe("createRateLimiter", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-17T00:00:00Z"));
  });

  it("allows up to `limit` requests per window per key", () => {
    const rl = createRateLimiter({ limit: 3, windowMs: 60_000 });
    expect(rl.check("1.1.1.1").allowed).toBe(true);
    expect(rl.check("1.1.1.1").allowed).toBe(true);
    expect(rl.check("1.1.1.1").allowed).toBe(true);
    expect(rl.check("1.1.1.1").allowed).toBe(false);
  });

  it("tracks keys independently", () => {
    const rl = createRateLimiter({ limit: 1, windowMs: 60_000 });
    expect(rl.check("1.1.1.1").allowed).toBe(true);
    expect(rl.check("2.2.2.2").allowed).toBe(true);
    expect(rl.check("1.1.1.1").allowed).toBe(false);
  });

  it("resets after the window elapses", () => {
    const rl = createRateLimiter({ limit: 1, windowMs: 60_000 });
    expect(rl.check("1.1.1.1").allowed).toBe(true);
    expect(rl.check("1.1.1.1").allowed).toBe(false);
    vi.advanceTimersByTime(61_000);
    expect(rl.check("1.1.1.1").allowed).toBe(true);
  });

  it("returns retryAfterSeconds when blocked", () => {
    const rl = createRateLimiter({ limit: 1, windowMs: 60_000 });
    rl.check("1.1.1.1");
    const res = rl.check("1.1.1.1");
    expect(res.allowed).toBe(false);
    expect(res.retryAfterSeconds).toBeGreaterThan(0);
    expect(res.retryAfterSeconds).toBeLessThanOrEqual(60);
  });
});

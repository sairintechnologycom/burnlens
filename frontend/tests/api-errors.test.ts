/**
 * apiFetch's error paths: the 402 body, and the message every other failure
 * surfaces.
 *
 * FastAPI serialises `HTTPException(402, detail={...})` as `{"detail": {...}}`,
 * so the backend's `required_plan` / `limit` / `required_feature` sit one level
 * below where every consumer reads them. That made `err.data.required_plan`
 * undefined everywhere — LockedPanel fell back to default copy and the API-keys
 * cap message could not name the limit. Silent, because a fallback always
 * rendered something plausible.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

process.env.NEXT_PUBLIC_API_URL = "https://api.example.test";

const { apiFetch, PaymentRequiredError, errorMessageFrom } = await import("@/lib/api");

function respond402(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      status: 402,
      ok: false,
      json: async () => body,
    })),
  );
}

describe("apiFetch 402", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("unwraps FastAPI's detail envelope", async () => {
    respond402({
      detail: {
        error: "api_key_limit_reached",
        limit: 1,
        current: 1,
        required_plan: "cloud",
      },
    });

    const err = await apiFetch("/account/api-keys", "tok", { method: "POST" }).catch(
      (e) => e,
    );

    expect(err).toBeInstanceOf(PaymentRequiredError);
    expect(err.data.limit).toBe(1);
    expect(err.data.required_plan).toBe("cloud");
    expect(err.data.error).toBe("api_key_limit_reached");
  });

  it("passes a flat body through unchanged", async () => {
    respond402({ error: "feature_not_in_plan", required_feature: "teams_view" });

    const err = await apiFetch("/api/v1/usage/by-tag", "tok").catch((e) => e);

    expect(err.data.required_feature).toBe("teams_view");
  });

  it("does not treat a string detail as the payload", async () => {
    respond402({ detail: "Payment required" });

    const err = await apiFetch("/api/v1/usage/by-tag", "tok").catch((e) => e);

    // No structured fields to read; consumers fall back to default copy rather
    // than reading characters off a string.
    expect(err.data.required_plan).toBeUndefined();
  });

  it("survives a body that is not JSON at all", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        status: 402,
        ok: false,
        json: async () => {
          throw new Error("not json");
        },
      })),
    );

    const err = await apiFetch("/api/v1/usage/by-tag", "tok").catch((e) => e);

    expect(err).toBeInstanceOf(PaymentRequiredError);
    expect(err.data).toEqual({});
  });
});

/**
 * Non-402 error bodies. `err.message` is rendered directly in ~10 places, so
 * every FastAPI detail shape — string, object, 422 array — has to come out as
 * a readable sentence rather than `[object Object]`.
 */
describe("errorMessageFrom", () => {
  it("uses a plain string detail", () => {
    expect(errorMessageFrom({ detail: "Workspace not found" }, 404)).toBe(
      "Workspace not found",
    );
  });

  it("names the field on a 422 validation array", () => {
    const body = {
      detail: [
        { loc: ["body", "name"], msg: "field required", type: "value_error.missing" },
        { loc: ["body", "days"], msg: "must be positive", type: "value_error" },
      ],
    };
    expect(errorMessageFrom(body, 422)).toBe(
      "name: field required; days: must be positive",
    );
  });

  it("reads a message out of a structured detail instead of stringifying it", () => {
    const body = { detail: { error: "quota_exceeded", message: "Monthly cap reached" } };
    expect(errorMessageFrom(body, 429)).toBe("Monthly cap reached");
  });

  it("falls back to the error code when a structured detail has no message", () => {
    expect(errorMessageFrom({ detail: { error: "quota_exceeded" } }, 429)).toBe(
      "quota_exceeded",
    );
  });

  it("never leaks a serialised object", () => {
    const shapes: unknown[] = [
      { detail: { limit: 1, current: 1 } },
      { detail: [] },
      { detail: [{ type: "value_error" }] },
      { detail: "" },
      {},
      null,
      "a plain string body",
    ];
    for (const body of shapes) {
      const msg = errorMessageFrom(body, 500);
      expect(msg).not.toContain("[object Object]");
      expect(msg).toBe("Request failed (500)");
    }
  });

  it("is what apiFetch throws on a non-JSON error page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        status: 502,
        ok: false,
        json: async () => {
          throw new Error("not json");
        },
      })),
    );

    const err = await apiFetch("/api/v1/usage/summary", "tok").catch((e) => e);

    // The old code swallowed the status here and said only "Unknown error".
    expect(err.message).toBe("Request failed (502)");
  });
});

import { describe, expect, it } from "vitest";
import { searchChunks, tokenize } from "@/lib/support/retrieval";
import type { Chunk } from "@/lib/support/types";

const chunks: Chunk[] = [
  {
    id: "a",
    source: "README.md",
    heading: "Installation",
    url: "https://example/README.md#installation",
    text: "Run pip install burnlens to install the proxy.",
  },
  {
    id: "b",
    source: "support-knowledge/faq.md",
    heading: "Why $0 cost?",
    url: "https://burnlens.app/faq#why-0-cost",
    text: "Either the model is not in the pricing JSON or streaming did not return usage.",
  },
  {
    id: "c",
    source: "docs/PROVIDERS.md",
    heading: "Supported Providers",
    url: "https://example/docs/PROVIDERS.md#supported-providers",
    text: "OpenAI, Anthropic, Google Gemini are supported.",
  },
];

describe("tokenize", () => {
  it("lowercases and splits on non-word characters", () => {
    expect(tokenize("How do I install BurnLens?")).toEqual(["how", "do", "install", "burnlens"]);
  });
  it("drops stop words and short tokens", () => {
    expect(tokenize("a an the of in")).toEqual([]);
  });
  it("keeps inline code tokens", () => {
    expect(tokenize("Run pip install")).toEqual(["run", "pip", "install"]);
  });
});

describe("searchChunks", () => {
  it("returns the best-matching chunk first", () => {
    const r = searchChunks("how do I install", chunks, 3);
    expect(r.length).toBeGreaterThan(0);
    expect(r[0].chunk.id).toBe("a");
  });

  it("weights heading matches higher than body matches", () => {
    const r = searchChunks("installation", chunks, 3);
    expect(r[0].chunk.heading).toBe("Installation");
    expect(r[0].score).toBeGreaterThan(0);
  });

  it("returns at most k results", () => {
    expect(searchChunks("install", chunks, 1)).toHaveLength(1);
  });

  it("returns empty array when nothing matches", () => {
    expect(searchChunks("xyznever", chunks, 3)).toEqual([]);
  });

  it("matches across heading and body for multi-word queries", () => {
    const r = searchChunks("supported providers openai", chunks, 3);
    expect(r[0].chunk.id).toBe("c");
  });

  it("handles empty query gracefully", () => {
    expect(searchChunks("", chunks, 3)).toEqual([]);
  });

  it("is case-insensitive", () => {
    const lower = searchChunks("install", chunks, 3);
    const upper = searchChunks("INSTALL", chunks, 3);
    expect(upper.map((r) => r.chunk.id)).toEqual(lower.map((r) => r.chunk.id));
  });
});

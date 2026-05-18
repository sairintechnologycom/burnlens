import { describe, expect, it } from "vitest";
import { cosineSimilarity, topK } from "@/lib/support/retrieval";
import type { IndexedChunk } from "@/lib/support/types";

describe("cosineSimilarity", () => {
  it("returns 1 for identical vectors", () => {
    expect(cosineSimilarity([1, 0, 0], [1, 0, 0])).toBeCloseTo(1, 5);
  });
  it("returns 0 for orthogonal vectors", () => {
    expect(cosineSimilarity([1, 0], [0, 1])).toBeCloseTo(0, 5);
  });
  it("returns -1 for opposing vectors", () => {
    expect(cosineSimilarity([1, 0], [-1, 0])).toBeCloseTo(-1, 5);
  });
  it("throws if dimensions differ", () => {
    expect(() => cosineSimilarity([1, 0], [1, 0, 0])).toThrow();
  });
});

describe("topK", () => {
  const chunks: IndexedChunk[] = [
    { id: "a", source: "x", heading: "A", url: "", text: "alpha", embedding: [1, 0, 0] },
    { id: "b", source: "x", heading: "B", url: "", text: "beta",  embedding: [0, 1, 0] },
    { id: "c", source: "x", heading: "C", url: "", text: "gamma", embedding: [0.9, 0.1, 0] },
  ];
  it("returns k highest-scoring chunks in order", () => {
    const r = topK([1, 0, 0], chunks, 2);
    expect(r.map((x) => x.chunk.id)).toEqual(["a", "c"]);
    expect(r[0].score).toBeGreaterThan(r[1].score);
  });
  it("returns all chunks if k > available", () => {
    expect(topK([1, 0, 0], chunks, 10)).toHaveLength(3);
  });
  it("returns empty array for k=0", () => {
    expect(topK([1, 0, 0], chunks, 0)).toEqual([]);
  });
});

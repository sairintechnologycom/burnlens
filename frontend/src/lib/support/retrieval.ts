import type { IndexedChunk } from "./types";

export function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length !== b.length) {
    throw new Error(`Vector dimension mismatch: ${a.length} vs ${b.length}`);
  }
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  const denom = Math.sqrt(na) * Math.sqrt(nb);
  return denom === 0 ? 0 : dot / denom;
}

export interface ScoredChunk {
  chunk: IndexedChunk;
  score: number;
}

export function topK(
  query: number[],
  chunks: IndexedChunk[],
  k: number
): ScoredChunk[] {
  if (k <= 0) return [];
  const scored = chunks.map((chunk) => ({
    chunk,
    score: cosineSimilarity(query, chunk.embedding),
  }));
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, k);
}

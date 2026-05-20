import type { Chunk, SearchResult } from "./types";

const STOP_WORDS = new Set([
  "a", "an", "the", "of", "in", "on", "at", "to", "for", "is", "are", "be",
  "and", "or", "but", "if", "i", "it", "its", "as", "by", "with", "from",
  "this", "that", "these", "those", "my", "your", "our",
]);

export function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9_$]+/)
    .filter((t) => t.length >= 2 && !STOP_WORDS.has(t));
}

function scoreChunk(chunk: Chunk, queryTokens: string[]): number {
  if (queryTokens.length === 0) return 0;
  const heading = chunk.heading.toLowerCase();
  const text = chunk.text.toLowerCase();
  let score = 0;
  for (const token of queryTokens) {
    if (heading.includes(token)) score += 4;
    const wordBoundary = new RegExp(`\\b${escapeRegex(token)}\\b`);
    if (wordBoundary.test(heading)) score += 2;
    let bodyMatches = 0;
    const re = new RegExp(escapeRegex(token), "g");
    bodyMatches = (text.match(re) || []).length;
    score += Math.min(bodyMatches, 3);
    if (wordBoundary.test(text)) score += 1;
  }
  return score;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function searchChunks(
  query: string,
  chunks: Chunk[],
  k: number
): SearchResult[] {
  const tokens = tokenize(query);
  if (tokens.length === 0 || k <= 0) return [];
  const scored: SearchResult[] = [];
  for (const chunk of chunks) {
    const score = scoreChunk(chunk, tokens);
    if (score > 0) scored.push({ chunk, score });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, k);
}

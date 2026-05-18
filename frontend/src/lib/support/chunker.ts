import { createHash } from "node:crypto";
import type { Chunk } from "./types";

interface SourceMeta {
  source: string;
  baseUrl: string;
}

interface ChunkOptions {
  maxChars: number;
}

function slugify(heading: string): string {
  return heading
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function stripFences(body: string): string {
  return body.replace(/```[\s\S]*?```/g, "").trim();
}

function splitOversized(text: string, maxChars: number): string[] {
  if (text.length <= maxChars) return [text];
  const out: string[] = [];
  let i = 0;
  while (i < text.length) {
    out.push(text.slice(i, i + maxChars));
    i += maxChars;
  }
  return out;
}

const HEADING_RE = /^#{1,6}\s+(.*)$/;

export function chunkMarkdown(
  md: string,
  meta: SourceMeta,
  opts: ChunkOptions
): Chunk[] {
  const lines = md.split("\n");
  const sections: { heading: string; body: string[] }[] = [];
  let current: { heading: string; body: string[] } | null = null;

  for (const line of lines) {
    const m = line.match(HEADING_RE);
    if (m) {
      if (current) sections.push(current);
      current = { heading: m[1].trim(), body: [] };
    } else if (current) {
      current.body.push(line);
    }
  }
  if (current) sections.push(current);

  const chunks: Chunk[] = [];
  for (const sec of sections) {
    const cleaned = stripFences(sec.body.join("\n")).replace(/\n{3,}/g, "\n\n").trim();
    if (!cleaned) continue;
    const parts = splitOversized(cleaned, opts.maxChars);
    const slug = slugify(sec.heading);
    parts.forEach((text, i) => {
      const hash = createHash("sha1")
        .update(`${meta.source}|${slug}|${i}|${text}`)
        .digest("hex")
        .slice(0, 12);
      chunks.push({
        id: `${meta.source}#${slug}-${i}-${hash}`,
        source: meta.source,
        heading: sec.heading,
        url: `${meta.baseUrl}#${slug}`,
        text,
      });
    });
  }
  return chunks;
}

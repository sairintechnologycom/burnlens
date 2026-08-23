import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { chunkMarkdown } from "../src/lib/support/chunker";
import { CHUNK_MAX_CHARS, SUPPORT_SOURCES } from "../src/lib/support/sources";
import type { Chunk, SupportIndex } from "../src/lib/support/types";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const frontendRoot = resolve(here, "..");
const outPath = resolve(frontendRoot, "src/lib/support/index.json");

async function loadChunks(): Promise<{ chunks: Chunk[]; missingSources: string[] }> {
  const all: Chunk[] = [];
  const missingSources: string[] = [];
  for (const src of SUPPORT_SOURCES) {
    let md: string;
    try {
      md = await readFile(resolve(repoRoot, src.path), "utf8");
    } catch {
      console.warn(`[build-support-index] skipping missing source: ${src.path}`);
      missingSources.push(src.path);
      continue;
    }
    const chunks = chunkMarkdown(
      md,
      { source: src.source, baseUrl: src.baseUrl },
      { maxChars: CHUNK_MAX_CHARS }
    );
    console.log(`[build-support-index] ${src.source}: ${chunks.length} chunks`);
    all.push(...chunks);
  }
  return { chunks: all, missingSources };
}

async function main() {
  const { chunks, missingSources } = await loadChunks();
  if (missingSources.length > 0) {
    // Vercel's monorepo root can omit files outside the configured frontend
    // directory. Keep the complete, reviewed index generated in CI/local
    // builds instead of silently replacing it with a partial knowledge base.
    const committed = JSON.parse(await readFile(outPath, "utf8")) as SupportIndex;
    if (!committed.chunks.length) {
      throw new Error("Support sources are missing and the committed index is empty");
    }
    console.warn(
      `[build-support-index] preserving committed index (${committed.chunks.length} chunks); ` +
        `${missingSources.length} source(s) unavailable in this build environment`
    );
    return;
  }
  if (chunks.length === 0) throw new Error("No chunks produced — nothing to index");

  // Rewriting on every build stamps a new generatedAt and dirties the tree even
  // when nothing changed. Developers then revert the churn — which is how the
  // index went stale for 16 days. Only write when the chunks actually differ.
  const existing = await readFile(outPath, "utf8").catch(() => null);
  if (existing) {
    const committed = JSON.parse(existing) as SupportIndex;
    if (JSON.stringify(committed.chunks) === JSON.stringify(chunks)) {
      console.log(`[build-support-index] index already current (${chunks.length} chunks)`);
      return;
    }
  }

  const out: SupportIndex = {
    generatedAt: new Date().toISOString(),
    chunks,
  };
  await mkdir(dirname(outPath), { recursive: true });
  await writeFile(outPath, JSON.stringify(out));
  console.log(`[build-support-index] wrote ${basename(outPath)} (${chunks.length} chunks)`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { chunkMarkdown } from "../src/lib/support/chunker";
import type { Chunk, SupportIndex } from "../src/lib/support/types";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const frontendRoot = resolve(here, "..");
const outPath = resolve(frontendRoot, "src/lib/support/index.json");

const CHUNK_MAX_CHARS = 1200;

interface Source {
  absPath: string;
  source: string;
  baseUrl: string;
}

const sources: Source[] = [
  {
    absPath: resolve(repoRoot, "README.md"),
    source: "README.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/README.md",
  },
  {
    absPath: resolve(repoRoot, "docs/PROVIDERS.md"),
    source: "docs/PROVIDERS.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/docs/PROVIDERS.md",
  },
  {
    absPath: resolve(repoRoot, "docs/KEY_ROTATION_RUNBOOK.md"),
    source: "docs/KEY_ROTATION_RUNBOOK.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/docs/KEY_ROTATION_RUNBOOK.md",
  },
  {
    absPath: resolve(frontendRoot, "support-knowledge/faq.md"),
    source: "support-knowledge/faq.md",
    baseUrl: "https://burnlens.app/faq",
  },
  {
    absPath: resolve(frontendRoot, "support-knowledge/troubleshooting.md"),
    source: "support-knowledge/troubleshooting.md",
    baseUrl: "https://burnlens.app/troubleshooting",
  },
];

async function loadChunks(): Promise<Chunk[]> {
  const all: Chunk[] = [];
  for (const src of sources) {
    let md: string;
    try {
      md = await readFile(src.absPath, "utf8");
    } catch {
      console.warn(`[build-support-index] skipping missing source: ${src.absPath}`);
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
  return all;
}

async function main() {
  const chunks = await loadChunks();
  if (chunks.length === 0) throw new Error("No chunks produced — nothing to index");

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

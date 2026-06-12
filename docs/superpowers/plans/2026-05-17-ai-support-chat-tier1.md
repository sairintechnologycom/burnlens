# AI Support Chat (Tier 1 — Docs RAG) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a public AI support chat widget on burnlens.app that answers user questions from a build-time index of BurnLens docs, README, and a hand-written support FAQ — with citations and a "still stuck → email support" escape hatch.

**Architecture:** Build-time TypeScript indexer reads markdown sources, splits into chunks, embeds via OpenAI text-embedding-3-small through the Vercel AI Gateway, and writes a static JSON vector index shipped with the Next.js build. A Route Handler at `/api/support-chat` accepts a user message, embeds it, picks the top-K chunks by cosine similarity, and streams a grounded reply via AI Gateway (anthropic/claude-haiku-4-5). A floating `<SupportChat />` widget mounts globally in `layout.tsx` and renders a panel with streaming responses, citation pills, and a feedback row. Rate limiting is per-IP in-memory (Fluid Compute warm instances — sufficient for Tier 1; upgrade to Vercel KV in Tier 2).

**Tech Stack:**
- Next.js 16.2.4 App Router Route Handlers (Web Request/Response)
- Vercel AI SDK v6 (`ai` package) + Vercel AI Gateway (no direct provider packages)
- OpenAI text-embedding-3-small (via Gateway) for embeddings
- anthropic/claude-haiku-4-5 (via Gateway) for answers
- Pure TypeScript cosine similarity (no vector DB for Tier 1)
- Tailwind + existing BurnLens components (ToastProvider, theme tokens)
- Playwright for E2E

**Non-goals for Tier 1:**
- No authentication, no per-user history, no Tier 2 diagnostic tool calls
- No Vercel KV/Redis (use in-memory rate limiter)
- No analytics dashboard for low-rated answers (just structured stdout logging)
- Not embedded in the dashboard yet — public marketing site only

---

## File Structure

**Create:**
- `frontend/support-knowledge/faq.md` — hand-curated answers to known issues
- `frontend/support-knowledge/troubleshooting.md` — error-code lookup table
- `frontend/scripts/build-support-index.ts` — Node script: reads markdown, chunks, embeds, writes JSON
- `frontend/src/lib/support/chunker.ts` — pure function: markdown → `Chunk[]`
- `frontend/src/lib/support/retrieval.ts` — cosine similarity + top-K
- `frontend/src/lib/support/rate-limit.ts` — per-IP token bucket
- `frontend/src/lib/support/answer.ts` — prompt builder + citation formatter
- `frontend/src/lib/support/types.ts` — shared types
- `frontend/src/lib/support/index.json` — generated artifact (gitignored, built before next build)
- `frontend/src/app/api/support-chat/route.ts` — POST: streaming chat handler
- `frontend/src/app/api/support-feedback/route.ts` — POST: thumbs feedback logger
- `frontend/src/components/SupportChat.tsx` — floating button + panel client component
- `frontend/src/components/SupportChatMessages.tsx` — message list + citations + feedback row
- `frontend/tests/support/chunker.test.ts`
- `frontend/tests/support/retrieval.test.ts`
- `frontend/tests/support/rate-limit.test.ts`
- `frontend/tests/support/chat-route.test.ts`
- `frontend/tests/e2e/support-chat.spec.ts`
- `frontend/vitest.config.ts`
- `frontend/.env.local.example`

**Modify:**
- `frontend/package.json` — add `ai`, `vitest`, `tsx`; add `build:index` and `test` scripts
- `frontend/src/app/layout.tsx` — mount `<SupportChat />` inside `<ToastProvider>`
- `frontend/.gitignore` — ignore `src/lib/support/index.json`

**Source documents the indexer ingests (read-only):**
- `README.md` (project root)
- `docs/ARCHITECTURE.md`
- `docs/PROVIDERS.md`
- `docs/KEY_ROTATION_RUNBOOK.md`
- `frontend/support-knowledge/*.md`

---

## Task 1: Install dependencies and add env scaffolding

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/.env.local.example`
- Modify: `frontend/.gitignore`

- [ ] **Step 1: Install AI SDK + Vitest + tsx**

Run: `cd frontend && npm install ai@^6 && npm install -D vitest@^2 @vitest/coverage-v8@^2 tsx@^4`

- [ ] **Step 2: Replace `scripts` block in `frontend/package.json`**

```json
"scripts": {
  "dev": "next dev",
  "build:index": "tsx scripts/build-support-index.ts",
  "build": "npm run build:index && next build",
  "start": "next start",
  "lint": "eslint",
  "test": "vitest run",
  "test:watch": "vitest",
  "test:e2e": "npx playwright test",
  "test:e2e:ui": "npx playwright test --ui"
}
```

- [ ] **Step 3: Create `frontend/.env.local.example`**

```bash
AI_GATEWAY_API_KEY=
SUPPORT_CHAT_MODEL=anthropic/claude-haiku-4-5
SUPPORT_EMBED_MODEL=openai/text-embedding-3-small
SUPPORT_RATE_LIMIT_PER_MIN=15
SUPPORT_MAX_MESSAGE_CHARS=2000
```

- [ ] **Step 4: Append to `frontend/.gitignore`**

```
# Generated support chat vector index
src/lib/support/index.json
```

- [ ] **Step 5: Verify install**

Run: `cd frontend && npm run lint`. Expected: lint passes.

- [ ] **Step 6: Commit**

```
git add frontend/package.json frontend/package-lock.json frontend/.gitignore frontend/.env.local.example
git commit -m "chore(support-chat): add ai sdk + vitest + env scaffolding"
```

---

## Task 2: Vitest config

**Files:**
- Create: `frontend/vitest.config.ts`

- [ ] **Step 1: Create the config**

```ts
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    exclude: ["tests/e2e/**", "node_modules/**"],
    coverage: { provider: "v8", reporter: ["text", "html"] },
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
});
```

- [ ] **Step 2: Smoke-test Vitest runs**

Run: `cd frontend && npm test`. Expected: `No test files found` (exit 0) — confirms Vitest is wired.

- [ ] **Step 3: Commit**

```
git add frontend/vitest.config.ts
git commit -m "chore(support-chat): add vitest config with @ alias"
```

---

## Task 3: Shared types

**Files:**
- Create: `frontend/src/lib/support/types.ts`

- [ ] **Step 1: Create**

```ts
export interface Chunk {
  id: string;
  source: string;
  heading: string;
  url: string;
  text: string;
}

export interface IndexedChunk extends Chunk {
  embedding: number[];
}

export interface SupportIndex {
  generatedAt: string;
  embedModel: string;
  dimension: number;
  chunks: IndexedChunk[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: { source: string; heading: string; url: string }[];
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/lib/support/types.ts
git commit -m "feat(support-chat): add shared types"
```

---

## Task 4: Markdown chunker (TDD)

**Files:**
- Create: `frontend/tests/support/chunker.test.ts`
- Create: `frontend/src/lib/support/chunker.ts`

- [ ] **Step 1: Write failing tests**

```ts
import { describe, expect, it } from "vitest";
import { chunkMarkdown } from "@/lib/support/chunker";

describe("chunkMarkdown", () => {
  const meta = { source: "README.md", baseUrl: "https://example.com/README.md" };

  it("emits one chunk per heading section under the size cap", () => {
    const md = `# Install\n\nRun pip install burnlens.\n\n# Usage\n\nStart it.\n`;
    const chunks = chunkMarkdown(md, meta, { maxChars: 1000 });
    expect(chunks).toHaveLength(2);
    expect(chunks[0].heading).toBe("Install");
    expect(chunks[0].text).toContain("pip install");
    expect(chunks[1].heading).toBe("Usage");
  });

  it("splits a section larger than maxChars into multiple chunks", () => {
    const body = "x".repeat(2500);
    const md = `# Long\n\n${body}\n`;
    const chunks = chunkMarkdown(md, meta, { maxChars: 1000 });
    expect(chunks.length).toBeGreaterThanOrEqual(3);
    expect(chunks.every((c) => c.heading === "Long")).toBe(true);
  });

  it("builds anchor-friendly URLs from headings", () => {
    const md = `## Key Rotation Runbook\n\nSteps here.\n`;
    const chunks = chunkMarkdown(md, meta, { maxChars: 1000 });
    expect(chunks[0].url).toBe("https://example.com/README.md#key-rotation-runbook");
  });

  it("produces stable ids across runs", () => {
    const md = `# A\n\nbody one\n\n# B\n\nbody two\n`;
    const a = chunkMarkdown(md, meta, { maxChars: 1000 });
    const b = chunkMarkdown(md, meta, { maxChars: 1000 });
    expect(a.map((c) => c.id)).toEqual(b.map((c) => c.id));
  });

  it("strips code fences but preserves inline code", () => {
    const md = "# Code\n\nUse `burnlens start`.\n\n```bash\nlong code\n```\n";
    const chunks = chunkMarkdown(md, meta, { maxChars: 1000 });
    expect(chunks[0].text).toContain("burnlens start");
    expect(chunks[0].text).not.toContain("long code");
  });

  it("ignores empty sections", () => {
    const md = `# Empty\n\n# Real\n\nhas content\n`;
    const chunks = chunkMarkdown(md, meta, { maxChars: 1000 });
    expect(chunks).toHaveLength(1);
    expect(chunks[0].heading).toBe("Real");
  });
});
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `cd frontend && npm test -- chunker`. Expected: all fail with `Cannot find module '@/lib/support/chunker'`.

- [ ] **Step 3: Implement**

```ts
import { createHash } from "node:crypto";
import type { Chunk } from "./types";

interface SourceMeta { source: string; baseUrl: string; }
interface ChunkOptions { maxChars: number; }

function slugify(heading: string): string {
  return heading.toLowerCase().replace(/[^a-z0-9\s-]/g, "").trim().replace(/\s+/g, "-");
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

export function chunkMarkdown(md: string, meta: SourceMeta, opts: ChunkOptions): Chunk[] {
  const lines = md.split("\n");
  const sections: { heading: string; body: string[] }[] = [];
  let current: { heading: string; body: string[] } | null = null;

  for (const line of lines) {
    const m = /^#{1,6}\s+(.*)$/.exec(line);
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
      const hash = createHash("sha1").update(`${meta.source}|${slug}|${i}|${text}`).digest("hex").slice(0, 12);
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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd frontend && npm test -- chunker`. Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```
git add frontend/src/lib/support/chunker.ts frontend/tests/support/chunker.test.ts
git commit -m "feat(support-chat): markdown chunker with stable ids"
```

---

## Task 5: Cosine similarity retrieval (TDD)

**Files:**
- Create: `frontend/tests/support/retrieval.test.ts`
- Create: `frontend/src/lib/support/retrieval.ts`

- [ ] **Step 1: Write failing tests**

```ts
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
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd frontend && npm test -- retrieval`. Expected: all fail.

- [ ] **Step 3: Implement**

```ts
import type { IndexedChunk } from "./types";

export function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length !== b.length) {
    throw new Error(`Vector dimension mismatch: ${a.length} vs ${b.length}`);
  }
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na  += a[i] * a[i];
    nb  += b[i] * b[i];
  }
  const denom = Math.sqrt(na) * Math.sqrt(nb);
  return denom === 0 ? 0 : dot / denom;
}

export interface ScoredChunk { chunk: IndexedChunk; score: number; }

export function topK(query: number[], chunks: IndexedChunk[], k: number): ScoredChunk[] {
  if (k <= 0) return [];
  const scored = chunks.map((chunk) => ({ chunk, score: cosineSimilarity(query, chunk.embedding) }));
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, k);
}
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd frontend && npm test -- retrieval`. Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```
git add frontend/src/lib/support/retrieval.ts frontend/tests/support/retrieval.test.ts
git commit -m "feat(support-chat): cosine similarity + topK retrieval"
```

---

## Task 6: Per-IP rate limiter (TDD)

**Files:**
- Create: `frontend/tests/support/rate-limit.test.ts`
- Create: `frontend/src/lib/support/rate-limit.ts`

- [ ] **Step 1: Write failing tests**

```ts
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
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd frontend && npm test -- rate-limit`.

- [ ] **Step 3: Implement**

```ts
interface RateLimiterOptions { limit: number; windowMs: number; }
export interface RateLimitResult { allowed: boolean; retryAfterSeconds: number; }
interface Bucket { count: number; resetAt: number; }

export function createRateLimiter(opts: RateLimiterOptions) {
  const buckets = new Map<string, Bucket>();
  return {
    check(key: string): RateLimitResult {
      const now = Date.now();
      const bucket = buckets.get(key);
      if (!bucket || bucket.resetAt <= now) {
        buckets.set(key, { count: 1, resetAt: now + opts.windowMs });
        return { allowed: true, retryAfterSeconds: 0 };
      }
      if (bucket.count < opts.limit) {
        bucket.count += 1;
        return { allowed: true, retryAfterSeconds: 0 };
      }
      return {
        allowed: false,
        retryAfterSeconds: Math.max(1, Math.ceil((bucket.resetAt - now) / 1000)),
      };
    },
  };
}
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd frontend && npm test -- rate-limit`. Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```
git add frontend/src/lib/support/rate-limit.ts frontend/tests/support/rate-limit.test.ts
git commit -m "feat(support-chat): per-ip in-memory rate limiter"
```

---

## Task 7: Hand-written support knowledge base

**Files:**
- Create: `frontend/support-knowledge/faq.md`
- Create: `frontend/support-knowledge/troubleshooting.md`

- [ ] **Step 1: Write `frontend/support-knowledge/faq.md`**

```markdown
# BurnLens Support FAQ

## How do I install BurnLens?

Run `pip install burnlens` (requires Python 3.10+). Start the proxy with `burnlens start`. The dashboard is at http://127.0.0.1:8420/ui.

## How do I point my SDK at BurnLens?

Set the provider's BASE_URL env var to the matching BurnLens proxy path:

- OpenAI: `OPENAI_BASE_URL=http://127.0.0.1:8420/proxy/openai`
- Anthropic: `ANTHROPIC_BASE_URL=http://127.0.0.1:8420/proxy/anthropic`
- Google: call `burnlens.patch()` in your code (Google SDK does not honor an env var)

Existing SDK code works unchanged.

## Why does the dashboard show $0 for my requests?

Either (a) the model is not in the pricing JSON for that provider (a warning is logged — open an issue with the model name), or (b) the request is streaming and the upstream response did not include a final usage block.

## My proxy will not start — port 8420 is in use.

Run `burnlens stop` to kill any running instance, or pass `--port 9000` to `burnlens start` and update your BASE_URL accordingly.

## Cloud sync is not pushing data to burnlens.app.

Three checks: (1) is your API key valid? Run `burnlens whoami`. (2) Is sync enabled in `~/.burnlens/config.yaml`? (3) Are you over plan quota? Free tier has limits — see the Plans page.

## How do I rotate my API key?

See the Key Rotation Runbook in the docs. TL;DR: create a new key in the dashboard, copy it into `~/.burnlens/config.yaml`, restart the proxy, then revoke the old key.

## My budget cap is not blocking requests.

Budget enforcement is per-API-key, not per-tag. Check the key's cap in the dashboard. Tag-level budgets only trigger alerts — they do not 429.

## Does BurnLens send my prompts to the cloud?

No. The local proxy logs prompts only to your local SQLite at `~/.burnlens/burnlens.db`. Cloud sync sends token counts, costs, tags, and SHA hashes only — never prompt or response content.

## How do I cancel my plan?

Account → Billing → Cancel. Cancellation takes effect at the end of the current billing period.

## What providers are supported?

Stable: OpenAI, Anthropic, Google Gemini. Roadmap (v0.2–v0.3): Azure OpenAI, AWS Bedrock, Groq, Together, Mistral.

## I am getting 429 errors from BurnLens but not from the upstream provider.

That is your hard cap firing. Either raise the cap on the API key in the dashboard, or wait for the daily window to reset (UTC midnight).
```

- [ ] **Step 2: Write `frontend/support-knowledge/troubleshooting.md`**

```markdown
# BurnLens Troubleshooting

## Error: "Plan limit exceeded"

Your account is over its monthly request, token, spend, or active-key quota. Upgrade your plan from Account → Billing, or wait for the next billing cycle. Open-source local proxy has no limits — quotas apply only to cloud sync.

## Error: "Invalid API key"

The key in `~/.burnlens/config.yaml` was revoked or never existed. Run `burnlens login` to set a new one.

## Error: "Upstream provider returned 401"

Your provider's own API key (OpenAI, Anthropic, etc.) is invalid or expired. BurnLens forwards your provider key unchanged — it does not store or rotate it.

## Streaming responses are buffered or slow

The proxy forwards SSE chunks immediately. If you see buffering, it is almost always your HTTP client. Set `stream=True` in your SDK call and read iteratively.

## Dashboard shows "no data" but I made requests

Check three things: (1) is the proxy actually running? `curl http://127.0.0.1:8420/health`. (2) Did your requests hit `/proxy/<provider>/...` (not the upstream URL directly)? (3) Did the request complete? Failed requests with no response body are recorded but show $0.

## CLI command not found after pip install

Your Python user-site bin is not on PATH. Either install into a virtualenv, or add `python3 -m site --user-base`/bin to your PATH.
```

- [ ] **Step 3: Commit**

```
git add frontend/support-knowledge/
git commit -m "docs(support-chat): seed FAQ and troubleshooting knowledge base"
```

---

## Task 8: Build-time index generator

**Files:**
- Create: `frontend/scripts/build-support-index.ts`

- [ ] **Step 1: Implement**

```ts
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { chunkMarkdown } from "../src/lib/support/chunker";
import type { Chunk, IndexedChunk, SupportIndex } from "../src/lib/support/types";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const frontendRoot = resolve(here, "..");
const outPath = resolve(frontendRoot, "src/lib/support/index.json");

const EMBED_MODEL = process.env.SUPPORT_EMBED_MODEL ?? "openai/text-embedding-3-small";
const GATEWAY_KEY = process.env.AI_GATEWAY_API_KEY;
const CHUNK_MAX_CHARS = 1200;

interface Source { absPath: string; source: string; baseUrl: string; }

const sources: Source[] = [
  { absPath: resolve(repoRoot, "README.md"), source: "README.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/README.md" },
  { absPath: resolve(repoRoot, "docs/ARCHITECTURE.md"), source: "docs/ARCHITECTURE.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/docs/ARCHITECTURE.md" },
  { absPath: resolve(repoRoot, "docs/PROVIDERS.md"), source: "docs/PROVIDERS.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/docs/PROVIDERS.md" },
  { absPath: resolve(repoRoot, "docs/KEY_ROTATION_RUNBOOK.md"), source: "docs/KEY_ROTATION_RUNBOOK.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/docs/KEY_ROTATION_RUNBOOK.md" },
  { absPath: resolve(frontendRoot, "support-knowledge/faq.md"), source: "support-knowledge/faq.md",
    baseUrl: "https://burnlens.app/faq" },
  { absPath: resolve(frontendRoot, "support-knowledge/troubleshooting.md"), source: "support-knowledge/troubleshooting.md",
    baseUrl: "https://burnlens.app/troubleshooting" },
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
    const chunks = chunkMarkdown(md, { source: src.source, baseUrl: src.baseUrl }, { maxChars: CHUNK_MAX_CHARS });
    console.log(`[build-support-index] ${src.source}: ${chunks.length} chunks`);
    all.push(...chunks);
  }
  return all;
}

async function embedBatch(texts: string[]): Promise<number[][]> {
  if (!GATEWAY_KEY) {
    throw new Error("AI_GATEWAY_API_KEY is required to build the support index");
  }
  const res = await fetch("https://ai-gateway.vercel.sh/v1/embeddings", {
    method: "POST",
    headers: { Authorization: `Bearer ${GATEWAY_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: EMBED_MODEL, input: texts }),
  });
  if (!res.ok) {
    throw new Error(`Embedding request failed: ${res.status} ${await res.text()}`);
  }
  const body = (await res.json()) as { data: { embedding: number[] }[] };
  return body.data.map((d) => d.embedding);
}

async function main() {
  const chunks = await loadChunks();
  if (chunks.length === 0) throw new Error("No chunks produced — nothing to index");

  const BATCH = 64;
  const indexed: IndexedChunk[] = [];
  for (let i = 0; i < chunks.length; i += BATCH) {
    const slice = chunks.slice(i, i + BATCH);
    const vectors = await embedBatch(slice.map((c) => `${c.heading}\n\n${c.text}`));
    for (let j = 0; j < slice.length; j++) {
      indexed.push({ ...slice[j], embedding: vectors[j] });
    }
    console.log(`[build-support-index] embedded ${indexed.length}/${chunks.length}`);
  }

  const out: SupportIndex = {
    generatedAt: new Date().toISOString(),
    embedModel: EMBED_MODEL,
    dimension: indexed[0].embedding.length,
    chunks: indexed,
  };
  await mkdir(dirname(outPath), { recursive: true });
  await writeFile(outPath, JSON.stringify(out));
  console.log(`[build-support-index] wrote ${basename(outPath)} (${indexed.length} chunks, dim=${out.dimension})`);
}

main().catch((err) => { console.error(err); process.exit(1); });
```

- [ ] **Step 2: Run it locally with the gateway key**

Run: `cd frontend && AI_GATEWAY_API_KEY=$AI_GATEWAY_API_KEY npm run build:index`

Expected: prints chunk counts per source, then `wrote index.json (N chunks, dim=1536)`. Confirms `src/lib/support/index.json` exists. If `AI_GATEWAY_API_KEY` is not set locally, add it to `frontend/.env.local` first.

- [ ] **Step 3: Commit (script only — index is gitignored)**

```
git add frontend/scripts/build-support-index.ts
git commit -m "feat(support-chat): build-time vector index generator"
```

---

## Task 9: Prompt builder + citation formatter (TDD)

**Files:**
- Create: `frontend/tests/support/chat-route.test.ts`
- Create: `frontend/src/lib/support/answer.ts`

- [ ] **Step 1: Write failing tests**

```ts
import { describe, expect, it } from "vitest";
import { buildSupportPrompt, formatCitations } from "@/lib/support/answer";
import type { IndexedChunk } from "@/lib/support/types";

const chunks: IndexedChunk[] = [
  { id: "a", source: "README.md", heading: "Install",
    url: "https://example/README.md#install",
    text: "Run pip install burnlens then burnlens start.",
    embedding: [1, 0, 0] },
  { id: "b", source: "support-knowledge/faq.md", heading: "Why $0?",
    url: "https://burnlens.app/faq#why-0",
    text: "Model not in pricing JSON. Cost shows $0.",
    embedding: [0, 1, 0] },
];

describe("buildSupportPrompt", () => {
  it("places the user question last", () => {
    const { messages } = buildSupportPrompt("How do I install?", chunks);
    const last = messages[messages.length - 1];
    expect(last.role).toBe("user");
    expect(last.content).toContain("How do I install?");
  });

  it("embeds retrieved chunks as numbered context blocks", () => {
    const { messages } = buildSupportPrompt("anything", chunks);
    const system = messages[0].content;
    expect(system).toContain("[1] README.md — Install");
    expect(system).toContain("Run pip install");
    expect(system).toContain("[2] support-knowledge/faq.md — Why $0?");
  });

  it("instructs the model to cite by [n]", () => {
    const { messages } = buildSupportPrompt("anything", chunks);
    expect(messages[0].content).toMatch(/cite.*\[/i);
  });

  it("tells the model to escalate if context is insufficient", () => {
    const { messages } = buildSupportPrompt("anything", chunks);
    expect(messages[0].content.toLowerCase()).toContain("support@burnlens.app");
  });
});

describe("formatCitations", () => {
  it("returns one citation per unique source heading in retrieval order", () => {
    const cites = formatCitations(chunks);
    expect(cites).toEqual([
      { source: "README.md", heading: "Install", url: "https://example/README.md#install" },
      { source: "support-knowledge/faq.md", heading: "Why $0?", url: "https://burnlens.app/faq#why-0" },
    ]);
  });

  it("de-duplicates identical citations", () => {
    const dup = [...chunks, chunks[0]];
    expect(formatCitations(dup)).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd frontend && npm test -- chat-route`.

- [ ] **Step 3: Implement**

```ts
import type { IndexedChunk } from "./types";

interface ChatRoleMessage { role: "system" | "user"; content: string; }

const SYSTEM_TEMPLATE = (contextBlock: string) =>
  `You are BurnLens Support, an assistant for an open-source LLM FinOps proxy (https://burnlens.app).

Answer the user's question using ONLY the context below. Cite sources inline using [1], [2], etc. matching the numbered context blocks.

If the context does not contain enough information to answer confidently, say so plainly and direct the user to email support@burnlens.app with their question. Do not invent commands, env vars, plan names, pricing, or features that are not in the context.

Keep answers concise: 1-4 short paragraphs or a short list. Use code blocks for commands and env vars.

=== CONTEXT ===
${contextBlock}
=== END CONTEXT ===`;

export function buildSupportPrompt(
  userQuestion: string,
  retrieved: IndexedChunk[]
): { messages: ChatRoleMessage[] } {
  const contextBlock = retrieved
    .map((c, i) => `[${i + 1}] ${c.source} — ${c.heading}\n${c.text}`)
    .join("\n\n");
  return {
    messages: [
      { role: "system", content: SYSTEM_TEMPLATE(contextBlock) },
      { role: "user", content: userQuestion },
    ],
  };
}

export function formatCitations(retrieved: IndexedChunk[]) {
  const seen = new Set<string>();
  const out: { source: string; heading: string; url: string }[] = [];
  for (const c of retrieved) {
    const key = `${c.source}#${c.heading}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ source: c.source, heading: c.heading, url: c.url });
  }
  return out;
}
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd frontend && npm test -- chat-route`. Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```
git add frontend/src/lib/support/answer.ts frontend/tests/support/chat-route.test.ts
git commit -m "feat(support-chat): prompt builder + citation formatter"
```

---

## Task 10: Streaming chat Route Handler

**Files:**
- Create: `frontend/src/app/api/support-chat/route.ts`

- [ ] **Step 1: Implement**

```ts
import { streamText, embed, gateway } from "ai";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { topK } from "@/lib/support/retrieval";
import { buildSupportPrompt, formatCitations } from "@/lib/support/answer";
import { createRateLimiter } from "@/lib/support/rate-limit";
import type { SupportIndex } from "@/lib/support/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const CHAT_MODEL = process.env.SUPPORT_CHAT_MODEL ?? "anthropic/claude-haiku-4-5";
const EMBED_MODEL = process.env.SUPPORT_EMBED_MODEL ?? "openai/text-embedding-3-small";
const MAX_CHARS = Number(process.env.SUPPORT_MAX_MESSAGE_CHARS ?? "2000");
const RATE_LIMIT = Number(process.env.SUPPORT_RATE_LIMIT_PER_MIN ?? "15");
const TOP_K = 5;

const limiter = createRateLimiter({ limit: RATE_LIMIT, windowMs: 60_000 });

let indexCache: SupportIndex | null = null;
async function loadIndex(): Promise<SupportIndex> {
  if (indexCache) return indexCache;
  const p = resolve(process.cwd(), "src/lib/support/index.json");
  indexCache = JSON.parse(await readFile(p, "utf8")) as SupportIndex;
  return indexCache;
}

function clientIp(req: Request): string {
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0].trim();
  return req.headers.get("x-real-ip") ?? "unknown";
}

export async function POST(req: Request) {
  const ip = clientIp(req);
  const gate = limiter.check(ip);
  if (!gate.allowed) {
    return new Response(
      JSON.stringify({ error: "rate_limited", retryAfterSeconds: gate.retryAfterSeconds }),
      { status: 429, headers: { "content-type": "application/json", "retry-after": String(gate.retryAfterSeconds) } }
    );
  }

  let body: { message?: unknown };
  try { body = await req.json(); } catch { return new Response(JSON.stringify({ error: "invalid_json" }), { status: 400 }); }
  const message = typeof body.message === "string" ? body.message.trim() : "";
  if (!message) return new Response(JSON.stringify({ error: "empty_message" }), { status: 400 });
  if (message.length > MAX_CHARS) return new Response(JSON.stringify({ error: "message_too_long", maxChars: MAX_CHARS }), { status: 413 });

  const index = await loadIndex();
  const { embedding } = await embed({
    model: gateway.textEmbeddingModel(EMBED_MODEL),
    value: message,
  });

  const retrieved = topK(embedding, index.chunks, TOP_K).map((s) => s.chunk);
  const citations = formatCitations(retrieved);
  const { messages } = buildSupportPrompt(message, retrieved);

  const result = streamText({
    model: gateway(CHAT_MODEL),
    messages,
    temperature: 0.2,
    maxOutputTokens: 600,
  });

  const headers = new Headers({
    "content-type": "text/plain; charset=utf-8",
    "cache-control": "no-store",
    "x-support-citations": Buffer.from(JSON.stringify(citations)).toString("base64"),
  });
  return result.toTextStreamResponse({ headers });
}
```

> **Verification note:** `gateway`, `streamText`, `embed` exports are from `ai` v6. Before this task, the executor MUST open `frontend/node_modules/ai/dist/index.d.ts` and confirm the export shape. If `gateway(...)` direct call or `gateway.textEmbeddingModel(...)` are named differently in the installed version, look up the Vercel AI Gateway skill for the current API. Do not switch to provider-specific packages.

- [ ] **Step 2: Build + smoke-test locally**

```
cd frontend && AI_GATEWAY_API_KEY=$AI_GATEWAY_API_KEY npm run build:index && npm run build
cd frontend && AI_GATEWAY_API_KEY=$AI_GATEWAY_API_KEY npm start &
sleep 3
curl -N -X POST http://localhost:3000/api/support-chat \
  -H "content-type: application/json" \
  -d '{"message":"How do I install BurnLens?"}'
```

Expected: streaming text answer mentioning `pip install burnlens`. Stop the server when done.

- [ ] **Step 3: Commit**

```
git add frontend/src/app/api/support-chat/route.ts
git commit -m "feat(support-chat): streaming /api/support-chat route via AI Gateway"
```

---

## Task 11: Feedback Route Handler

**Files:**
- Create: `frontend/src/app/api/support-feedback/route.ts`

- [ ] **Step 1: Implement**

```ts
import { createRateLimiter } from "@/lib/support/rate-limit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const limiter = createRateLimiter({ limit: 30, windowMs: 60_000 });

interface FeedbackBody {
  rating: "up" | "down";
  question: string;
  answer: string;
  reason?: string;
}

function clientIp(req: Request): string {
  const fwd = req.headers.get("x-forwarded-for");
  return fwd ? fwd.split(",")[0].trim() : req.headers.get("x-real-ip") ?? "unknown";
}

export async function POST(req: Request) {
  const ip = clientIp(req);
  const gate = limiter.check(ip);
  if (!gate.allowed) return new Response(JSON.stringify({ error: "rate_limited" }), { status: 429 });

  let body: Partial<FeedbackBody>;
  try { body = await req.json(); } catch { return new Response(JSON.stringify({ error: "invalid_json" }), { status: 400 }); }

  if (body.rating !== "up" && body.rating !== "down") {
    return new Response(JSON.stringify({ error: "invalid_rating" }), { status: 400 });
  }
  if (typeof body.question !== "string" || typeof body.answer !== "string") {
    return new Response(JSON.stringify({ error: "missing_fields" }), { status: 400 });
  }

  console.log(JSON.stringify({
    event: "support_chat_feedback",
    rating: body.rating,
    question: body.question.slice(0, 500),
    answer: body.answer.slice(0, 2000),
    reason: (body.reason ?? "").slice(0, 500),
    ts: new Date().toISOString(),
  }));

  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/app/api/support-feedback/route.ts
git commit -m "feat(support-chat): feedback logging endpoint"
```

---

## Task 12: Chat widget UI

**Files:**
- Create: `frontend/src/components/SupportChat.tsx`
- Create: `frontend/src/components/SupportChatMessages.tsx`

- [ ] **Step 1: Implement `SupportChatMessages.tsx`**

```tsx
"use client";

import type { ChatMessage } from "@/lib/support/types";

interface Props {
  messages: ChatMessage[];
  isStreaming: boolean;
  onFeedback: (index: number, rating: "up" | "down") => void;
  feedback: Record<number, "up" | "down" | undefined>;
}

export default function SupportChatMessages({ messages, isStreaming, onFeedback, feedback }: Props) {
  return (
    <div className="flex flex-col gap-4 overflow-y-auto px-4 py-3">
      {messages.map((m, i) => (
        <div key={i} className={`flex flex-col gap-2 ${m.role === "user" ? "items-end" : "items-start"}`}>
          <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
            m.role === "user"
              ? "bg-[color:var(--accent)] text-[color:var(--accent-fg)]"
              : "bg-[color:var(--surface-2)] text-[color:var(--fg)]"
          }`}>
            {m.content || (isStreaming && i === messages.length - 1 ? "…" : "")}
          </div>

          {m.role === "assistant" && m.citations && m.citations.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {m.citations.map((c, ci) => (
                <a key={ci} href={c.url} target="_blank" rel="noreferrer"
                   className="rounded-full border border-[color:var(--border)] px-2 py-0.5 text-xs text-[color:var(--muted-fg)] hover:bg-[color:var(--surface-3)]">
                  [{ci + 1}] {c.heading}
                </a>
              ))}
            </div>
          )}

          {m.role === "assistant" && !isStreaming && m.content && (
            <div className="flex items-center gap-2 text-xs text-[color:var(--muted-fg)]">
              <span>Was this helpful?</span>
              <button type="button" onClick={() => onFeedback(i, "up")} aria-label="Helpful"
                      className={`rounded-full px-2 py-0.5 ${feedback[i] === "up" ? "bg-[color:var(--success-bg)]" : "hover:bg-[color:var(--surface-3)]"}`}>👍</button>
              <button type="button" onClick={() => onFeedback(i, "down")} aria-label="Not helpful"
                      className={`rounded-full px-2 py-0.5 ${feedback[i] === "down" ? "bg-[color:var(--danger-bg)]" : "hover:bg-[color:var(--surface-3)]"}`}>👎</button>
              {feedback[i] === "down" && (
                <a className="ml-2 underline"
                   href={`mailto:support@burnlens.app?subject=BurnLens%20chat%20follow-up&body=Question%3A%20${encodeURIComponent(messages[i - 1]?.content ?? "")}%0A%0AChat%20answer%3A%20${encodeURIComponent(m.content)}`}>
                  Email support
                </a>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

> The CSS tokens (`--accent`, `--surface-1`, etc.) must match what `frontend/src/app/globals.css` defines. Open that file before this task; if a token does not exist, swap for the closest existing token. Do not invent new tokens.

- [ ] **Step 2: Implement `SupportChat.tsx`**

```tsx
"use client";

import { useCallback, useRef, useState } from "react";
import SupportChatMessages from "./SupportChatMessages";
import type { ChatMessage } from "@/lib/support/types";

const GREETING: ChatMessage = {
  role: "assistant",
  content: "Hi! Ask me anything about BurnLens — installation, billing, providers, troubleshooting. I'll cite the docs.",
};

export default function SupportChat() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([GREETING]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<number, "up" | "down" | undefined>>({});
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || streaming) return;
    setError(null);
    const userMsg: ChatMessage = { role: "user", content: trimmed };
    const placeholder: ChatMessage = { role: "assistant", content: "" };
    setMessages((m) => [...m, userMsg, placeholder]);
    setInput("");
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/support-chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: trimmed }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const text = await res.text();
        setError(res.status === 429 ? "You're sending messages too quickly. Please wait a moment." : `Request failed (${res.status}). ${text}`);
        setMessages((m) => m.slice(0, -1));
        return;
      }

      const citeHeader = res.headers.get("x-support-citations");
      let citations: ChatMessage["citations"] = [];
      if (citeHeader) {
        try { citations = JSON.parse(atob(citeHeader)); } catch { citations = []; }
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let acc = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });
        setMessages((m) => {
          const copy = m.slice();
          copy[copy.length - 1] = { role: "assistant", content: acc, citations };
          return copy;
        });
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setError((err as Error).message);
      setMessages((m) => m.slice(0, -1));
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming]);

  const onFeedback = useCallback((idx: number, rating: "up" | "down") => {
    setFeedback((f) => ({ ...f, [idx]: rating }));
    const assistantMsg = messages[idx];
    const userMsg = messages[idx - 1];
    if (!assistantMsg || !userMsg) return;
    void fetch("/api/support-feedback", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ rating, question: userMsg.content, answer: assistantMsg.content }),
    });
  }, [messages]);

  return (
    <>
      <button type="button" aria-label={open ? "Close support chat" : "Open support chat"}
              onClick={() => setOpen((v) => !v)}
              className="fixed bottom-5 right-5 z-50 rounded-full bg-[color:var(--accent)] px-4 py-3 text-sm font-medium text-[color:var(--accent-fg)] shadow-lg hover:opacity-90">
        {open ? "Close" : "Ask BurnLens"}
      </button>

      {open && (
        <div role="dialog" aria-label="BurnLens support chat"
             className="fixed bottom-20 right-5 z-50 flex h-[32rem] w-[22rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface-1)] shadow-2xl">
          <header className="flex items-center justify-between border-b border-[color:var(--border)] px-4 py-2 text-sm">
            <span className="font-medium">BurnLens Support</span>
            <a href="mailto:support@burnlens.app" className="text-xs text-[color:var(--muted-fg)] underline">Email instead</a>
          </header>

          <div className="flex-1 overflow-y-auto">
            <SupportChatMessages messages={messages} isStreaming={streaming} onFeedback={onFeedback} feedback={feedback} />
          </div>

          {error && (
            <div className="border-t border-[color:var(--danger-border)] bg-[color:var(--danger-bg)] px-4 py-2 text-xs text-[color:var(--danger-fg)]">
              {error}
            </div>
          )}

          <form onSubmit={(e) => { e.preventDefault(); void send(); }}
                className="flex gap-2 border-t border-[color:var(--border)] p-2">
            <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
                   placeholder="Ask a question…" maxLength={2000} disabled={streaming}
                   className="flex-1 rounded-md bg-[color:var(--surface-2)] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[color:var(--accent)]" />
            <button type="submit" disabled={streaming || !input.trim()}
                    className="rounded-md bg-[color:var(--accent)] px-3 py-2 text-sm font-medium text-[color:var(--accent-fg)] disabled:opacity-50">
              {streaming ? "…" : "Send"}
            </button>
          </form>
        </div>
      )}
    </>
  );
}
```

- [ ] **Step 3: Commit**

```
git add frontend/src/components/SupportChat.tsx frontend/src/components/SupportChatMessages.tsx
git commit -m "feat(support-chat): floating chat widget with streaming + citations"
```

---

## Task 13: Mount widget globally

**Files:**
- Modify: `frontend/src/app/layout.tsx`

- [ ] **Step 1: Add the import**

Add to the import block:

```tsx
import SupportChat from "@/components/SupportChat";
```

- [ ] **Step 2: Mount inside `<ToastProvider>`**

Change:

```tsx
        <ThemeProvider>
          <ToastProvider>
            {children}
          </ToastProvider>
        </ThemeProvider>
```

to:

```tsx
        <ThemeProvider>
          <ToastProvider>
            {children}
            <SupportChat />
          </ToastProvider>
        </ThemeProvider>
```

- [ ] **Step 3: Manual browser smoke-test**

Run: `cd frontend && npm run dev`. Open http://localhost:3000. Verify: a floating "Ask BurnLens" button appears bottom-right; clicking opens the panel; sending "How do I install BurnLens?" streams a real answer with citation pills. Try the empty-input case (Send button stays disabled). Try a 2500-char paste (rejected with 413). Stop the dev server when done.

> Per project CLAUDE.md: type-check/test passing is necessary but NOT sufficient. You must actually exercise the widget in a browser before claiming this task done.

- [ ] **Step 4: Commit**

```
git add frontend/src/app/layout.tsx
git commit -m "feat(support-chat): mount widget globally in root layout"
```

---

## Task 14: Playwright E2E

**Files:**
- Create: `frontend/tests/e2e/support-chat.spec.ts`

- [ ] **Step 1: Write the test**

```ts
import { test, expect } from "@playwright/test";

test.describe("Support chat widget", () => {
  test("opens, asks a question, and streams an answer with citations", async ({ page }) => {
    await page.goto("/");

    const trigger = page.getByRole("button", { name: /ask burnlens/i });
    await expect(trigger).toBeVisible();
    await trigger.click();

    const dialog = page.getByRole("dialog", { name: /burnlens support chat/i });
    await expect(dialog).toBeVisible();

    const input = dialog.getByPlaceholder(/ask a question/i);
    await input.fill("How do I install BurnLens?");
    await dialog.getByRole("button", { name: /^send$/i }).click();

    await expect(dialog).toContainText(/pip install burnlens/i, { timeout: 30_000 });

    const citations = dialog.locator('a[href*="github.com"], a[href*="burnlens.app"]');
    await expect(citations.first()).toBeVisible();
  });

  test("send button stays disabled when input is empty", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /ask burnlens/i }).click();
    const sendBtn = page.getByRole("button", { name: /^send$/i });
    await expect(sendBtn).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run E2E**

```
cd frontend && AI_GATEWAY_API_KEY=$AI_GATEWAY_API_KEY npm run build && npm start &
sleep 5
npx playwright test tests/e2e/support-chat.spec.ts
```

Expected: both specs pass.

> **Cost note:** E2E hits the real AI Gateway. Run sparingly; use a short-lived gateway key with a low cap.

- [ ] **Step 3: Commit**

```
git add frontend/tests/e2e/support-chat.spec.ts
git commit -m "test(support-chat): playwright e2e for widget open + streamed answer"
```

---

## Task 15: Wire env vars in Vercel + verify production

- [ ] **Step 1: Set Vercel env vars (Production + Preview)**

Run for each scope:

```
vercel env add AI_GATEWAY_API_KEY production
vercel env add AI_GATEWAY_API_KEY preview
vercel env add SUPPORT_CHAT_MODEL production
vercel env add SUPPORT_CHAT_MODEL preview
vercel env add SUPPORT_EMBED_MODEL production
vercel env add SUPPORT_EMBED_MODEL preview
vercel env add SUPPORT_RATE_LIMIT_PER_MIN production
vercel env add SUPPORT_RATE_LIMIT_PER_MIN preview
vercel env add SUPPORT_MAX_MESSAGE_CHARS production
vercel env add SUPPORT_MAX_MESSAGE_CHARS preview
```

Values: `SUPPORT_CHAT_MODEL=anthropic/claude-haiku-4-5`, `SUPPORT_EMBED_MODEL=openai/text-embedding-3-small`, `SUPPORT_RATE_LIMIT_PER_MIN=15`, `SUPPORT_MAX_MESSAGE_CHARS=2000`. `AI_GATEWAY_API_KEY` from the Vercel AI Gateway dashboard.

- [ ] **Step 2: Push to preview, then prod**

```
git push origin main
```

Watch the Vercel deploy. The `build:index` step requires `AI_GATEWAY_API_KEY` — if absent on a build, the build will fail loudly, which is correct.

- [ ] **Step 3: Manual smoke on production**

Visit https://burnlens.app, open the widget, ask: "How do I install BurnLens?" — confirm a streamed answer with citation pills. Ask: "What providers do you support?" — confirm it lists OpenAI, Anthropic, Google. Ask a deliberately out-of-scope question: "What is the capital of France?" — confirm it declines and points to support@burnlens.app.

- [ ] **Step 4: Tag the release**

```
git tag -a support-chat-v1 -m "Tier 1 AI support chat live"
git push origin support-chat-v1
```

---

## Self-Review

**Spec coverage:**
- Tier 1 docs RAG over README + docs/*.md + curated FAQ → Tasks 4–9 ✓
- Citations rendered inline + pills → Task 9 (formatCitations) + Task 12 ✓
- Escape hatch (email support) → Task 11 (header link + 👎 row mailto) + Task 9 (system prompt instructs escalation) ✓
- Per-IP rate limiting → Task 6 + Task 10 + Task 11 ✓
- Cost guardrails (Haiku default, 600 output tokens, 2000 char input cap, top-K=5) → Task 10 ✓
- Feedback (thumbs) with stdout structured logging → Task 11 + Task 12 ✓
- Public marketing site only — no auth — globally mounted → Task 13 ✓
- E2E coverage → Task 14 ✓

**Placeholder scan:** None. All code is concrete; env vars have defaults; source paths are real and verified to exist in this repo.

**Type consistency:** `Chunk`, `IndexedChunk`, `SupportIndex`, `ChatMessage` defined once in `types.ts`. Prompt builder uses a narrower `ChatRoleMessage` (`system|user`) deliberately, to separate model-input shapes from UI shapes (`user|assistant`). `formatCitations` return shape matches `ChatMessage.citations` exactly.

**Known unverified items the executor MUST check:**
1. **AI SDK v6 export surface.** Before Task 10 Step 1, open `frontend/node_modules/ai/dist/index.d.ts` and confirm `gateway`, `streamText`, `embed` exports exist with the shapes used here. If the API differs, consult the Vercel AI Gateway skill — do NOT switch to `@ai-sdk/anthropic` or any provider package; the Vercel guidance is to route through the Gateway as `"provider/model"` strings.
2. **CSS theme tokens.** Before Task 12, open `frontend/src/app/globals.css` and verify the `--accent`, `--surface-1/2/3`, `--border`, `--muted-fg`, `--danger-bg`, `--danger-fg`, `--danger-border`, `--success-bg`, `--accent-fg`, `--fg` tokens. Swap for existing tokens where names differ. Do not invent new tokens.
3. **Anthropic model id.** `anthropic/claude-haiku-4-5` is per current Vercel knowledge update. If the Gateway rejects it, try `anthropic/claude-haiku-4-5-20251001`.
4. **Next.js 16 Route Handler conventions.** The `runtime = "nodejs"` export is current. Reading `node_modules/next/dist/docs/01-app/01-getting-started/15-route-handlers.md` before Task 10 is recommended per project AGENTS.md.

---

## Execution Handoff

Plan saved. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks
2. **Inline Execution** — execute in this session with checkpoints

Which approach do you want?

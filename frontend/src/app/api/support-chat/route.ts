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
      {
        status: 429,
        headers: {
          "content-type": "application/json",
          "retry-after": String(gate.retryAfterSeconds),
        },
      }
    );
  }

  let body: { message?: unknown };
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "invalid_json" }), { status: 400 });
  }
  const message = typeof body.message === "string" ? body.message.trim() : "";
  if (!message) {
    return new Response(JSON.stringify({ error: "empty_message" }), { status: 400 });
  }
  if (message.length > MAX_CHARS) {
    return new Response(JSON.stringify({ error: "message_too_long", maxChars: MAX_CHARS }), { status: 413 });
  }

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

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
  if (!gate.allowed) {
    return new Response(JSON.stringify({ error: "rate_limited" }), { status: 429 });
  }

  let body: Partial<FeedbackBody>;
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "invalid_json" }), { status: 400 });
  }

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

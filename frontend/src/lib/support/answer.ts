import type { IndexedChunk } from "./types";

interface ChatRoleMessage {
  role: "system" | "user";
  content: string;
}

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

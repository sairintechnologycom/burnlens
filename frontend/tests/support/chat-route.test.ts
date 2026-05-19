import { describe, expect, it } from "vitest";
import { buildSupportPrompt, formatCitations } from "@/lib/support/answer";
import type { IndexedChunk } from "@/lib/support/types";

const chunks: IndexedChunk[] = [
  {
    id: "a", source: "README.md", heading: "Install",
    url: "https://example/README.md#install",
    text: "Run pip install burnlens then burnlens start.",
    embedding: [1, 0, 0],
  },
  {
    id: "b", source: "support-knowledge/faq.md", heading: "Why $0?",
    url: "https://burnlens.app/faq#why-0",
    text: "Model not in pricing JSON. Cost shows $0.",
    embedding: [0, 1, 0],
  },
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

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

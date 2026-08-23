import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { chunkMarkdown } from "../../src/lib/support/chunker";
import { CHUNK_MAX_CHARS, SUPPORT_SOURCES } from "../../src/lib/support/sources";
import committed from "../../src/lib/support/index.json";

// The support chat answers from a committed index, NOT from a fresh build:
// README.md and docs/ live outside the Vercel frontend root, so the build
// script cannot read them there and deliberately preserves whatever is checked
// in. That makes the committed file production data. It went 16 days stale
// once — five README chunks the chat could not cite, including the cost-per-
// accepted-outcome section — because the only thing that refreshes it is a
// developer happening to run `npm run build` locally and commit the churn.
//
// Regenerate with: npm run build:index
const REPO_ROOT = join(__dirname, "..", "..", "..");

function rebuild() {
  return SUPPORT_SOURCES.flatMap((src) =>
    chunkMarkdown(
      readFileSync(join(REPO_ROOT, src.path), "utf8"),
      { source: src.source, baseUrl: src.baseUrl },
      { maxChars: CHUNK_MAX_CHARS }
    )
  );
}

describe("support index freshness", () => {
  it("matches the markdown sources it was built from", () => {
    // Compared by chunk, not whole-file, so a failure names the drifted heading
    // instead of dumping 40KB of JSON.
    const fresh = rebuild();
    expect(committed.chunks.map((c) => `${c.source}#${c.heading}`)).toEqual(
      fresh.map((c) => `${c.source}#${c.heading}`)
    );
    expect(committed.chunks).toEqual(fresh);
  });
});

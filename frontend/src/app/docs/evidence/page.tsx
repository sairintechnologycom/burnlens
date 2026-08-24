import type { Metadata } from "next";
import indexData from "@/lib/support/index.json";
import type { SupportIndex } from "@/lib/support/types";
import { slugify, renderChunkText } from "@/lib/support/render";
import DocsNav from "../DocsNav";

const TITLE = "Cost evidence — Cost Confidence, Outcome Coverage, Verified Savings";
const DESCRIPTION =
  "How BurnLens says how much of its own spend figure it can prove: which spend was verified against the provider's bill, which share reaches a recorded outcome, and which projected savings actually showed up in traffic.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/docs/evidence" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: "https://burnlens.app/docs/evidence",
    siteName: "BurnLens",
    type: "article",
  },
};

// Rendered from the built support index rather than hand-written JSX, the same
// way /faq is: the markdown is then the single source for this page AND for what
// the support chat can answer. A hand-written page would leave the chat unable
// to answer a single question about any of this.
const INDEX = indexData as SupportIndex;

export default function EvidenceDocsPage() {
  const chunks = INDEX.chunks.filter((c) => c.source === "support-knowledge/evidence.md");

  return (
    <>
      <h1>Cost evidence</h1>
      <p className="legal-updated">
        A spend total says what was charged. These three figures say how much of it
        BurnLens can prove — and where the proof stops. See also{" "}
        <a href="/docs/limitations">Known limitations</a>.
      </p>

      {chunks.map((c) => (
        <section key={c.id} id={slugify(c.heading)}>
          <h2>{c.heading}</h2>
          {renderChunkText(c.text)}
        </section>
      ))}

      <DocsNav />
    </>
  );
}

import type { Metadata } from "next";
import indexData from "@/lib/support/index.json";
import type { SupportIndex } from "@/lib/support/types";
import { slugify, renderChunkText } from "@/lib/support/render";
import DocsNav from "../DocsNav";

const TITLE = "Known limitations — where BurnLens stops being authoritative";
const DESCRIPTION =
  "Every figure BurnLens shows has a boundary where it stops being authoritative. Unpriced models count as $0, scanned runs carry no prompt breakdown, cost per outcome only sees tagged requests, and waste categories overlap and must never be summed.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/docs/limitations" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: "https://burnlens.app/docs/limitations",
    siteName: "BurnLens",
    type: "article",
  },
};

const INDEX = indexData as SupportIndex;

export default function LimitationsDocsPage() {
  const chunks = INDEX.chunks.filter((c) => c.source === "support-knowledge/limitations.md");

  return (
    <>
      <h1>Known limitations</h1>
      <p className="legal-updated">
        Published deliberately. A cost tool is worth what its worst number is worth,
        and a reader who does not know where a figure stops being authoritative
        cannot use it safely.
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

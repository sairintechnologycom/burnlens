import Link from "next/link";
import type { Metadata } from "next";
import indexData from "@/lib/support/index.json";
import type { SupportIndex } from "@/lib/support/types";
import { slugify, renderChunkText } from "@/lib/support/render";

export const metadata: Metadata = {
  title: "Troubleshooting — BurnLens",
  description:
    "Diagnose and fix common BurnLens errors — plan limits, invalid keys, upstream 401s, model downgrade, dashboard issues.",
  alternates: { canonical: "/troubleshooting" },
  openGraph: {
    title: "Troubleshooting — BurnLens",
    description:
      "Diagnose and fix common BurnLens errors — plan limits, invalid keys, upstream 401s, model downgrade, dashboard issues.",
    url: "https://burnlens.app/troubleshooting",
    siteName: "BurnLens",
    type: "article",
  },
};

const INDEX = indexData as SupportIndex;

export default function TroubleshootingPage() {
  const chunks = INDEX.chunks.filter(
    (c) => c.source === "support-knowledge/troubleshooting.md"
  );

  return (
    <div className="legal-page">
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>BurnLens Troubleshooting</h1>
        <p className="legal-updated">
          Common errors and how to fix them. Still stuck?{" "}
          <a href="mailto:support@burnlens.app">Email support@burnlens.app</a>.
        </p>

        {chunks.map((c) => (
          <section key={c.id} id={slugify(c.heading)}>
            <h2>{c.heading}</h2>
            {renderChunkText(c.text)}
          </section>
        ))}
      </main>
    </div>
  );
}

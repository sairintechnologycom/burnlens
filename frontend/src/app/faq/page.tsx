import Link from "next/link";
import type { Metadata } from "next";
import indexData from "@/lib/support/index.json";
import type { SupportIndex } from "@/lib/support/types";
import { slugify, renderChunkText } from "@/lib/support/render";

export const metadata: Metadata = {
  title: "FAQ — BurnLens",
  description:
    "Frequently asked questions about installing, configuring, and operating BurnLens — the open-source LLM FinOps proxy.",
  alternates: { canonical: "/faq" },
  openGraph: {
    title: "FAQ — BurnLens",
    description:
      "Frequently asked questions about installing, configuring, and operating BurnLens.",
    url: "https://burnlens.app/faq",
    siteName: "BurnLens",
    type: "article",
  },
};

const INDEX = indexData as SupportIndex;

export default function FaqPage() {
  const chunks = INDEX.chunks.filter(
    (c) => c.source === "support-knowledge/faq.md"
  );

  return (
    <div className="legal-page">
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        <h1>BurnLens Support FAQ</h1>
        <p className="legal-updated">
          Answers to common questions. Can&rsquo;t find what you need?{" "}
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

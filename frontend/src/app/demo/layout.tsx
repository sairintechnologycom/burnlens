import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Live demo — see what BurnLens shows for your AI spend · BurnLens",
  description:
    "Interactive read-only demo of the BurnLens dashboard. See cost by model, customer, feature, and team plus a runaway-agent incident caught by a hard cap. No signup, seeded data.",
  alternates: { canonical: "/demo" },
  openGraph: {
    title: "Live demo — the BurnLens dashboard with real data",
    description:
      "Read-only dashboard showing cost by model / customer / feature, a runaway-agent spike, and an HTTP 429 cap-hit. This is what you get on your own machine.",
    url: "https://burnlens.app/demo",
    siteName: "BurnLens",
    type: "article",
  },
  twitter: {
    card: "summary_large_image",
    title: "Live demo — the BurnLens dashboard",
    description: "Read-only dashboard with cost attribution, runaway-agent spike, and HTTP 429 cap-hit example.",
  },
};

export default function DemoLayout({ children }: { children: React.ReactNode }) {
  return children;
}

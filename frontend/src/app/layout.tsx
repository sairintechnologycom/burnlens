import type { Metadata } from "next";
import localFont from "next/font/local";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ToastProvider } from "@/lib/contexts/ToastContext";
import SupportChat from "@/components/SupportChat";
import { PlausibleScript } from "@/components/PlausibleScript";
import "./globals.css";

// Self-hosted rather than next/font/google: that helper fetches font metadata
// from Google at BUILD time, and when a CI runner cannot reach it Turbopack
// reports an unresolvable internal font module instead of a network error —
// reddening the deploy's frontend build and blocking backend-only releases.
// Same latin woff2 subsets Google served, vendored under ./fonts.
const dmMono = localFont({
  src: [
    { path: "./fonts/DMMono-300.woff2", weight: "300", style: "normal" },
    { path: "./fonts/DMMono-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/DMMono-500.woff2", weight: "500", style: "normal" },
  ],
  variable: "--font-mono",
  display: "swap",
});

const manrope = localFont({
  // One variable file covers the 400–800 range the design uses.
  src: [{ path: "./fonts/Manrope-400-800.woff2", weight: "400 800", style: "normal" }],
  variable: "--font-sans",
  display: "swap",
});

const SITE_TITLE = "BurnLens — Hard-cap your AI spend across every provider";
const SITE_DESCRIPTION =
  "Open-source, local-first proxy that hard-caps LLM spend before the call — 429 at the limit, not a surprise bill. Cost attribution across 10 providers including OpenAI, Anthropic, Google, Azure OpenAI, and AWS Bedrock.";

export const metadata: Metadata = {
  metadataBase: new URL("https://burnlens.app"),
  title: SITE_TITLE,
  description: SITE_DESCRIPTION,
  alternates: {
    canonical: "/",
  },
  verification: {
    google: process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION,
    other: {
      "msvalidate.01": process.env.NEXT_PUBLIC_BING_SITE_VERIFICATION ?? "",
    },
  },
  openGraph: {
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    url: "https://burnlens.app",
    siteName: "BurnLens",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
  },
};

const structuredData = [
  {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "BurnLens",
    url: "https://burnlens.app",
    logo: "https://burnlens.app/opengraph-image",
    sameAs: ["https://github.com/sairintechnologycom/burnlens"],
    parentOrganization: {
      "@type": "Organization",
      name: "Sairin Technology",
      url: "https://sairintechnology.com",
    },
  },
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "BurnLens",
    applicationCategory: "DeveloperApplication",
    operatingSystem: "macOS, Linux, Windows",
    url: "https://burnlens.app",
    description:
      "Open-source LLM FinOps proxy — install with pip, make zero code changes, see every AI API call's real cost across Anthropic, OpenAI, and Google AI.",
    offers: [
      { "@type": "Offer", name: "Open source proxy", price: "0", priceCurrency: "USD" },
      { "@type": "Offer", name: "Cloud", price: "29", priceCurrency: "USD" },
      { "@type": "Offer", name: "Teams", price: "99", priceCurrency: "USD" },
    ],
  },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="theme-dark">
      <body className={`${dmMono.variable} ${manrope.variable}`}>
        <script type="application/ld+json">{JSON.stringify(structuredData)}</script>
        <PlausibleScript />
        <ThemeProvider>
          <ToastProvider>
            {children}
            <SupportChat />
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

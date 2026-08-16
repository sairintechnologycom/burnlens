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

const SITE_TITLE = "BurnLens — See what your AI spent. Cap the next call.";
const SITE_DESCRIPTION =
  "Scan Claude Code, Cursor, Codex, and Gemini CLI logs in one command, or hard-cap production APIs with a local proxy. 429 at the limit, not a surprise bill. Prompt bodies go to your provider, never to BurnLens Cloud.";

export const metadata: Metadata = {
  metadataBase: new URL("https://burnlens.app"),
  title: SITE_TITLE,
  description: SITE_DESCRIPTION,
  alternates: {
    canonical: "/",
  },
  // Both of these are unset in Vercel, so neither meta tag renders in
  // production — and that is not a gap. Google is verified by DNS TXT on
  // burnlens.app (`dig +short TXT burnlens.app` shows the
  // google-site-verification record), which is the stronger method: it is a
  // domain property, so it covers every subdomain and protocol and survives a
  // redeploy that drops an env var. Bing inherits that through its "import
  // from Google Search Console" flow.
  //
  // Absence of these meta tags has now twice been read as "the site is not
  // verified". Check DNS before concluding that again. The env vars stay wired
  // as the fallback for the day DNS is not available.
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
      "Open-source LLM FinOps — scan local coding-agent logs or hard-cap production APIs with a local proxy. Prompt bodies go only to your provider.",
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

import type { Metadata } from "next";
import { DM_Mono, Inter_Tight } from "next/font/google";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ToastProvider } from "@/lib/contexts/ToastContext";
import SupportChat from "@/components/SupportChat";
import { PlausibleScript } from "@/components/PlausibleScript";
import "./globals.css";

const dmMono = DM_Mono({
  weight: ["300", "400", "500"],
  subsets: ["latin"],
  variable: "--font-mono",
});

const interTight = Inter_Tight({
  weight: ["400", "500", "600", "700", "800"],
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://burnlens.app"),
  title: "BurnLens — Open-Source FinOps Proxy for AI Spend",
  description: "Open-source LLM cost tracking proxy. Attribute AI spend per feature, team, and customer. Hard-cap budgets across OpenAI, Anthropic, and Google.",
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
    title: "BurnLens — Open-Source FinOps Proxy for AI Spend",
    description: "The open-source FinOps proxy for AI spend. Track every dollar by feature, team, and customer across OpenAI, Anthropic, and Google — with Azure, AWS Bedrock, Groq, Mistral, and Together on the roadmap.",
    url: "https://burnlens.app",
    siteName: "BurnLens",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "BurnLens — Open-Source FinOps Proxy for AI Spend",
    description: "The open-source FinOps proxy for AI spend. Track every dollar by feature, team, and customer across OpenAI, Anthropic, and Google today. Hard-cap budgets before the API call.",
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
      <body className={`${dmMono.variable} ${interTight.variable}`}>
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

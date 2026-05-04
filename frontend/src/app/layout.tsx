import type { Metadata } from "next";
import { DM_Mono, Inter_Tight } from "next/font/google";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ToastProvider } from "@/lib/contexts/ToastContext";
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
  description: "The open-source FinOps proxy for AI spend. Track every dollar by feature, team, and customer across OpenAI, Anthropic, Google, Azure, AWS Bedrock, and Groq. Hard-cap budgets before the API call — not after the bill arrives.",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "BurnLens — Open-Source FinOps Proxy for AI Spend",
    description: "The open-source FinOps proxy for AI spend. Track every dollar by feature, team, and customer across OpenAI, Anthropic, Google, Azure, AWS Bedrock, and Groq.",
    url: "https://burnlens.app",
    siteName: "BurnLens",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "BurnLens — Open-Source FinOps Proxy for AI Spend",
    description: "The open-source FinOps proxy for AI spend. Track every dollar by feature, team, and customer across OpenAI, Anthropic, Google, Azure, AWS Bedrock, and Groq. Hard-cap budgets before the API call.",
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
        <ThemeProvider>
          <ToastProvider>
            {children}
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

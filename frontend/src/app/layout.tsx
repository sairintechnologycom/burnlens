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
  title: "BurnLens — AI FinOps Dashboard",
  description: "Track, analyze, and optimize your LLM API spend across Anthropic, OpenAI & Google AI.",
  robots: "noindex, nofollow",
  openGraph: {
    title: "BurnLens Dashboard",
    description: "AI FinOps dashboard — track LLM API costs across providers.",
    siteName: "BurnLens",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="theme-dark">
      <body className={`${dmMono.variable} ${interTight.variable}`}>
        <ThemeProvider>
          <ToastProvider>
            {children}
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

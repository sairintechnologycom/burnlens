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
  title: "BurnLens — See exactly what your AI API calls cost",
  description: "One command. Zero code changes. Every dollar tracked. Open-source LLM FinOps proxy for Anthropic, OpenAI & Google AI.",
  openGraph: {
    title: "BurnLens — See exactly what your AI API calls cost",
    description: "One command. Zero code changes. Every dollar tracked. Open-source LLM FinOps proxy that shows developers where their AI API money goes.",
    siteName: "BurnLens",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "BurnLens — See exactly what your AI API calls cost",
    description: "One command. Zero code changes. Every dollar tracked. Open-source LLM FinOps for Anthropic, OpenAI & Google AI.",
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

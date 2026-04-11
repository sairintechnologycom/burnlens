import type { Metadata } from "next";
import { ToastProvider } from "@/lib/contexts/ToastContext";
import "./globals.css";

export const metadata: Metadata = {
  title: "BurnLens — AI FinOps Dashboard",
  description: "Track, analyze, and optimize your LLM API spend across Anthropic, OpenAI & Google AI.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <ToastProvider>
          {children}
        </ToastProvider>
      </body>
    </html>
  );
}

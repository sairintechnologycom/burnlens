import Link from "next/link";
import type { ReactNode } from "react";
import DocsNav from "./DocsNav";
import { GH } from "@/lib/docs";

export default function DocsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="legal-page">
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/docs" className="legal-nav-link">Docs</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content">
        {children}

        <DocsNav />

        <p style={{ marginTop: 32 }}>
          Something here wrong or missing?{" "}
          <a href={`${GH}/issues`} target="_blank" rel="noreferrer">Open an issue</a> or email{" "}
          <a href="mailto:support@burnlens.app">support@burnlens.app</a>.
        </p>
      </main>
    </div>
  );
}

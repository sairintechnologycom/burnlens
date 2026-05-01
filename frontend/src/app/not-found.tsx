import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Page not found — BurnLens",
  description: "The page you're looking for doesn't exist.",
  robots: { index: false, follow: false },
};

export default function NotFound() {
  return (
    <div className="legal-page">
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
      </nav>

      <main className="legal-content" style={{ textAlign: "center", paddingTop: "8rem" }}>
        <h1 style={{ fontSize: "4rem", marginBottom: "0.5rem" }}>404</h1>
        <p style={{ fontSize: "1.125rem", opacity: 0.8, marginBottom: "2rem" }}>
          That page doesn&apos;t exist. Possibly because it never did, or it
          moved. The dashboard, the docs, and the marketing page are all still
          here.
        </p>
        <div style={{ display: "flex", gap: "1rem", justifyContent: "center", flexWrap: "wrap" }}>
          <Link href="/" className="legal-nav-link">Home</Link>
          <Link href="/dashboard" className="legal-nav-link">Dashboard</Link>
          <Link href="/setup?intent=register" className="legal-nav-link">Sign up</Link>
          <a
            href="https://github.com/sairintechnologycom/burnlens#readme"
            className="legal-nav-link"
            target="_blank"
            rel="noopener noreferrer"
          >
            Docs
          </a>
        </div>
      </main>
    </div>
  );
}

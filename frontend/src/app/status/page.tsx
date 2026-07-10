"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type ComponentStatus = {
  name: string;
  status: "operational" | "degraded" | "down" | "unknown";
  uptime_30d: number;
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.burnlens.app";

export default function StatusPage() {
  const [components, setComponents] = useState<ComponentStatus[]>([]);
  const [available, setAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 8000);
    fetch(`${API_BASE}/api/status`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        setComponents(Array.isArray(body.components) ? body.components : []);
        setAvailable(true);
      })
      .catch(() => {
        setComponents([]);
        setAvailable(false);
      })
      .finally(() => window.clearTimeout(timer));
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, []);

  const overall = available === false
    ? "unknown"
    : components.some((item) => item.status === "down")
      ? "down"
      : components.some((item) => item.status === "degraded" || item.status === "unknown")
        ? "degraded"
        : available === true ? "operational" : "checking";

  return (
    <div className="legal-page">
      <nav className="legal-nav">
        <Link href="/" className="legal-nav-logo">BURNLENS</Link>
        <Link href="/security" className="legal-nav-link">Security</Link>
      </nav>
      <main className="legal-content">
        <h1>Service status</h1>
        <p className="legal-updated">Current state: {overall}</p>
        {available === null && <p>Checking hosted services…</p>}
        {available === false && (
          <section>
            <h2>Status unavailable</h2>
            <p>
              BurnLens cannot currently retrieve service health. Hosted service status is unknown;
              local proxies continue operating independently.
            </p>
          </section>
        )}
        {components.map((component) => (
          <section key={component.name}>
            <h2>{component.name}</h2>
            <p>
              {component.status} · {component.uptime_30d.toFixed(2)}% measured uptime over 30 days
            </p>
          </section>
        ))}
      </main>
    </div>
  );
}

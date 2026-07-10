import type { MetadataRoute } from "next";

export const dynamic = "force-static";

const BASE = "https://burnlens.app";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    { url: `${BASE}/`, lastModified: now, changeFrequency: "weekly", priority: 1.0 },
    { url: `${BASE}/scan`, lastModified: now, changeFrequency: "monthly", priority: 0.95 },
    { url: `${BASE}/demo`, lastModified: now, changeFrequency: "weekly", priority: 0.95 },
    { url: `${BASE}/compare/burnlens-vs-helicone`, lastModified: now, changeFrequency: "monthly", priority: 0.9 },
    { url: `${BASE}/compare/burnlens-vs-litellm`, lastModified: now, changeFrequency: "monthly", priority: 0.9 },
    { url: `${BASE}/compare/burnlens-vs-langfuse`, lastModified: now, changeFrequency: "monthly", priority: 0.9 },
    { url: `${BASE}/security`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${BASE}/status`, lastModified: now, changeFrequency: "daily", priority: 0.8 },
    { url: `${BASE}/privacy`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
    { url: `${BASE}/terms`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
    { url: `${BASE}/refund`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
    { url: `${BASE}/faq`, lastModified: now, changeFrequency: "monthly", priority: 0.7 },
    { url: `${BASE}/troubleshooting`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },
  ];
}

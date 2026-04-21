import type { MetadataRoute } from "next";

export const dynamic = "force-static";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          "/dashboard",
          "/dashboard/",
          "/alerts",
          "/budgets",
          "/checkout",
          "/connections",
          "/customers",
          "/features",
          "/models",
          "/optimizations",
          "/savings",
          "/settings",
          "/setup",
          "/teams",
          "/waste",
          "/auth/",
          "/dashboard.html",
          "/signup.html",
          "/team.html",
        ],
      },
    ],
    sitemap: "https://burnlens.app/sitemap.xml",
    host: "https://burnlens.app",
  };
}

import type { MetadataRoute } from "next";

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

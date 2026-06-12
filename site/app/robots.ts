import type { MetadataRoute } from "next";

// Single source of truth for the canonical origin. Matches the per-page
// canonical tags already declared under /whitepaper and /whitepaper/summary.
const SITE_URL = "https://quantum.advancelabs.dev";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}

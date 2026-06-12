import type { MetadataRoute } from "next";

const SITE_URL = "https://quantum.advancelabs.dev";

// Stable, content-derived lastmod dates (the git commit date of each page's
// source), not `new Date()` at render time — otherwise every deploy bumps
// lastmod even when content is unchanged, which trains crawlers to distrust
// the signal. Bump a date here only when that page's content actually changes.
const ROUTES: Array<{ path: string; lastModified: string; priority: number }> = [
  { path: "/", lastModified: "2026-06-12", priority: 1 },
  { path: "/whitepaper", lastModified: "2026-06-12", priority: 0.9 },
  { path: "/whitepaper/summary", lastModified: "2026-06-12", priority: 0.8 },
  { path: "/learn", lastModified: "2026-06-11", priority: 0.7 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  return ROUTES.map(({ path, lastModified, priority }) => ({
    url: `${SITE_URL}${path}`,
    lastModified,
    changeFrequency: "monthly" as const,
    priority,
  }));
}

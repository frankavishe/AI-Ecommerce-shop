import type { NextConfig } from "next";

const api = process.env.DJANGO_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  output: "standalone",
  // e2e runs a second dev server (playwright.config.ts) that must not share .next with `npm run dev`.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Django URLs end in "/"; keep them intact through the BFF (/bff/api/.../).
  skipTrailingSlashRedirect: true,
  // Django media is served through this origin, so image URLs work whatever host Django saw.
  // UI code turns absolute media URLs into "/media/..." paths (see lib/media.ts).
  async rewrites() {
    return [{ source: "/media/:path*", destination: `${api}/media/:path*` }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;

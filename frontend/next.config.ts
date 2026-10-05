import type { NextConfig } from "next";

/**
 * Proxy mode (recommended for production): leave NEXT_PUBLIC_API_URL empty and set
 * API_PROXY_TARGET to the backend origin. The browser then talks to the frontend's own
 * origin, so the refresh-token cookie is first-party (works with Safari ITP and
 * third-party-cookie blocking). Direct mode: set NEXT_PUBLIC_API_URL to the API origin.
 */
const proxyTarget = process.env.API_PROXY_TARGET?.replace(/\/$/, "");

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    if (!proxyTarget) return [];
    return [
      { source: "/api/:path*", destination: `${proxyTarget}/api/:path*` },
      { source: "/health", destination: `${proxyTarget}/health` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;

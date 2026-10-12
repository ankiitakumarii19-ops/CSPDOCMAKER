import type { NextConfig } from "next";

// Where the app is served from: "" locally, "/csp-docmaker" on the server
// (https://indev.eko.in/csp-docmaker). Fixed at build time; see lib/basePath.ts.
const basePath = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  basePath: basePath || undefined,
  // API proxy to the FastAPI backend (local development; on the server the
  // front door sends /api to the backend directly).
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  // API calls are handled directly by the Python backend
  // in the portable build — no proxy needed
};

export default nextConfig;

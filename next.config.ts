import type { NextConfig } from "next";
import { execFileSync } from "node:child_process";

/**
 * Raw `git describe` output, exposed as NEXT_PUBLIC_APP_VERSION and rendered by
 * `lib/version.ts` → `formatVersion()` in the app's wordmark lines.
 *
 * The git tag is the real version — package.json has sat at 0.1.0 through every
 * release, so reading it would print a number that never moves. Resolving it at
 * build time means the footer describes the build that is actually serving. An
 * empty string (no git, e.g. a tarball deploy) makes the app omit the label
 * rather than invent a version.
 */
function buildVersion(): string {
  try {
    return execFileSync("git", ["describe", "--tags", "--always", "--dirty"], {
      cwd: process.cwd(),
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "";
  }
}

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_APP_VERSION: buildVersion(),
  },
  allowedDevOrigins: [
    "fedora-nuc.tailc24d36.ts.net",
    "*.tailc24d36.ts.net",
  ],
  // Middleware buffers request bodies (added for the auth wall) and Next.js
  // caps those at 10MB by default. Our app accepts 100MB PPTX uploads, so the
  // cap must match — otherwise large uploads get truncated mid-multipart,
  // losing the closing boundary ("Failed to parse body as FormData").
  experimental: {
    middlewareClientMaxBodySize: "100mb",
  },
};

export default nextConfig;

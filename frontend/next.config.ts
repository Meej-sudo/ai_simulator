import { execSync } from "node:child_process";
import type { NextConfig } from "next";

const internalApiUrl = process.env.INTERNAL_API_URL ?? "http://localhost:8000";

// Short commit hash of the build, shown in the corner of every page.
// Set SHOW_BUILD_COMMIT=false to hide it. GIT_COMMIT overrides the git lookup
// (e.g. in CI). Returning "" hides the footer, so it never shows a placeholder
// when the hash is switched off or cannot be determined.
function gitCommit(): string {
  if (/^(false|0|off|no)$/i.test(process.env.SHOW_BUILD_COMMIT ?? "")) return "";
  if (process.env.GIT_COMMIT) return process.env.GIT_COMMIT;
  try {
    return execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
  } catch {
    return "";
  }
}

const nextConfig: NextConfig = {
  output: "standalone",
  env: { NEXT_PUBLIC_GIT_COMMIT: gitCommit() },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${internalApiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;

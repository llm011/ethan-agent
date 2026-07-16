import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 'export' for pip package (static files served by FastAPI)
  // 'standalone' for Docker image (node server)
  output: (process.env.NEXT_OUTPUT as "standalone" | "export") ?? "export",
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;

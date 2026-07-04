import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: (process.env.NEXT_OUTPUT as "standalone" | "export") ?? "standalone",
};

export default nextConfig;

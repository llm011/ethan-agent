/** @type {import('next').NextConfig} */
const nextConfig = {
  // 'export' for pip package (static files served by FastAPI)
  // 'standalone' for Docker image (node server)
  output: process.env.NEXT_OUTPUT || 'export',
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || '',
  trailingSlash: true,
  images: { unoptimized: true },
  experimental: {
    turbopack: {
      root: __dirname,
    }
  }
};

module.exports = nextConfig;

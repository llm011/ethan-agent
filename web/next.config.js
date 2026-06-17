/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  trailingSlash: true,
  images: { unoptimized: true },
  experimental: {
    turbopack: {
      root: __dirname,
    }
  }
};

module.exports = nextConfig;

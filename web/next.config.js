/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',  // 用于 Docker 多阶段构建
  experimental: {
    turbopack: {
      root: __dirname,
    }
  }
};

module.exports = nextConfig;

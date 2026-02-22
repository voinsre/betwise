/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    // In Docker: NEXT_PUBLIC_API_URL = http://backend:2323
    // Local dev: NEXT_PUBLIC_API_URL = http://localhost:2323 (or default)
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:2323";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;

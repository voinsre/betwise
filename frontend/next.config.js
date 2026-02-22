/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    // When NEXT_PUBLIC_API_URL is set (production), api.ts calls the backend
    // directly — no rewrites needed. Only proxy in local dev / Docker.
    if (process.env.NEXT_PUBLIC_API_URL) {
      return [];
    }
    const apiUrl = process.env.BACKEND_URL || "http://localhost:2323";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;

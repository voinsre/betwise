/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    // BACKEND_URL is a server-side env var (not NEXT_PUBLIC_*) so it resolves
    // at runtime, not build time. This lets Railway set it to the backend's
    // internal/public URL while Docker uses http://backend:2323.
    const apiUrl =
      process.env.BACKEND_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://localhost:2323";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;

/** @type {import('next').NextConfig} */
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // Increase timeouts for long LLM inference calls (up to 3 minutes)
  httpAgentOptions: {
    keepAlive: true,
  },
  serverRuntimeConfig: {
    // Allow rewrites to wait up to 180s before timing out
    proxyTimeout: 180000,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `${backendUrl}/ws/:path*`,
      },
    ];
  },
};

export default nextConfig;

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    // TM11-142: game art comes straight from Steam's public CDN by app id
    // (lib/discover/featured.ts). Served unoptimised, so this only allows the host.
    remotePatterns: [
      {
        protocol: "https",
        hostname: "shared.akamai.steamstatic.com",
        pathname: "/store_item_assets/steam/apps/**",
      },
    ],
  },
};

export default nextConfig;

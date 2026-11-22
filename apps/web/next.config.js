/** @type {import('next').NextConfig} */
const nextConfig = {
  // the Docker image runs .next/standalone/server.js; it does not change dev
  output: "standalone",
};

module.exports = nextConfig;

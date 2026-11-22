import { NextResponse } from "next/server";

// read on every request from the container's own environment: this is what
// makes one built image deployable to any environment, and why it must never
// be cached (a cached answer would keep the previous URL after a deploy)
export const dynamic = "force-dynamic";

export function GET() {
  const config = {
    apiBaseUrl: (process.env.API_BASE_URL || "").replace(/\/+$/, "") || null,
    maxUploadMb: Number(process.env.MAX_UPLOAD_SIZE_MB) || null,
  };

  return new NextResponse(
    `window.__RIVET_CONFIG__=${JSON.stringify(config)};`,
    {
      headers: {
        "Content-Type": "application/javascript; charset=utf-8",
        "Cache-Control": "no-store",
      },
    },
  );
}

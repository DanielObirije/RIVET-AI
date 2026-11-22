export interface RuntimeConfig {
  apiBaseUrl?: string | null;
  maxUploadMb?: number | null;
}

declare global {
  interface Window {
    // set by /config.js, which the root layout loads before hydration
    __RIVET_CONFIG__?: RuntimeConfig;
  }
}

/**
 * Values the Next server serves from its own environment, per request.
 *
 * Read at call time rather than module load: the script can land after the app
 * chunk, and a module-scope copy would then stick to the build-time default.
 * Empty during server rendering, where no API call is made.
 */
export function runtimeConfig(): RuntimeConfig {
  if (typeof window === "undefined") return {};
  return window.__RIVET_CONFIG__ ?? {};
}

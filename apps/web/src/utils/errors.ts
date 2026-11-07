const RATE_LIMIT_MESSAGE =
  "Oops! It seems you've reached the rate limit. Please try again later.";

const FALLBACK_MESSAGE = "Something went wrong. Please try again.";

const GENERIC_MESSAGE =
  "I couldn't finish that reply. Please try again in a moment.";

const NETWORK_MESSAGE =
  "I can't reach the server right now. Check your connection and try again.";

export const TIMEOUT_MESSAGE =
  "That took too long to respond. Please try again.";

// server sends {"code","error"}; only the code is trusted for user-facing text
function errorCode(message: string): string | undefined {
  try {
    const parsed = JSON.parse(message);
    return typeof parsed?.code === "string" ? parsed.code : undefined;
  } catch {
    return undefined;
  }
}

export function friendlyErrorMessage(error: Error): string {
  const message = error?.message ?? "";
  const code = errorCode(message);

  if (code === "rate_limit") return RATE_LIMIT_MESSAGE;
  if (code === "timeout") return TIMEOUT_MESSAGE;
  if (code === "network") return NETWORK_MESSAGE;
  if (
    code === "server_error" ||
    code === "unavailable" ||
    code === "missing_config"
  ) {
    return GENERIC_MESSAGE;
  }

  if (
    /failed to fetch|network ?error|load failed|fetch failed/i.test(message)
  ) {
    return NETWORK_MESSAGE;
  }

  return FALLBACK_MESSAGE;
}

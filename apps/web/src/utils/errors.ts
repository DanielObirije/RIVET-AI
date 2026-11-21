const RATE_LIMIT_MESSAGE =
  "Oops! It seems you've reached the rate limit. Please try again later.";

const FALLBACK_MESSAGE = "Something went wrong. Please try again.";

const GENERIC_MESSAGE =
  "I couldn't finish that reply. Please try again in a moment.";

const NETWORK_MESSAGE =
  "I can't reach the server right now. Check your connection and try again.";

export const TIMEOUT_MESSAGE =
  "That took too long to respond. Please try again.";

const ALREADY_FINISHED_MESSAGE =
  "That reply already finished. Send a new message to ask again.";

// server sends {"code","error"}; only the code is trusted for user-facing text
function errorCode(message: string): string | undefined {
  try {
    const parsed = JSON.parse(message);
    return typeof parsed?.code === "string" ? parsed.code : undefined;
  } catch {
    return undefined;
  }
}

/** The text to show for one API error code. */
export function friendlyErrorForCode(code: string): string {
  if (code === "rate_limit") return RATE_LIMIT_MESSAGE;
  if (code === "timeout") return TIMEOUT_MESSAGE;
  if (code === "network") return NETWORK_MESSAGE;
  if (code === "not_retryable") return ALREADY_FINISHED_MESSAGE;
  if (code === "unsupported_file")
    return "That file type isn't supported. Attach a PDF or JPEG file.";
  if (code === "file_too_large")
    return "That file is too large. Please attach a smaller file.";
  if (code === "forbidden")
    return "That attachment isn't available for this request.";
  if (code === "attachment_not_ready")
    return "That upload hasn't finished yet. Try again in a moment.";
  if (code === "attachment_missing")
    return "That attachment is no longer available.";
  if (code === "attachment_unreadable")
    return "I couldn't read that file. It may be corrupt or a scanned document.";
  if (code === "image_unsupported")
    return "The current AI model can't read images. Attach a PDF instead.";
  if (code === "storage_unavailable")
    return "File storage isn't available right now. Please try again.";
  if (
    code === "server_error" ||
    code === "unavailable" ||
    code === "missing_config" ||
    code === "bad_request" ||
    code === "not_found" ||
    code === "enqueue_failed"
  ) {
    return GENERIC_MESSAGE;
  }

  return FALLBACK_MESSAGE;
}

export function friendlyErrorMessage(error: Error): string {
  const message = error?.message ?? "";
  const code = errorCode(message);
  if (code) return friendlyErrorForCode(code);

  if (
    /failed to fetch|network ?error|load failed|fetch failed/i.test(message)
  ) {
    return NETWORK_MESSAGE;
  }

  return FALLBACK_MESSAGE;
}

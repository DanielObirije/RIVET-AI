import { runtimeConfig } from "@/utils/runtime-config";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

/**
 * Base URL of the FastAPI backend that owns chat jobs and results.
 *
 * Read per call, because /config.js supplies it at run time: the build-time
 * value only covers a deploy that starts the container without API_BASE_URL.
 */
function apiBaseUrl(): string {
  return (
    runtimeConfig().apiBaseUrl ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    DEFAULT_API_BASE_URL
  ).replace(/\/+$/, "");
}

/** Submits a chat turn and returns a job id. */
export function chatApiUrl(): string {
  return `${apiBaseUrl()}/api/chat`;
}

/** Attachment presign, confirm and download endpoints. */
export function attachmentsApiUrl(): string {
  return `${apiBaseUrl()}/api/attachments`;
}

/** Current status and, once finished, the reply for one job. */
export function jobUrl(jobId: string): string {
  return `${apiBaseUrl()}/api/jobs/${encodeURIComponent(jobId)}`;
}

/** Creates a new job from an existing one; the original job is not modified. */
export function retryJobUrl(jobId: string): string {
  return `${apiBaseUrl()}/api/jobs/${encodeURIComponent(jobId)}/retry`;
}

/** Confirms that a direct-to-S3 upload finished. */
export function attachmentConfirmUrl(attachmentId: string): string {
  return `${attachmentsApiUrl()}/${encodeURIComponent(attachmentId)}/confirm`;
}

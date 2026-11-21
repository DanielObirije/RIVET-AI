const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** Base URL of the FastAPI backend that owns chat jobs and results. */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL
).replace(/\/+$/, "");

/** Submits a chat turn and returns a job id. */
export const CHAT_API_URL = `${API_BASE_URL}/api/chat`;

/** Attachment presign, confirm and download endpoints. */
export const ATTACHMENTS_API_URL = `${API_BASE_URL}/api/attachments`;

/** Current status and, once finished, the reply for one job. */
export function jobUrl(jobId: string): string {
  return `${API_BASE_URL}/api/jobs/${encodeURIComponent(jobId)}`;
}

/** Creates a new job from an existing one; the original job is not modified. */
export function retryJobUrl(jobId: string): string {
  return `${API_BASE_URL}/api/jobs/${encodeURIComponent(jobId)}/retry`;
}

/** Confirms that a direct-to-S3 upload finished. */
export function attachmentConfirmUrl(attachmentId: string): string {
  return `${ATTACHMENTS_API_URL}/${encodeURIComponent(attachmentId)}/confirm`;
}

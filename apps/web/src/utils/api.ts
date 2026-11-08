const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** Base URL of the FastAPI backend that owns chat jobs and results. */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL
).replace(/\/+$/, "");

/** Submits a chat turn and returns a job id. */
export const CHAT_API_URL = `${API_BASE_URL}/api/chat`;

/** Current status and, once finished, the reply for one job. */
export function jobUrl(jobId: string): string {
  return `${API_BASE_URL}/api/jobs/${encodeURIComponent(jobId)}`;
}

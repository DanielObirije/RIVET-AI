const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** Base URL of the FastAPI backend that owns all chat logic. */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE_URL
).replace(/\/+$/, "");

export const CHAT_API_URL = `${API_BASE_URL}/api/chat`;

import {
  ATTACHMENTS_API_URL,
  attachmentConfirmUrl,
} from "@/utils/api";

/** Kept in step with the API's MAX_UPLOAD_SIZE_MB. */
const MAX_UPLOAD_MB = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB) || 1;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
export const ACCEPTED_EXTENSIONS = [".pdf", ".jpg", ".jpeg"];

const CONTENT_TYPES: Record<string, string> = {
  ".pdf": "application/pdf",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
};

const CLIENT_ID_KEY = "rivet-client-id";

export interface UploadedAttachment {
  id: string;
  filename: string;
  sizeBytes: number;
}

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

function contentTypeOf(filename: string): string | undefined {
  return CONTENT_TYPES[extensionOf(filename)];
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Client-side feedback only; the API validates the metadata again. */
export function validateFile(file: File): string | null {
  if (!CONTENT_TYPES[extensionOf(file.name)]) {
    return "Attach a PDF or JPEG file.";
  }
  if (file.size <= 0) {
    return "That file is empty.";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `That file is too large. The limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`;
  }
  return null;
}

/**
 * An opaque per-browser id. It scopes attachments to this browser; it is not a
 * login, because the app has no accounts.
 */
export function clientId(): string {
  if (typeof window === "undefined") return "";
  let id = window.localStorage.getItem(CLIENT_ID_KEY);
  if (!id) {
    id =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `client-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    window.localStorage.setItem(CLIENT_ID_KEY, id);
  }
  return id;
}

async function errorFrom(response: Response): Promise<Error> {
  return new Error(await response.text());
}

export async function createUpload(
  file: File,
): Promise<{ id: string; uploadUrl: string }> {
  const response = await fetch(ATTACHMENTS_API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Client-Id": clientId(),
    },
    body: JSON.stringify({
      filename: file.name,
      content_type: contentTypeOf(file.name),
      size_bytes: file.size,
    }),
  });
  if (!response.ok) throw await errorFrom(response);

  const body = await response.json();
  return { id: body.id, uploadUrl: body.upload_url };
}

/** PUT straight to S3; XHR is used only because fetch has no upload progress. */
export function uploadToS3(
  uploadUrl: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", uploadUrl);
    // the presigned URL signs this exact value, and S3 stores it
    request.setRequestHeader("Content-Type", contentTypeOf(file.name) ?? "");

    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total);
      }
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload failed (${request.status}).`));
      }
    };
    request.onerror = () =>
      reject(new Error("Upload failed. Check your connection and try again."));
    request.onabort = () => reject(new Error("Upload cancelled."));

    request.send(file);
  });
}

export async function confirmUpload(
  attachmentId: string,
): Promise<UploadedAttachment> {
  const response = await fetch(attachmentConfirmUrl(attachmentId), {
    method: "POST",
    headers: { "X-Client-Id": clientId() },
  });
  if (!response.ok) throw await errorFrom(response);

  const body = await response.json();
  return {
    id: body.id,
    filename: body.filename,
    sizeBytes: body.size_bytes,
  };
}

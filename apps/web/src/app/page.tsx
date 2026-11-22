"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Form, { type AttachmentDraft } from "@/components/form";
import Message, { type MessageAttachment } from "@/components/message";
import cx from "@/utils/cx";
import PoweredBy from "@/components/powered-by";
import MessageLoading from "@/components/message-loading";
import ErrorMessage from "@/components/error-message";
import { INITIAL_QUESTIONS } from "@/utils/const";
import { chatApiUrl, jobUrl, retryJobUrl } from "@/utils/api";
import {
  clientId,
  confirmUpload,
  createUpload,
  uploadToS3,
  validateFile,
  type UploadedAttachment,
} from "@/utils/attachments";
import {
  TIMEOUT_MESSAGE,
  friendlyErrorForCode,
  friendlyErrorMessage,
} from "@/utils/errors";

const POLL_INTERVAL_MS = 1000;
// the worker retries a failed attempt with backoff, so allow more than one try
const RESPONSE_TIMEOUT_MS = 120000;

type Role = "system" | "user" | "assistant";

interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  attachment?: MessageAttachment;
}

interface Job {
  id: string;
  status: string;
  result: string | null;
  code: string | null;
}

const WELCOME: ChatMessage = {
  id: "welcome",
  role: "system",
  content: `**Welcome to Rivet AI**

Your AI assistant for questions, explanations, writing, and summaries.`,
};

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// the API answers a failure with {"code","error"}, which friendlyErrorMessage reads
async function requireOk(response: Response): Promise<Response> {
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response;
}

function jobErrorMessage(job: Job): string {
  return friendlyErrorForCode(job.code ?? "server_error");
}

export default function Home() {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);
  const failedPromptRef = useRef<string | null>(null);
  // the job the Retry button should retry; null when no job id was ever returned
  const failedJobIdRef = useRef<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [attachment, setAttachment] = useState<UploadedAttachment | null>(null);
  const [uploading, setUploading] = useState<AttachmentDraft | null>(null);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);

  useEffect(() => {
    // ignore a poll that resolves after the screen goes away
    return () => {
      requestIdRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView();
    }
  }, [messages, chatError, busy]);

  // polls one job until it finishes, fails or the poll budget runs out
  const trackJob = useCallback(async (job: Job, requestId: number) => {
    let current = job;
    const deadline = Date.now() + RESPONSE_TIMEOUT_MS;
    // if anything below fails, this is the job the Retry button acts on
    failedJobIdRef.current = job.id;

    while (requestIdRef.current === requestId) {
      if (current.status === "succeeded") {
        const reply: ChatMessage = {
          id: `${current.id}-reply`,
          role: "assistant",
          content: current.result ?? "",
        };
        setMessages((messages) => [...messages, reply]);
        failedJobIdRef.current = null;
        return;
      }
      if (current.status === "failed") {
        setChatError(jobErrorMessage(current));
        return;
      }
      if (Date.now() >= deadline) {
        setChatError(TIMEOUT_MESSAGE);
        return;
      }

      await wait(POLL_INTERVAL_MS);
      if (requestIdRef.current !== requestId) return;

      const poll = await requireOk(await fetch(jobUrl(current.id)));
      current = await poll.json();
    }
  }, []);

  const retry = useCallback(
    async (jobId: string) => {
      setChatError(null);
      setBusy(true);
      const requestId = ++requestIdRef.current;

      try {
        const response = await requireOk(
          await fetch(retryJobUrl(jobId), { method: "POST" }),
        );
        await trackJob(await response.json(), requestId);
      } catch (error) {
        if (requestIdRef.current === requestId) {
          setChatError(friendlyErrorMessage(error as Error));
        }
      } finally {
        if (requestIdRef.current === requestId) {
          setBusy(false);
        }
      }
    },
    [trackJob],
  );

  const onSelectFile = useCallback(
    async (file: File) => {
      if (busy || uploading) return;

      const problem = validateFile(file);
      if (problem) {
        setAttachmentError(problem);
        return;
      }

      setAttachmentError(null);
      setAttachment(null);
      setUploading({ filename: file.name, size: file.size, progress: 0 });

      try {
        const { id, uploadUrl } = await createUpload(file);
        await uploadToS3(uploadUrl, file, (progress) =>
          setUploading({ filename: file.name, size: file.size, progress }),
        );
        setAttachment(await confirmUpload(id));
      } catch (error) {
        setAttachmentError(friendlyErrorMessage(error as Error));
      } finally {
        setUploading(null);
      }
    },
    [busy, uploading],
  );

  const onRemoveAttachment = () => {
    setAttachment(null);
    setAttachmentError(null);
  };

  const send = useCallback(
    async (raw: string, options?: { appendUser?: boolean }) => {
      const prompt = raw.trim();
      if (!prompt || busy || uploading) return;

      const pending = attachment;
      const appendUser = options?.appendUser ?? true;
      const history = appendUser
        ? [
            ...messages,
            {
              id: `${Date.now()}-user`,
              role: "user" as Role,
              content: prompt,
              attachment: pending
                ? { filename: pending.filename, size: pending.sizeBytes }
                : undefined,
            },
          ]
        : messages;

      if (appendUser) setMessages(history);
      setInput("");
      setChatError(null);
      failedPromptRef.current = prompt;
      failedJobIdRef.current = null;
      setBusy(true);

      const requestId = ++requestIdRef.current;

      try {
        const response = await requireOk(
          await fetch(chatApiUrl(), {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(pending ? { "X-Client-Id": clientId() } : {}),
            },
            body: JSON.stringify({
              messages: history.map(({ role, content }) => ({ role, content })),
              ...(pending ? { attachment_id: pending.id } : {}),
            }),
          }),
        );

        // the job now owns the attachment, so the composer can let it go
        setAttachment(null);
        await trackJob(await response.json(), requestId);
      } catch (error) {
        if (requestIdRef.current === requestId) {
          setChatError(friendlyErrorMessage(error as Error));
        }
      } finally {
        if (requestIdRef.current === requestId) {
          setBusy(false);
        }
      }
    },
    [attachment, busy, messages, trackJob, uploading],
  );

  const onSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void send(input);
  };

  const onClickQuestion = (value: string) => {
    void send(value);
  };

  const onRetry = () => {
    if (busy) return;

    // a job id means the request reached the API: retry it as a new job
    if (failedJobIdRef.current) {
      void retry(failedJobIdRef.current);
      return;
    }

    // the request never got that far, so send the same prompt again
    const prompt = failedPromptRef.current;
    if (!prompt) return;
    const lastMessage = messages[messages.length - 1];
    const alreadyShown =
      lastMessage?.role === "user" && lastMessage.content === prompt;

    void send(prompt, { appendUser: !alreadyShown });
  };

  return (
    <main className="relative max-w-screen-md p-4 md:p-6 mx-auto flex min-h-svh !pb-32 md:!pb-40 overflow-y-auto">
      <div className="w-full">
        {messages.map((message: ChatMessage) => {
          return <Message key={message.id} {...message} />;
        })}

        {/* the worker is generating the reply */}
        {busy && <MessageLoading />}

        {/* error */}
        {chatError && (
          <ErrorMessage message={chatError} onRetry={onRetry} retrying={busy} />
        )}

        {/* initial question */}
        {messages.length === 1 && !chatError && (
          <div className="mt-4 md:mt-6 grid md:grid-cols-2 gap-2 md:gap-4">
            {INITIAL_QUESTIONS.map((message) => {
              return (
                <button
                  key={message.content}
                  type="button"
                  className="cursor-pointer select-none text-left bg-neutral-900 font-normal text-neutral-200
                  border border-neutral-800 rounded-xl p-3 md:px-4 md:py-3
                  hover:bg-neutral-800 hover:border-purple-500/50 hover:text-white"
                  onClick={() => onClickQuestion(message.content)}
                >
                  {message.content}
                </button>
              );
            })}
          </div>
        )}

        {/* bottom ref */}
        <div ref={messagesEndRef} />
      </div>

      <div
        className={cx(
          "fixed z-10 bottom-0 inset-x-0",
          "flex justify-center items-center",
          "bg-neutral-950",
        )}
      >
        <span
          className="absolute bottom-full h-10 inset-x-0 from-neutral-950/0
         bg-gradient-to-b to-neutral-950 pointer-events-none"
        />

        <div className="w-full max-w-screen-md rounded-xl px-4 md:px-5 py-6">
          <Form
            onSubmit={onSubmit}
            inputProps={{
              disabled: busy || uploading !== null,
              value: input,
              onChange: (e) => setInput(e.target.value),
            }}
            buttonProps={{
              disabled: busy || uploading !== null,
            }}
            attachment={
              uploading
                ? {
                    filename: uploading.filename,
                    size: uploading.size,
                    progress: uploading.progress,
                  }
                : attachment
                  ? {
                      filename: attachment.filename,
                      size: attachment.sizeBytes,
                      progress: null,
                    }
                  : null
            }
            attachmentError={attachmentError}
            onSelectFile={(file) => void onSelectFile(file)}
            onRemoveAttachment={onRemoveAttachment}
          />

          <PoweredBy />
        </div>
      </div>
    </main>
  );
}

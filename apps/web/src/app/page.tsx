"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Form from "@/components/form";
import Message from "@/components/message";
import cx from "@/utils/cx";
import PoweredBy from "@/components/powered-by";
import MessageLoading from "@/components/message-loading";
import ErrorMessage from "@/components/error-message";
import { INITIAL_QUESTIONS } from "@/utils/const";
import { CHAT_API_URL, jobUrl } from "@/utils/api";
import { TIMEOUT_MESSAGE, friendlyErrorMessage } from "@/utils/errors";

const POLL_INTERVAL_MS = 1000;
// the worker retries a failed attempt with backoff, so allow more than one try
const RESPONSE_TIMEOUT_MS = 120000;

type Role = "system" | "user" | "assistant";

interface ChatMessage {
  id: string;
  role: Role;
  content: string;
}

interface Job {
  id: string;
  status: string;
  result: string | null;
  code: string | null;
  error: string | null;
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

function jobErrorMessage(job: Job): string {
  const code = job.code ?? "server_error";
  return friendlyErrorMessage(new Error(JSON.stringify({ code })));
}

export default function Home() {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);
  const failedPromptRef = useRef<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

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

  const send = useCallback(
    async (raw: string, options?: { appendUser?: boolean }) => {
      const prompt = raw.trim();
      if (!prompt || busy) return;

      const appendUser = options?.appendUser ?? true;
      const history = appendUser
        ? [
            ...messages,
            { id: `${Date.now()}-user`, role: "user" as Role, content: prompt },
          ]
        : messages;

      if (appendUser) setMessages(history);
      setInput("");
      setChatError(null);
      failedPromptRef.current = prompt;
      setBusy(true);

      const requestId = ++requestIdRef.current;

      try {
        const response = await fetch(CHAT_API_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: history.map(({ role, content }) => ({ role, content })),
          }),
        });
        if (!response.ok) {
          throw new Error(await response.text());
        }

        let job: Job = await response.json();
        const deadline = Date.now() + RESPONSE_TIMEOUT_MS;

        while (requestIdRef.current === requestId) {
          if (job.status === "succeeded") {
            const reply: ChatMessage = {
              id: `${job.id}-reply`,
              role: "assistant",
              content: job.result ?? "",
            };
            setMessages((current) => [...current, reply]);
            return;
          }
          if (job.status === "failed") {
            setChatError(jobErrorMessage(job));
            return;
          }
          if (Date.now() >= deadline) {
            setChatError(TIMEOUT_MESSAGE);
            return;
          }

          await wait(POLL_INTERVAL_MS);
          if (requestIdRef.current !== requestId) return;

          const poll = await fetch(jobUrl(job.id));
          if (!poll.ok) {
            throw new Error(await poll.text());
          }
          job = await poll.json();
        }
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
    [busy, messages],
  );

  const onSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void send(input);
  };

  const onClickQuestion = (value: string) => {
    void send(value);
  };

  const onRetry = () => {
    if (busy || !failedPromptRef.current) return;

    const prompt = failedPromptRef.current;
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
              disabled: busy,
              value: input,
              onChange: (e) => setInput(e.target.value),
            }}
            buttonProps={{
              disabled: busy,
            }}
          />

          <PoweredBy />
        </div>
      </div>
    </main>
  );
}

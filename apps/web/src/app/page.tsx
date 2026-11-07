"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Message as MessageProps, useChat } from "ai/react";
import Form from "@/components/form";
import Message from "@/components/message";
import cx from "@/utils/cx";
import PoweredBy from "@/components/powered-by";
import MessageLoading from "@/components/message-loading";
import ErrorMessage from "@/components/error-message";
import { INITIAL_QUESTIONS } from "@/utils/const";
import { TIMEOUT_MESSAGE, friendlyErrorMessage } from "@/utils/errors";

const RESPONSE_TIMEOUT_MS = 45000;

export default function Home() {
  const formRef = useRef<HTMLFormElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failedPromptRef = useRef<string | null>(null);

  const [streaming, setStreaming] = useState<boolean>(false);
  const [chatError, setChatError] = useState<string | null>(null);

  const clearResponseTimeout = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    setInput,
    append,
    reload,
    stop,
  } = useChat({
    api: "/api/chat",
    initialMessages: [
      {
        id: "0",
        role: "system",
        content: `**Welcome to Rivet AI**

Your AI assistant for questions, explanations, writing, and summaries.`,
      },
    ],
    onResponse: () => {
      clearResponseTimeout();
      setStreaming(false);
    },
    onFinish: () => {
      clearResponseTimeout();
      setStreaming(false);
    },
    onError: (error) => {
      clearResponseTimeout();
      setStreaming(false);
      setChatError(friendlyErrorMessage(error));
    },
  });

  const startResponseTimeout = useCallback(() => {
    clearResponseTimeout();
    timeoutRef.current = setTimeout(() => {
      timeoutRef.current = null;
      stop();
      setStreaming(false);
      setChatError(TIMEOUT_MESSAGE);
    }, RESPONSE_TIMEOUT_MS);
  }, [clearResponseTimeout, stop]);

  useEffect(() => clearResponseTimeout, [clearResponseTimeout]);

  const onClickQuestion = (value: string) => {
    setInput(value);
    failedPromptRef.current = value;
    setTimeout(() => {
      formRef.current?.dispatchEvent(
        new Event("submit", {
          cancelable: true,
          bubbles: true,
        }),
      );
    }, 1);
  };

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView();
    }
  }, [messages, chatError]);

  const onSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (streaming) return;

      setChatError(null);
      failedPromptRef.current = input;
      handleSubmit(e);
      setStreaming(true);
      startResponseTimeout();
    },
    [handleSubmit, input, startResponseTimeout, streaming],
  );

  const onRetry = useCallback(() => {
    if (streaming) return;

    const prompt = failedPromptRef.current;
    const lastMessage = messages[messages.length - 1];

    setChatError(null);
    setStreaming(true);
    startResponseTimeout();

    // a failed request drops the user message, an aborted one keeps it
    if (
      prompt &&
      !(lastMessage?.role === "user" && lastMessage.content === prompt)
    ) {
      append({ role: "user", content: prompt });
    } else {
      reload();
    }
  }, [append, messages, reload, startResponseTimeout, streaming]);

  return (
    <main className="relative max-w-screen-md p-4 md:p-6 mx-auto flex min-h-svh !pb-32 md:!pb-40 overflow-y-auto">
      <div className="w-full">
        {messages.map((message: MessageProps) => {
          return <Message key={message.id} {...message} />;
        })}

        {/* loading */}
        {streaming && <MessageLoading />}

        {/* error */}
        {chatError && (
          <ErrorMessage
            message={chatError}
            onRetry={onRetry}
            retrying={streaming}
          />
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
            ref={formRef}
            onSubmit={onSubmit}
            inputProps={{
              disabled: streaming,
              value: input,
              onChange: handleInputChange,
            }}
            buttonProps={{
              disabled: streaming,
            }}
          />

          <PoweredBy />
        </div>
      </div>
    </main>
  );
}

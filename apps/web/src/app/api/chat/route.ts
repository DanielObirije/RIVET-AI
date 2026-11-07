import { NextRequest, NextResponse } from "next/server";
import { StreamingTextResponse } from "ai";

export const runtime = "edge";

const DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions";
const UPSTREAM_TIMEOUT_MS = 40000;

const SYSTEM_PROMPT = `You are Rivet AI, a helpful general-purpose AI assistant.

You answer general questions, explain technical topics in plain language, help people write and improve content, summarize information, and hold natural conversations.

Stay conversational, not developmental. Do not generate, debug, or review code, and do not recommend programming tools or libraries. If someone asks for code or debugging help, explain kindly that Rivet AI is a conversational assistant rather than a coding assistant, then offer the concept in plain language instead.

Be accurate, clear, and concise. Use Markdown when it helps: short paragraphs, and lists or headings for longer answers. Ask a short clarifying question only when a request is genuinely ambiguous. If you do not know something, say so instead of guessing.`;

const FRIENDLY_ERRORS = {
  rate_limit:
    "Oops! It seems you've reached the rate limit. Please try again later.",
  timeout: "That request took too long. Please try again.",
  network:
    "Rivet AI can't reach the model right now. Please try again in a moment.",
  unavailable:
    "Rivet AI is unavailable right now. Please try again in a moment.",
  server_error:
    "Something went wrong while generating that reply. Please try again.",
  bad_request: "That message couldn't be processed. Try rephrasing it.",
  missing_config: "Rivet AI isn't fully set up yet. Please try again later.",
} as const;

type ErrorCode = keyof typeof FRIENDLY_ERRORS;

const ERROR_STATUS: Record<ErrorCode, number> = {
  rate_limit: 429,
  timeout: 504,
  network: 502,
  unavailable: 503,
  server_error: 502,
  bad_request: 400,
  missing_config: 500,
};

function errorResponse(code: ErrorCode) {
  return NextResponse.json(
    { code, error: FRIENDLY_ERRORS[code] },
    { status: ERROR_STATUS[code] },
  );
}

type ChatMessage = { role: string; content: string };

export async function POST(req: NextRequest) {
  const apiKey = process.env.DEEPSEEK_API_KEY;

  if (!apiKey) {
    console.error("DeepSeek chat error: DEEPSEEK_API_KEY is not configured.");
    return errorResponse("missing_config");
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return errorResponse("bad_request");
  }

  const messages: ChatMessage[] = (
    Array.isArray(body?.messages) ? body.messages : []
  ).filter(
    (message: ChatMessage) =>
      message?.role === "user" || message?.role === "assistant",
  );

  if (messages.length === 0) {
    return errorResponse("bad_request");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(DEEPSEEK_API_URL, {
      method: "POST",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: process.env.DEEPSEEK_MODEL || "deepseek-chat",
        stream: true,
        temperature: 0.7,
        messages: [
          { role: "system", content: SYSTEM_PROMPT },
          ...messages.map(({ role, content }) => ({ role, content })),
        ],
      }),
    });
  } catch (error) {
    clearTimeout(timeout);
    const aborted = error instanceof Error && error.name === "AbortError";
    console.error(
      "DeepSeek chat error:",
      aborted ? "upstream timed out" : "upstream unreachable",
    );
    return errorResponse(aborted ? "timeout" : "network");
  }

  if (!response.ok || !response.body) {
    // detail stays in the server log; users only see the friendly message
    const detail = await response.text().catch(() => "");
    console.error(
      `DeepSeek chat error: upstream responded ${response.status}`,
      detail.slice(0, 500),
    );
    clearTimeout(timeout);

    if (response.status === 429 || response.status === 402) {
      return errorResponse("rate_limit");
    }
    if (response.status >= 500) {
      return errorResponse("unavailable");
    }
    return errorResponse("server_error");
  }

  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = "";

  // DeepSeek streams SSE: "data: {json}" lines ending with "data: [DONE]"
  const stream = new ReadableStream({
    async start(streamController) {
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data:")) continue;

            const payload = trimmed.slice(5).trim();
            if (payload === "[DONE]") {
              streamController.close();
              clearTimeout(timeout);
              return;
            }

            let content: string | undefined;
            try {
              content = JSON.parse(payload).choices?.[0]?.delta?.content;
            } catch {
              continue;
            }

            if (content) streamController.enqueue(encoder.encode(content));
          }
        }
        streamController.close();
      } catch (error) {
        console.error(
          "DeepSeek chat error: stream interrupted",
          error instanceof Error ? error.name : "unknown",
        );
        streamController.error(new Error("stream_interrupted"));
      } finally {
        clearTimeout(timeout);
      }
    },
    cancel() {
      clearTimeout(timeout);
      reader.cancel();
    },
  });

  return new StreamingTextResponse(stream);
}

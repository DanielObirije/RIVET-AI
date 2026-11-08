# Rivet AI API

FastAPI backend for Rivet AI. It owns every backend responsibility the app used
to keep inside Next.js:

- request validation for chat payloads
- the system prompt and conversation assembly
- the DeepSeek chat completion call (streaming SSE)
- upstream error classification and user-safe error messages
- conversation statelessness: history arrives in the request body, nothing is
  persisted (no database or vector store exists in this project)

## Layout

```
app/main.py             FastAPI app, CORS, JSON error handlers
app/config.py           env-backed settings (key, model, CORS origins)
app/errors.py           error codes, status mapping, ChatError
app/schemas.py          ChatRequest / ChatMessage validation
app/routes/chat.py      POST /api/chat
app/services/deepseek.py  upstream call, SSE parsing, error classification
tests/test_chat.py      route + parser tests
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env      # add DEEPSEEK_API_KEY
```

## Run

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000 --env-file .env
```

OpenAPI docs: http://localhost:8000/docs

The Next.js app expects this at `http://localhost:8000` by default; change it
with `NEXT_PUBLIC_API_BASE_URL` in `apps/web/.env.local`. If you move the web
app or the API to another origin, add that origin to `CORS_ALLOWED_ORIGINS`
(comma separated).

## Endpoints

`GET /health` -> `{"status": "ok"}`

`POST /api/chat`

```json
{ "messages": [{ "role": "user", "content": "Hi" }] }
```

Returns a `text/plain` stream of content deltas, which is what the `ai`
package's `useChat` consumes. Only `user` and `assistant` messages are
forwarded; a client-side `system` message is dropped and the server prompt is
used instead.

Failures return `{"code", "error"}` with a curated message, matching the codes
the frontend already understands:

| code             | status | meaning                          |
| ---------------- | ------ | -------------------------------- |
| `bad_request`    | 400    | unreadable or empty payload      |
| `rate_limit`     | 429    | upstream 402/429                 |
| `network`        | 502    | upstream unreachable             |
| `server_error`   | 502    | upstream rejected the request    |
| `unavailable`    | 503    | upstream 5xx                     |
| `timeout`        | 504    | upstream exceeded 40s            |
| `missing_config` | 500    | `DEEPSEEK_API_KEY` not set       |

Stack traces and upstream response bodies stay in the server log only.

## Tests

```bash
source .venv/bin/activate
pytest
```

The suite uses `httpx.MockTransport`, so it never calls DeepSeek.

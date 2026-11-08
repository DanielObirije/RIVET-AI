# Rivet AI

A general-purpose AI chat app. Next.js renders the UI and talks to a FastAPI
backend, which records each chat turn as a job. A Celery worker in `apps/worker`
generates the reply; the browser polls the job until it is ready.

## Features

- Asynchronous chat: submit a message, get a job id, poll for the finished reply
- A generating state while the worker is running
- Markdown rendering with code blocks
- Conversations stay in the browser for the current session, nothing is stored
- Responsive layout on mobile and desktop

## Getting started

This app is the frontend only. The API and the worker both need to be running
(see `apps/api/README.md` and `apps/worker/README.md`), and Redis must be up so
the API can publish jobs.

1. Install dependencies:

   ```bash
   npm install
   ```

2. Create `.env.local` from the example and point it at the backend:

   ```bash
   cp .env.local.example .env.local
   ```

   ```dotenv
   NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
   ```

   Only the backend URL is public here. The DeepSeek key belongs to the worker
   and never reaches the browser.

3. Run the app:

   ```bash
   npm run dev
   ```

   Open http://localhost:3000.

## How a message travels

1. `POST /api/chat` with `{messages: [{role, content}, ...]}`. The history is
   held in React state and sent on every turn; the server does not keep it.
2. The API answers `202` with `{id, status: "queued"}`.
3. The page polls `GET /api/jobs/{id}` once a second, for up to 120 seconds
   (enough for one worker retry).
4. On `succeeded` the reply is appended as an assistant message. On `failed` the
   job's error code is mapped to the same friendly text the API uses, and the
   message can be retried.

The loading indicator (bouncing dots plus "Generating your reply...") is shown
while a job is queued, running or being polled.

## Project structure

```
src/app/page.tsx             Chat screen, job submission, polling, retry handling
src/components/              Message bubbles, form, loading indicator, logo
src/utils/api.ts             API base URL, chat submit URL, job status URL
src/utils/                   Shared helpers, error text, starter prompts
```

## Why polling instead of streaming

The reply arrives as one block. That is a deliberate trade-off: the backend
accepts a message immediately, the worker owns the slow model call, and neither
the browser nor the API holds an open connection to the provider. The cost is
that text does not appear token by token.

The previous version streamed deltas straight from the API. That kept the model
call inside the web request, which is what the API/worker split exists to avoid.
Streaming through the worker (worker publishes chunks, API relays them over SSE)
is a documented future option in `apps/worker/README.md`; it is not implemented.

Revisit this when time-to-first-token matters enough to justify a second
transport. Until then, polling is one cheap database read per second and needs
no extra infrastructure.

## Scripts

| Command         | Description              |
| --------------- | ------------------------ |
| `npm run dev`   | Start the dev server     |
| `npm run build` | Production build         |
| `npm start`     | Run the production build |
| `npm run lint`  | Lint with ESLint         |

# Rivet AI

A general-purpose AI chat app. Next.js renders the UI and streams replies from a
FastAPI backend, which owns all AI orchestration and the DeepSeek API call.

## Features

- Streaming chat responses from the FastAPI backend (`deepseek-chat` by default)
- Markdown rendering with code blocks
- Conversations stay in the browser for the current session, nothing is stored
- Responsive layout on mobile and desktop

## Getting started

This app is the frontend only. The chat endpoint, validation, DeepSeek call, and
error handling live in the FastAPI backend in `apps/api`, so start that first
(see `apps/api/README.md`).

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

   Only the backend URL is public here. The DeepSeek key belongs in
   `apps/api/.env` and never reaches the browser.

3. Run the app:

   ```bash
   npm run dev
   ```

   Open http://localhost:3000.

## Scripts

| Command         | Description              |
| --------------- | ------------------------ |
| `npm run dev`   | Start the dev server     |
| `npm run build` | Production build         |
| `npm start`     | Run the production build |
| `npm run lint`  | Lint with ESLint         |

## Project structure

```
src/app/page.tsx   Chat screen, streaming state, retry handling
src/components/    Message bubbles, form, loading indicator, logo
src/utils/api.ts   FastAPI base URL and chat endpoint
src/utils/         Shared helpers, error text, starter prompts
```

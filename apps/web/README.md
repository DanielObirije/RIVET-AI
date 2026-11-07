# Rivet AI

A general-purpose AI chat app built with Next.js and streaming responses from
[DeepSeek](https://www.deepseek.com).

## Features

- Streaming chat responses from the DeepSeek API (`deepseek-chat` by default)
- Markdown rendering with code blocks
- Conversations stay in the browser for the current session, nothing is stored
- Responsive layout on mobile and desktop

## Getting started

1. Install dependencies:

   ```bash
   npm install
   ```

2. Create `.env.local` from the example and add your DeepSeek API key:

   ```bash
   cp .env.local.example .env.local
   ```

   ```dotenv
   DEEPSEEK_API_KEY=your-key-here
   # DEEPSEEK_MODEL=deepseek-chat
   ```

   The key is only read on the server in `src/app/api/chat/route.ts`, never in
   client code.

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
src/app/api/chat/route.ts   DeepSeek streaming endpoint
src/app/page.tsx            Chat screen
src/components/             Message bubbles, form, loading indicator, logo
src/utils/                  Shared helpers and starter prompts
```

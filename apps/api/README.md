# Rivet AI API

FastAPI is the HTTP edge of Rivet AI. It owns request validation, job records,
publishing a job id to Amazon SQS and result retrieval. It does **not** call the
AI provider. Every completion runs in the Python SQS worker in `apps/worker`.

That boundary is deliberate: the API process is short-lived and request-bound,
while a model call is slow, can time out, and needs retries. Keeping the two
apart lets each scale and fail on its own. Neither service imports the other:
the contracts are the queue message and the `jobs` table.

## Request flow (implemented)

```text
browser
  |  POST /api/chat  {messages: [...]}
  v
FastAPI  validates -> inserts a `queued` row -> sends {"job_id": "..."} to SQS
  |                                             |
  |  202 {id, status: "queued"}                 v
  v                                    main queue  --redrive-->  DLQ
browser polls GET /api/jobs/{id}                |
  |                                             | long poll, claim, DeepSeek
  |                                             | write `succeeded` + reply
  +-------------------------------------------->|
```

1. The browser posts the whole conversation to `POST /api/chat`.
2. The API keeps only `user` and `assistant` turns (a client-side `system`
   message is replaced by the server prompt in the worker), inserts a `queued`
   row in `jobs`, and publishes one SQS message: `{"job_id": "..."}`. The
   message carries nothing else; the conversation stays in PostgreSQL.
3. The API returns `202` immediately with the job id. It never waits for the
   model.
4. The worker long-polls the queue, claims the row, calls DeepSeek and writes
   the outcome. It deletes the message only after that write commits.
5. The browser polls `GET /api/jobs/{id}` until the row says `succeeded`
   (`result` holds the reply) or `failed` (`code` and `error` explain it). If the
   reply never arrives, it stops after two minutes and offers Retry, which posts
   `POST /api/jobs/{id}/retry` and polls the new job.

There is exactly one AI execution path: a chat request becomes a job, and only
the worker runs jobs. The API holds no DeepSeek key and imports no provider
client, so a direct call cannot creep back in.

## Layout

```
app/main.py             FastAPI app, CORS, JSON error handlers
app/config.py           env-backed settings (CORS, database URL, queue URL, region)
app/queue.py            Boto3 SQS publisher; imports no worker code
app/errors.py           error codes, status mapping, user-safe messages
app/schemas.py          ChatRequest / ChatMessage / JobResponse, allowed roles
app/jobs.py             jobs table + submit_job / submit_retry (the write paths)
app/routes/chat.py      POST /api/chat
app/routes/jobs.py      POST /api/jobs, GET /api/jobs/{id}
tests/                  route, validation, job and publisher tests
```

This app imports nothing from `apps/worker` and nothing from `apps/web`. It
reaches the worker through two contracts only: the SQS message body
`{"job_id": "<id>"}` (`app/queue.py`) and the `jobs` table. The message body and
the table's DDL are kept in step by hand with the worker's copies, because the
two services share no package. Each app is still its own deployment.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

PostgreSQL 16 runs locally as a normal server. Create the role and the two empty
databases once:

```bash
psql -d postgres -c "CREATE ROLE rivet LOGIN PASSWORD 'rivet';"
psql -d postgres -c "CREATE DATABASE rivet OWNER rivet;"
psql -d postgres -c "CREATE DATABASE rivet_test OWNER rivet;"   # test suite only
```

Both services read `DATABASE_URL`. The default is
`postgresql://rivet:rivet@localhost:5432/rivet`, so no export is needed for
local work. There is no migration step: `app/jobs.py` runs
`CREATE TABLE IF NOT EXISTS jobs` the first time a process touches the database,
so an empty database is enough. For AWS RDS, change only `DATABASE_URL` to the
RDS endpoint with `sslmode=require`.

Each process opens its own pool: `DB_POOL_MIN_SIZE` connections held open
(default 1) and at most `DB_POOL_MAX_SIZE` (default 8). The worker reads the same
two variables with the same defaults, so one value set sizes every instance and
`max_connections` on RDS stays predictable as instances are added.

No `DEEPSEEK_API_KEY` here. The model credential belongs to the worker only.

## Run

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000 --env-file .env
```

`--env-file .env` is what loads the file; nothing in the app reads it on its own.
Set `SQS_QUEUE_URL` there (or export it) and have the worker running, or a chat
submission answers `503 enqueue_failed`:

```text
# the queue the worker polls; there is no default on purpose
SQS_QUEUE_URL=http://localhost:4566/000000000000/rivet-jobs   # LocalStack
AWS_REGION=us-east-1
SQS_ENDPOINT_URL=http://localhost:4566                        # LocalStack only
```

There is no AWS infrastructure yet. For local queue work, run LocalStack and
create the queue once (dummy credentials are enough, they are never used to sign
anything real):

```bash
docker run --rm -d -p 4566:4566 --name rivet-localstack localstack/localstack
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  aws --endpoint-url http://localhost:4566 --region us-east-1 \
  sqs create-queue --queue-name rivet-jobs
```

Production uses no endpoint URL: boto3 talks to the regional SQS endpoint and
takes credentials from the IAM role attached to the task. Nothing in this service
asks for credentials at import time, so imports, tests and the OpenAPI docs work
on a machine with no AWS access at all.

OpenAPI docs: http://localhost:8000/docs

The Next.js app expects this at `http://localhost:8000` by default; change it
with `NEXT_PUBLIC_API_BASE_URL` in `apps/web/.env.local`. If you move the web
app or the API to another origin, add that origin to `CORS_ALLOWED_ORIGINS`
(comma separated).

## Docker

This directory is the deployable unit: build the image here and run it on its
own, with no dependency on the other two apps' images.

```bash
docker build -t rivet-api .
docker run --rm --env-file .env -p 8000:8000 rivet-api
```

Inside the container `localhost` is the container, so point `DATABASE_URL` and
the endpoint URLs at the host or at real AWS, not at `localhost`.

For local work, `docker-compose.yml` in this directory starts this app with
Postgres and LocalStack and creates the queue and bucket:

```bash
docker compose up -d --build
```

It publishes 5432 and 4566 as well, because the worker container and a browser
uploading through a presigned URL have to reach them.

## Endpoints

`GET /health` -> `{"status": "ok"}`

`POST /api/chat` and `POST /api/jobs` take the same body:

```json
{ "messages": [{ "role": "user", "content": "Hi" }] }
```

Both answer `202` with the job record. They share one implementation
(`app/jobs.py:submit_job`); `/api/chat` is kept because it is the URL the web
app already used, so a chat submission has one destination and one code path.

```json
{ "id": "8f1c...", "status": "queued", "result": null, "code": null, "error": null, "retry_of": null }
```

`GET /api/jobs/{id}` returns the same shape. `status` is `queued`, `running`,
`succeeded` (then `result` holds the reply) or `failed` (then `code` and
`error` explain it). `retry_of` is set when the job was started by a retry. An
unknown id is `404` with code `not_found`.

`POST /api/jobs/{id}/retry` starts a new job from an existing one and answers
`202` with the new record. It copies the stored conversation, writes a fresh
`queued` row whose `retry_of` points at the original, and publishes the new id.
The original row is never modified. A second click while that retry is still
`queued` or `running` returns the same retry instead of starting another one, so
a double submit cannot run twice. Retrying is refused with `409` only when the
original already `succeeded`; a job stuck in `queued` or `running` (for example
because its message exhausted its SQS redeliveries and was moved to the DLQ) can
be retried, which is how a user recovers without anyone touching the DLQ. The
conversation comes from PostgreSQL, so this endpoint never reads a queue.

The one check this endpoint cannot make today is ownership: the app has no
authenticated user and no owner column, so any caller who knows an id can retry
it. When authentication arrives, that check goes in `submit_retry`, inside the
same transaction that locks the original row.

Failures return `{"code", "error"}` with a curated message:

| code             | status | meaning                                    |
| ---------------- | ------ | ------------------------------------------ |
| `bad_request`    | 400    | unreadable or empty payload                |
| `not_found`      | 404    | no job with that id                        |
| `not_retryable`  | 409    | that job already succeeded                 |
| `enqueue_failed` | 503    | no queue configured or SQS rejected it     |

A job that fails inside the worker reports `rate_limit`, `timeout`, `network`,
`unavailable`, `server_error` or `missing_config` on `GET /api/jobs/{id}`; the
API maps those to the same friendly text. Stack traces and upstream response
bodies stay in the server log only.

## Attachments

One file per message: PDF, DOC, DOCX or PNG, up to `MAX_UPLOAD_SIZE_MB` (1 MB by
default). File bytes never pass through this service.

1. `POST /api/attachments` with the filename, content type and size records a
   `pending` row and returns a 5-minute presigned PUT URL.
2. The browser PUTs the file straight to the private bucket.
3. `POST /api/attachments/{id}/confirm` checks that the object exists, is within
   the limit, has the expected content type and starts with the signature for
   its extension. It then copies the object from `uploads/pending/` to
   `uploads/attached/` and marks the row `attached`.
4. `POST /api/chat` or `POST /api/jobs` with `attachment_id` binds that row to
   the job in the same transaction that inserts the job.
5. `GET /api/attachments/{id}/url` returns a 5-minute presigned GET URL.

Attachment endpoints require an `X-Client-Id` header, an opaque id the browser
keeps in localStorage. It scopes an attachment to one browser. The app has no
accounts, so this is ownership scoping, not authentication: a caller who knows
both ids can still forge the header.

The API sweeps `pending` rows older than `PENDING_UPLOAD_TTL_HOURS` (24) on each
new upload and deletes their objects, at most 25 per call. The S3 lifecycle rule
below is the backstop.

Attachment failures use the same `{"code", "error"}` shape: `unsupported_file`
(400), `file_too_large` (400), `forbidden` (403), `attachment_not_ready` (409),
`attachment_missing` (404), `attachment_unreadable` (422, worker),
`image_unsupported` (415, worker; only when a text-only model is configured,
since the default `deepseek-flash` reads PNGs) and `storage_unavailable` (503).

### Required S3 configuration

- **Bucket:** private, Block Public Access on, no public ACLs. The app never
  sends one. Upload and download access is presigned and short-lived.
- **CORS:** allow the web origin to `PUT` with `Content-Type`:

  ```json
  [
    {
      "AllowedOrigins": ["http://localhost:3000"],
      "AllowedMethods": ["PUT"],
      "AllowedHeaders": ["Content-Type"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 300
    }
  ]
  ```

- **API role:** `s3:PutObject` on `uploads/*` (the presigned PUT is signed with
  these credentials), `s3:GetObject` on `uploads/*` (HEAD and the signature
  read), `s3:DeleteObject` on `uploads/pending/*`, and `s3:GetObject` on the
  copy source plus `s3:PutObject` on `uploads/attached/*` for the confirm copy.
- **Worker role:** `s3:GetObject` on `uploads/attached/*`.
- **Lifecycle:** expire `uploads/pending/` after 1 day. This cleans up an upload
  whose confirm never arrived even if the API never sweeps it.

## Decisions behind this service

### FastAPI and the worker are separate services

**Decision.** The HTTP API and the AI processing run as two processes with no
shared code and no in-process hand-off.

**Why.** They have different failure modes and scaling curves. An API pod is
cheap, request-bound and must answer quickly; a worker holds a 40-second
outbound call and may retry. If the model provider is slow, the API must still
accept messages. If the API is restarted, queued work must not be lost.

**Alternatives considered.** One process that runs the model call inline;
FastAPI `BackgroundTasks`; Python threads.

**Why not.** Inline calls couple browser latency to provider latency and make a
restart drop in-flight work. `BackgroundTasks` and threads keep the work inside
the web process: no independent scaling, no retry semantics, and a deploy kills
the work. Both were rejected for the same reason.

**Trade-off.** More moving parts: two images, a queue, and a database both
services can reach.

**Reconsider if.** The workload becomes trivially fast (sub-second, no retries),
or the operational cost of two services outweighs the isolation on a much
smaller deployment.

### The API publishes jobs instead of generating replies

**Decision.** `POST /api/chat` validates, writes a `queued` row, publishes the
job id, and returns `202`.

**Why.** Publishing is fast and predictable. The HTTP response no longer depends
on the provider, so the API can enforce its own timeout and the worker can
retry without the browser holding a connection open.

**Alternatives considered.** Streaming the provider response straight through
the API (the previous implementation); awaiting a non-streaming completion in
the request handler.

**Why not.** Both make the browser wait on the provider and lose the work when
the request or process ends. Straight-through streaming also cannot use a worker
at all without extra streaming infrastructure.

**Trade-off.** The browser must poll, and a reply arrives as one block instead of
token by token.

**Reconsider if.** Token-by-token output becomes a product requirement. That is
a future change, described in `apps/worker/README.md`, not something implemented
here.

### Amazon SQS carries the job messages

**Decision.** The API publishes one JSON message per job to an SQS queue with
Boto3: `{"job_id": "..."}`. The worker long-polls that queue. A second queue is
wired as the DLQ through the main queue's redrive policy.

**Why.** It is the managed queue the AWS deployment needs: no Redis to operate,
delivery retries and a dead-letter queue handled by AWS, long polling instead of
a tight loop, and IAM for access. Messages stay small because the conversation
and the result live in PostgreSQL, so a redelivered message always reads current
state rather than a stale copy.

**Alternatives considered.** Redis with Celery (the previous implementation);
RabbitMQ; a database-backed queue table; in-process queues.

**Why not.** Redis and RabbitMQ mean running and securing another service that
AWS already offers, and Celery's retry state would sit outside the `jobs` table.
A queue table turns the database into a broker and needs its own polling and
locking. In-process queues break the process boundary.

**Trade-off.** SQS is at-least-once, so a job can be delivered twice; the worker
guards that with a conditional claim on `jobs`. SQS also does not update
PostgreSQL, so a message that ends up in the DLQ leaves its row behind in
`queued` or `running`. Nothing in either service repairs that, by design: the
DLQ is for investigation, and the user-facing recovery is
`POST /api/jobs/{id}/retry`, which starts a new job from the stored conversation
without touching the dead-lettered message. Local development needs LocalStack
(or another SQS-compatible endpoint) because there is no local default.

**Reconsider if.** Message volume or ordering needs outgrow a standard queue: FIFO
queues, or a different broker, would be the next step. The submission path only
needs a queue URL, so the API's side would not change.

### A row can be committed without its message (known gap)

**Decision.** `submit_job` inserts the row first and publishes second. When the
send fails, the row is marked `failed` / `enqueue_failed` and the request answers
`503`, so the caller never receives an id that nothing will ever run.

**Why.** That is the only failure the process can observe and repair in-line, and
it costs one UPDATE.

**Known gap.** If the process dies between the INSERT commit and `send_message`,
the row stays `queued` with no message behind it. No worker will pick it up, and
nothing sweeps for it. The user sees a poll that never finishes and retries, which
starts a new job.

**Why not a transactional outbox now.** An outbox means an extra table plus a
publisher process, and a sweeper means a clock and a second writer racing the
normal path. Both are real components for a single-crash window.

**Reconsider if.** Losing an accepted job becomes unacceptable. The smallest
useful step is a one-off command that re-publishes jobs still `queued` after a
few minutes, run by hand or from a scheduled task, not a new service.

### PostgreSQL is the only application database

**Decision.** Job state lives in PostgreSQL, reached through `DATABASE_URL`. The
API and the worker read the same value, so they share one database and one
`jobs` table. Local development runs PostgreSQL 16 as a local server;
production points the same variable at Amazon RDS.

**Why.** The API and the worker are separate processes and, on AWS, separate
hosts and images. A network database both can reach is the only way for the API
to create a row and the worker to claim it. Developing against PostgreSQL from
the start means the SQL, types and locking behaviour are the ones that will run on
RDS, with no second dialect to debug at deploy time.

**Alternatives considered.** Keeping SQLite for local work and switching at
deploy time; a second database just for jobs; the queue's own result store as the
source of truth.

**Why not.** SQLite is a file on one host: separate services cannot share it,
and its single-writer locking hides the concurrency problems PostgreSQL will
expose. A second database doubles the operational surface and splits job state
from application state. Keeping results in the queue would move the source of
truth out of the `jobs` table, and SQS has no result store anyway.

**Trade-off.** Local development needs a running PostgreSQL server; the database
must exist, though its tables do not. Every request now depends on the database
being reachable.

**Reconsider if.** Never back to SQLite. Revisit PostgreSQL itself only if the
deployment target moves away from RDS, or job volume outgrows a single primary
and a `jobs` table stops being the right shape.

### Pooled connections and table creation

**Decision.** Each process keeps one `psycopg` connection pool (1 to 8
connections). Every job function checks out a connection, runs its own transaction
and returns it. The `jobs` table is created by `CREATE TABLE IF NOT EXISTS` on
the first call in each process (`ensure_schema` in `app/jobs.py`), and the same
DDL sits in `apps/worker/jobs.py`.

**Why.** The API serves requests from FastAPI's thread pool and the worker
handles messages from its own thread, so a module-level shared connection would
be a data race. A pool gives each call its own connection while amortising the
handshake. Creating the table from code keeps setup to "the database exists":
there is no migration command to run before the first request.

**Alternatives considered.** One connection per process behind a lock; a fresh
connection per request without a pool; a migration tool such as Alembic.

**Why not.** A single locked connection serialises every request. Per-request
connections work but pay a TCP and authentication handshake each time. A
migration tool is the right answer once the schema keeps changing; with one
stable table it adds a dependency, a deploy step and a second copy of the DDL.

**Trade-off.** The DDL exists twice (here and in the worker) and the two copies
must be edited together. A schema change is deployed by rolling out new code,
not by running a command against the database, and `IF NOT EXISTS` never alters
an existing table.

**Reconsider if.** The schema grows past a table or two, or existing databases
need data migrations. At that point add Alembic and move the DDL out of the
application.

## Tests

```bash
source .venv/bin/activate
pytest
```

The suite drives the real routes with `TestClient` against PostgreSQL: the job
store creates `jobs` if it is missing and `jobs` is truncated before each test.
The publish step is stubbed for every test (`tests/conftest.py`), and
`tests/test_queue.py` checks the publisher itself against a fake SQS client, so
no test needs an AWS credential, an AWS account or an SQS queue.
`RIVET_TEST_DATABASE_URL` defaults to
`postgresql://rivet:rivet@localhost:5432/rivet_test`, which must exist and must
not be the development database. Never point it at `rivet`: the suite truncates
whatever it points at.

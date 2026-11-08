# Rivet AI API

FastAPI is the HTTP edge of Rivet AI. It owns request validation, job records,
task publishing and result retrieval. It does **not** call the AI provider.
Every completion runs in the Celery worker in `apps/worker`.

That boundary is deliberate: the API process is short-lived and request-bound,
while a model call is slow, can time out, and needs retries. Keeping the two
apart lets each scale and fail on its own.

## Request flow (implemented)

```text
browser
  |  POST /api/chat  {messages: [...]}
  v
FastAPI  validates -> inserts a `queued` row -> publishes the job id to Redis
  |                                             |
  |  202 {id, status: "queued"}                 v
  v                                        Celery worker
browser polls GET /api/jobs/{id}                |
  |                                             | DeepSeek completion
  |                                             | writes `succeeded` + reply
  +-------------------------------------------->|
```

1. The browser posts the whole conversation to `POST /api/chat`.
2. The API keeps only `user` and `assistant` turns (a client-side `system`
   message is replaced by the server prompt in the worker), inserts a `queued`
   row in `jobs`, and publishes `rivet.tasks.generate_reply` with the job id.
3. The API returns `202` immediately with the job id. It never waits for the
   model.
4. The browser polls `GET /api/jobs/{id}` until the row says `succeeded`
   (`result` holds the reply) or `failed` (`code` and `error` explain it).

There is exactly one AI execution path: a chat request becomes a job, and only
the worker runs jobs. The API holds no DeepSeek key and imports no provider
client, so a direct call cannot creep back in.

## Layout

```
app/main.py             FastAPI app, CORS, JSON error handlers
app/config.py           env-backed settings (CORS, broker, database URL)
app/celery_client.py    dispatches tasks by name; imports no worker code
app/errors.py           error codes, status mapping, user-safe messages
app/schemas.py          ChatRequest / ChatMessage / JobResponse, allowed roles
app/jobs.py             jobs table + submit_job (the only write path)
app/routes/chat.py      POST /api/chat
app/routes/jobs.py      POST /api/jobs, GET /api/jobs/{id}
tests/                  route, validation and job tests
```

This app imports nothing from `apps/worker` and nothing from `apps/web`. It
reaches the worker through two contracts only: the Celery task name
`rivet.tasks.generate_reply` (`app/celery_client.py`) and the `jobs` table.
The task name and the table's DDL are kept in step by hand, because the two
services share that database. Each app is still its own deployment.

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

No `DEEPSEEK_API_KEY` here. The model credential belongs to the worker only.

## Run

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000 --env-file .env
```

Redis must be running for publishing to work; the worker must be running for a
job to finish. See `apps/worker/README.md` for its start command.

OpenAPI docs: http://localhost:8000/docs

The Next.js app expects this at `http://localhost:8000` by default; change it
with `NEXT_PUBLIC_API_BASE_URL` in `apps/web/.env.local`. If you move the web
app or the API to another origin, add that origin to `CORS_ALLOWED_ORIGINS`
(comma separated).

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
{ "id": "8f1c...", "status": "queued", "result": null, "code": null, "error": null }
```

`GET /api/jobs/{id}` returns the same shape. `status` is `queued`, `running`,
`succeeded` (then `result` holds the reply) or `failed` (then `code` and
`error` explain it). An unknown id is `404` with code `not_found`.

Failures return `{"code", "error"}` with a curated message:

| code             | status | meaning                          |
| ---------------- | ------ | -------------------------------- |
| `bad_request`    | 400    | unreadable or empty payload      |
| `not_found`      | 404    | no job with that id              |
| `enqueue_failed` | 503    | broker unreachable, job not sent |

A job that fails inside the worker reports `rate_limit`, `timeout`, `network`,
`unavailable`, `server_error` or `missing_config` on `GET /api/jobs/{id}`; the
API maps those to the same friendly text. Stack traces and upstream response
bodies stay in the server log only.

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

**Trade-off.** More moving parts: two images, a broker, and a database both
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

### Redis carries the job messages

**Decision.** Celery publishes and consumes through Redis (`CELERY_BROKER_URL`).

**Why.** Redis is already the project's broker, it has no operational overhead
locally, and Celery's protocol is built around it. The message stays small: one
job id.

**Alternatives considered.** A database-backed queue table; Amazon SQS;
in-process queues.

**Why not.** A queue table needs polling and locking and turns the database into
a broker. SQS is the target for the AWS deployment but is not available in the
local setup and would add infrastructure now. In-process queues break the
process boundary.

**Trade-off.** Redis delivery is at-least-once, so a job can be delivered twice.
The worker handles that with a state guard (see its README).

**Reconsider if.** The services move to separate hosts on AWS, where SQS removes
the need to operate Redis and gives a dead-letter queue for free. That is
planned, not implemented.

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
deploy time; a second database just for jobs; Celery's result backend as the
source of truth.

**Why not.** SQLite is a file on one host: separate services cannot share it,
and its single-writer locking hides the concurrency problems PostgreSQL will
expose. A second database doubles the operational surface and splits job state
from application state. Celery's result backend would move the source of truth
out of the `jobs` table and make status and error mapping harder.

**Trade-off.** Local development needs a running PostgreSQL server; the database
must exist, though its tables do not. Every request now depends on the database
being reachable.

**Reconsider if.** Never back to SQLite. Revisit PostgreSQL itself only if the
deployment target moves away from RDS, or job volume outgrows a single primary
and a `jobs` table stops being the right shape.

### Pooled connections and table creation

**Decision.** Each process keeps one `psycopg` connection pool (1 to 8
connections). Every store call checks out a connection, runs its own transaction
and returns it. The `jobs` table is created by `CREATE TABLE IF NOT EXISTS` on
the first call in each process (`ensure_schema` in `app/jobs.py`), and the same
DDL sits in `apps/worker/jobs.py`.

**Why.** The API serves requests from FastAPI's thread pool and the worker runs
prefork children, so a module-level shared connection would be a data race. A
pool gives each call its own connection while amortising the handshake. Creating
the table from code keeps setup to "the database exists": there is no migration
command to run before the first request.

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
store creates `jobs` if it is missing, `jobs` is truncated before each test, and
the Celery publish step is stubbed, so the tests never contact Redis or DeepSeek.
`RIVET_TEST_DATABASE_URL` defaults to
`postgresql://rivet:rivet@localhost:5432/rivet_test`, which must exist and must
not be the development database. Never point it at `rivet`: the suite truncates
whatever it points at.

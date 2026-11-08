# Rivet AI worker

The Celery worker owns all AI processing in Rivet AI. Every chat completion runs
here: the system prompt, the DeepSeek call, the retries and writing the result
back to the job row. The FastAPI app in `apps/api` only validates, records a job
and publishes it.

This is a separate process in a separate folder, with its own dependencies and
its own model credentials.

## Layout

```
celery_app.py       Celery instance, broker and worker settings, .env loading
settings.py         env-backed settings (key, model, upstream URL, broker, database URL)
chat.py             system prompt, request payload, completion + error mapping
jobs.py             jobs table and the status transitions the worker performs
tasks.py            generate_reply: claims a job, runs it, records the outcome
tests/test_chat.py  completion + error-mapping tests
tests/test_jobs.py  claim/requeue/ignore-finished transitions
tests/test_tasks.py task-level success, retry, duplicate and crash tests
```

The worker imports nothing from `apps/api` and nothing from the web app. It
reaches the API through two contracts: the Celery task name
`rivet.tasks.generate_reply` and the `jobs` table. Both are configured, not
imported, so this folder can be its own image and its own deployment.

The task name therefore exists in both services
(`apps/api/app/celery_client.py` and `tasks.py`). Keep the pair in step by hand;
the comments in both files point at the counterpart. Duplication is accepted on
purpose so neither service depends on the other's package. The `jobs` DDL is
duplicated as well (`jobs.py` here and `apps/api/app/jobs.py`), and the two
copies must be edited together.

## Prerequisites

Redis is the broker:

```bash
redis-server --port 6379
```

`CELERY_BROKER_URL` must match the API's value.

PostgreSQL is the database, at `DATABASE_URL`, which must match the API's value.
It runs locally as a normal server; see `apps/api/README.md` for the role and
database creation commands. There is no migration step: the job store creates
`jobs` with `CREATE TABLE IF NOT EXISTS` the first time it is used, so the
database only has to exist.

## Setup

```bash
cd apps/worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add DEEPSEEK_API_KEY
```

This is the only service that holds the model key. `DATABASE_URL` defaults to the
local server (`postgresql://rivet:rivet@localhost:5432/rivet`); for RDS, set it
to the RDS endpoint with `sslmode=require`. It must equal the API's value.

## Run

From `apps/worker`:

```bash
source .venv/bin/activate
celery -A celery_app:celery worker --loglevel=info
```

`.` does not need to be added to `PYTHONPATH`: Celery puts the working directory
on the path, which is how `celery_app` and `tasks` resolve.

Start the API alongside it (see `apps/api/README.md`), then submit a chat and
poll the job.

Run the tests with `pip install -r requirements-dev.txt` then `pytest`.

## Job lifecycle (implemented)

1. `POST /api/chat` or `POST /api/jobs` writes a `queued` row and publishes
   `rivet.tasks.generate_reply` with the job id.
2. The worker claims the row: `status = running`, `attempts + 1`. Claiming is a
   conditional update (`WHERE status IN ('queued','running')`), so a redelivered
   message for a finished job returns no row and the task exits without calling
   the model.
3. `chat.complete_chat` builds the payload (system prompt plus the stored
   conversation) and calls DeepSeek without streaming.
4. Success writes `succeeded` plus the reply. A permanent failure writes `failed`
   plus an error code the API already knows: `rate_limit`, `timeout`, `network`,
   `unavailable`, `server_error`, `missing_config`.

Job state is in PostgreSQL (`DATABASE_URL`, the same value the API uses) because
both processes must read and write it. Celery keeps no result backend
(`task_ignore_result=True`); the table is the source of truth. Each call checks a
`psycopg` connection out of a small pool, so concurrent task threads never share
a handle, and the claim in step 2 is a single conditional `UPDATE ... RETURNING`
whose row lock keeps `attempts` consistent across workers.

## Failure handling

`task_acks_late=True` with `task_reject_on_worker_lost=True` means a message is
acknowledged after the task finishes, not when it is received. If a worker dies
mid-call, the broker redelivers the job. Prefetch is 1, so one worker holds one
unacknowledged job at a time.

| situation                            | what happens                                             |
| ------------------------------------ | -------------------------------------------------------- |
| timeout, network, 402/429, upstream 5xx | retryable: row goes back to `queued`, Celery retries with 5s/10s/20s backoff, max 3 |
| retries exhausted                    | row becomes `failed` with that code                      |
| 4xx such as a bad key                | not retryable: row becomes `failed` immediately          |
| unexpected exception                 | logged with traceback, row becomes `failed` / `server_error` |
| duplicate delivery, job still queued or running | reclaimed and run; attempts increments         |
| duplicate delivery, job already finished | ignored: the conditional claim finds no row         |
| worker crashes after writing `succeeded` | redelivery is ignored, the stored reply is kept       |
| worker crashes mid-call              | redelivery reclaims the running row and tries again    |

The API never reports `running` while a job is waiting for a retry, because the
row is put back to `queued` before the retry is scheduled.

Known limits: a task that crashes the process hard (`SIGKILL`, OOM) is only
recovered when the broker redelivers, and a job that succeeded but whose worker
died before the ack can be re-run if the crash happened between the claim and
the write. Both paths are idempotent at the row level because the claim is
conditional.

## Decisions behind this service

### The worker owns every DeepSeek call

**Decision.** Only this service holds `DEEPSEEK_API_KEY` and only this service
imports an HTTP client for the provider. The API has no provider code at all.

**Why.** One owner means one place to change the model, prompt, timeout and
retry policy, and one place where a bug or a leaked key can be reasoned about.
It also makes the "no two competing AI paths" rule structural instead of a
convention: the API cannot call the model because the code is not there.

**Alternatives considered.** Keeping a shared client used by both services;
leaving the old streaming endpoint in the API for "simple" chats.

**Why not.** A shared Python package would couple the two deployments, and the
project deliberately builds each app as its own image. A second streaming path
would mean two behaviours to test and two places to fix a provider change, which
is exactly the split this change removes.

**Trade-off.** The prompt and payload builder exist twice (the old API copy was
deleted, so there is only the worker's copy now), and the worker must be running
for any chat to work.

**Reconsider if.** A second provider or a second consumer needs the same prompt
logic; then a generated/shared contract is worth the coupling. Not now.

### The worker creates the jobs table if it is missing

**Decision.** The worker connects to PostgreSQL with `DATABASE_URL` and runs
`CREATE TABLE IF NOT EXISTS jobs` once per process (`ensure_schema` in
`jobs.py`). The same DDL sits in `apps/api/app/jobs.py`; both copies are edited
together.

**Why.** Whichever service starts first creates the table and the other finds it
already there. That keeps each app startable on its own, with no migration step
and no ordering between deployments, which is what the separate AWS deployments
need.

**Alternatives considered.** A migration tool (Alembic) run by the API image or
a deploy step; having the worker assume the API created the table first.

**Why not.** A migration tool earns its dependency when the schema changes
often; with one stable table it adds a deploy step and a second copy of the DDL
that can drift from the queries. Making the worker wait for the API makes it
unstartable on its own.

**Trade-off.** A schema change must be made in both files and rolled out by
deploying new code, and `IF NOT EXISTS` never alters a table that already exists.

**Reconsider if.** The schema starts changing, or these services need different
tables. Then move the DDL into Alembic, run as one deploy step.

### Asynchronous submission and polling instead of streaming

**Decision.** The API returns a job id and the browser polls `GET /api/jobs/{id}`.
The reply arrives complete.

**Why.** A queued job is the only way to keep the API independent of the
provider. Polling needs no new infrastructure: the row already holds the status
and the result, and the browser already knows the job id.

**Alternatives considered.** Server-Sent Events relaying chunks from the worker;
WebSockets; Redis Streams; long polling with a held request.

**Why not.** All of them need a second channel plus a relay in the API, and the
worker would have to publish partial output. That is real infrastructure for a
UX improvement, and it was explicitly out of scope for this change.

**Trade-off.** Time to first token is lost. The user sees a spinner until the
whole reply is ready, and each poll is a cheap database read.

**Reconsider if.** Perceived latency becomes a product problem. The documented
next step is worker-published chunks plus an SSE relay; see below. It is not
implemented.

### Future: worker-based streaming (planned, not implemented)

A future version could have the worker publish token chunks to a channel
(Redis Streams is one option) while the API relays them to the browser over SSE,
with the final message still written to the `jobs` row so polling and
reconnection keep working. That would keep the provider call in the worker and
leave the API as a relay only.

It is deliberately not built now: it adds a second transport, ordering and
backpressure concerns, and partial-output failure handling, none of which the
current polling flow needs. Move to it when streaming is a requirement rather
than a nice-to-have.

## Tests

```bash
source .venv/bin/activate
pytest
```

`tests/test_chat.py` uses `httpx.MockTransport` and never calls DeepSeek.
`tests/test_jobs.py` and `tests/test_tasks.py` run against the PostgreSQL test
database (`rivet_test` by default, `RIVET_TEST_DATABASE_URL` overrides it):
the job store creates `jobs` once and it is truncated before each test. That
covers
success, retries, duplicate delivery and crashes without a broker. Never point
the variable at the development database; the suite truncates it.

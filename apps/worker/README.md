# Rivet AI worker

The worker owns all AI processing in Rivet AI. Every chat completion runs here:
the system prompt, the DeepSeek call, the failure handling and writing the result
back to the job row. The FastAPI app in `apps/api` only validates, records a job
and publishes its id to Amazon SQS.

This is a separate process in a separate folder, with its own dependencies and
its own model credentials. It polls SQS with Boto3; there is no Celery and no
Redis anywhere in this service.

## Layout

``` 
worker.py           the process: long-poll SQS, handle messages, shut down cleanly
processor.py        the job lifecycle: claim, run, persist, decide what to do next
sqs_queue.py        every SQS call: receive, delete, send, visibility, parse
storage.py          the one S3 read the worker makes: download an attachment
jobs.py             jobs table and the status transitions the worker performs
chat.py             system prompt, request payload, completion + error mapping
settings.py         env-backed settings (key, model, database, queue, storage)
tests/              job store, completion, queue, processor, loop and S3 tests
```

`sqs_queue.py` is not called `queue.py` on purpose: this folder is on `sys.path`
when the worker runs, so a local `queue.py` would shadow the standard library
module that boto3 and psycopg import.

The worker imports nothing from `apps/api` and nothing from the web app. It
reaches the API through two contracts: the SQS message body `{"job_id": "<id>"}`
and the `jobs` table. Both are configured, not imported, so this folder can be
its own image and its own deployment. The message body therefore exists in both
services (`apps/api/app/queue.py` and `sqs_queue.py`); keep the pair in step by
hand, the comments in both files point at the counterpart. Duplication is
accepted on purpose so neither service depends on the other's package. The
`jobs` DDL is duplicated as well (`jobs.py` here and `apps/api/app/jobs.py`), and
the two copies must be edited together.

## Prerequisites

PostgreSQL is the database, at `DATABASE_URL`, which must match the API's value.
It runs locally as a normal server; see `apps/api/README.md` for the role and
database creation commands. There is no migration step: the job store creates
`jobs` with `CREATE TABLE IF NOT EXISTS` the first time it is used, so the
database only has to exist.

SQS is the queue. There is no local default, because AWS is not provisioned yet,
so either point the worker at LocalStack or at a real queue:

```bash
docker run --rm -d -p 4566:4566 --name rivet-localstack localstack/localstack
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test
aws --endpoint-url http://localhost:4566 --region us-east-1 \
  sqs create-queue --queue-name rivet-jobs-dlq
aws --endpoint-url http://localhost:4566 --region us-east-1 \
  sqs create-queue --queue-name rivet-jobs
aws --endpoint-url http://localhost:4566 --region us-east-1 \
  sqs set-queue-attributes \
  --queue-url http://localhost:4566/000000000000/rivet-jobs \
  --attributes '{"RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:rivet-jobs-dlq\",\"maxReceiveCount\":\"3\"}"}'
```

The redrive policy is queue configuration, not application configuration: the
worker only needs the main queue URL.

Then in `.env`:

```text
SQS_QUEUE_URL=http://localhost:4566/000000000000/rivet-jobs
SQS_ENDPOINT_URL=http://localhost:4566
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_REGION=us-east-1
```

Those dummy credentials are what LocalStack expects. On AWS, delete all of them:
the task's IAM role supplies the credentials and `SQS_ENDPOINT_URL` stays empty.
Nothing needs an AWS credential to import a module or run the test suite.

S3 is only needed for attachments. With no chat that carries a file,
`S3_BUCKET_NAME` can stay empty; the worker only complains when it has to
download one.

## Setup

```bash
cd apps/worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add DEEPSEEK_API_KEY and the queue settings
```

This is the only service that holds the model key. `DATABASE_URL` defaults to the
local server (`postgresql://rivet:rivet@localhost:5432/rivet`); for RDS, set it
to the RDS endpoint with `sslmode=require`. It must equal the API's value.

## Run

From `apps/worker`:

```bash
source .venv/bin/activate
python worker.py
```

`.env` is loaded by `worker.py` itself, so no exports are needed for local work.
The loop logs each receive, claim, failure and finish. `SIGTERM` or `Ctrl-C` sets
a stop flag: the job in hand finishes, its message is acknowledged only if the
row was written, and the process exits. A signal that arrives during a long poll
is acted on when that poll returns, so allow up to `SQS_WAIT_TIME_SECONDS` (20s)
for a graceful stop.

One poll uses the settings below, all read from the environment on each startup:

| variable                | default    | meaning                                        |
| ----------------------- | ---------- | ---------------------------------------------- |
| `SQS_QUEUE_URL`         | none       | main queue; the worker refuses to start without it |
| `AWS_REGION`            | us-east-1  | region for the SQS and S3 clients              |
| `SQS_ENDPOINT_URL`      | none       | LocalStack only; empty on AWS                  |
| `SQS_WAIT_TIME_SECONDS` | 20         | long-poll wait per receive                     |
| `SQS_VISIBILITY_TIMEOUT`| 120        | how long a received job stays invisible        |
| `SQS_MAX_MESSAGES`      | 1          | messages per receive                           |
| `S3_BUCKET_NAME`        | none       | attachments; no bucket is created by this app  |
| `S3_REGION`             | `AWS_REGION` | region for the S3 client                     |
| `S3_ENDPOINT_URL`       | none       | LocalStack only                                |

`SQS_VISIBILITY_TIMEOUT` must be longer than a DeepSeek request (40s), otherwise
SQS hands the same job to a second worker while the first is still waiting. Keep
`SQS_MAX_MESSAGES` at 1: the loop is single-threaded, so a second message would
sit received and invisible while the first one runs.

Start the API alongside it (see `apps/api/README.md`), then submit a chat and
poll the job.

Run the tests with `pip install -r requirements-dev.txt` then `pytest`.

## Running more than one worker

One worker is enough today; more of them are the same process started again.
Nothing is per-instance:

- `DATABASE_URL` and `SQS_QUEUE_URL` are identical on every instance and come
  from the environment.
- Every instance long-polls the same queue. SQS hands a message to one receiver
  and keeps it invisible for `SQS_VISIBILITY_TIMEOUT`, so work spreads across
  instances without a dispatcher.
- The claim is one conditional `UPDATE ... RETURNING` on the shared `jobs` row,
  so the instance that loses the race gets no row back and stops. Two instances
  never work on the same job at the same time.
- Each instance opens its own pool: `DB_POOL_MIN_SIZE` connections held open,
  `DB_POOL_MAX_SIZE` at peak. The loop is single-threaded, so it checks out one
  connection at a time; ten idle instances cost ten connections on RDS. Lower
  `DB_POOL_MIN_SIZE` (0 is allowed) if `max_connections` is tight.

There is no coordinator, no leader election and no lock table: the shared row
and the queue already provide both the split of work and the duplicate
protection. Adding instances changes nothing in the code or the schema.

## Job lifecycle (implemented)

1. `POST /api/chat` or `POST /api/jobs` writes a `queued` row and publishes
   `{"job_id": "<id>"}` to the SQS queue.
2. The worker receives the message and claims the row: `status = running`,
   `attempts + 1`. Claiming is one conditional `UPDATE ... RETURNING`, so of two
   workers handed the same message only one gets a row back; the other sees a
   finished or owned job and stops without calling the model. A row still
   `running` is reclaimed only after `SQS_VISIBILITY_TIMEOUT` seconds, the
   earliest moment SQS can hand that message to another worker: that recovers a
   worker killed mid-job, and refuses a duplicate delivery that arrives while
   the job is genuinely in flight.
3. `chat.complete_chat` builds the payload (system prompt plus the stored
   conversation) and calls DeepSeek without streaming.
4. Success writes `succeeded` plus the reply. A permanent failure writes `failed`
   plus a code the API already knows: `rate_limit`, `timeout`, `network`,
   `unavailable`, `server_error`, `missing_config`.
5. The message is deleted **after** that write commits. Until then it is only
   invisible.

Job state is in PostgreSQL (`DATABASE_URL`, the same value the API uses) because
both processes must read and write it. The table is the source of truth; SQS
carries an id and nothing else. Each call checks a `psycopg` connection out of a
small pool, so the API's threads and the worker's loop never share a handle, and
the claim in step 2 is a single conditional `UPDATE ... RETURNING` whose row lock
keeps `attempts` consistent across workers.

## Message lifecycle and the DLQ

SQS delivers at least once, and it does not know what PostgreSQL says. The two
are reconciled like this:

| situation                                  | what happens                                         |
| ------------------------------------------ | ---------------------------------------------------- |
| success                                    | row written, then the message is deleted             |
| retryable error (timeout, network, 429, upstream 5xx) | row back to `queued`, message **left** on the queue; SQS redelivers it after the visibility timeout |
| permanent error (bad key, malformed upstream reply) | row `failed` with that code, message deleted |
| unexpected exception                       | logged with traceback, row `failed` / `server_error`, message deleted |
| database write fails                       | message left on the queue; redelivery reruns the job |
| claim refused (job already finished)       | message deleted, reply kept                          |
| message with no job id                     | logged as an error and deleted; there is no row to retry |
| job id with no row                         | logged as an error and deleted; there is nothing to reconcile |

There is no application-level retry counter and no backoff timer: the visibility
timeout is the backoff, and the queue's redrive policy is the retry limit. After
`maxReceiveCount` receives the main queue moves the message to the DLQ, which is
where an operator looks for poison messages.

SQS never updates the `jobs` row, and this service deliberately does not read
the DLQ: there is no reconciliation command, no scheduler and no automatic
replay. A message that exhausted its redeliveries therefore leaves its row
`queued` or `running` forever. That is a known, accepted gap between the two
records, not something the worker tries to repair. The DLQ is for a human:
inspect the message in the AWS Console (it is retained there), find the cause,
recover by hand if the job still matters, then purge it.

What the user sees: the browser polls the row, keeps getting `queued` or
`running`, and after `RESPONSE_TIMEOUT_MS` (two minutes, in
`apps/web/src/app/page.tsx`) shows a timeout message with a Retry button. That
button asks the API for a new job built from the same conversation
(`POST /api/jobs/{id}/retry`), which is independent of the DLQ and of the stuck
row, so a dead-lettered message never has to be replayed for the user to get an
answer.

Known limits: a process killed hard (`SIGKILL`, OOM) leaves its row `running`
until the message is redelivered and the visibility timeout has passed, which is
why the claim accepts a `running` row whose lease has expired. A job that succeeded but whose message was not deleted before the
crash is not re-run: the claim refuses it and the message is simply deleted on
the next delivery.

## S3 attachment storage

`storage.py` owns the only S3 call the worker makes: `read_object`, a bounded
download of an attachment an API-confirmed upload already wrote. `S3_BUCKET_NAME`
names the bucket; no bucket is created here, no object is ever written or
deleted here, and no credentials are read from code.

`documents.py` turns PDF, DOCX and legacy DOC into plain text; a PNG is passed
to the model as a base64 data URL only when `DEEPSEEK_MODEL` is a vision-capable
model. `DEEPSEEK_MODEL` defaults to `deepseek-flash`, which reads images. A
text-only model such as `deepseek-chat` or `deepseek-v4-pro` fails the job with
`image_unsupported` instead of pretending to see the image. Extracted text is
cached on the attachment row, so a redelivery does not download and parse the
file again.

There is no OCR. A scanned PDF has no text layer, so extraction raises
`DocumentError` and the job fails with `attachment_unreadable`. Legacy `.doc`
files are read through their Word 97 piece table; if that fails, the user is
told to save the file as `.docx` or PDF. Nothing is invented for either case.

## Decisions behind this service

### The worker owns every DeepSeek call

**Decision.** Only this service holds `DEEPSEEK_API_KEY` and only this service
imports an HTTP client for the provider. The API has no provider code at all.

**Why.** One owner means one place to change the model, prompt, timeout and
failure policy, and one place where a bug or a leaked key can be reasoned about.
It also makes the "no two competing AI paths" rule structural instead of a
convention: the API cannot call the model because the code is not there.

**Alternatives considered.** Keeping a shared client used by both services;
leaving the old streaming endpoint in the API for "simple" chats.

**Why not.** A shared Python package would couple the two deployments, and the
project deliberately builds each app as its own image. A second streaming path
would mean two behaviours to test and two places to fix a provider change, which
is exactly the split this change removes.

**Trade-off.** The worker must be running for any chat to work, and the payload
builder lives only here, so a change to it is a worker release.

**Reconsider if.** A second provider or a second consumer needs the same prompt
logic; then a generated/shared contract is worth the coupling. Not now.

### SQS redelivery instead of an in-process retry loop

**Decision.** A retryable failure puts the row back to `queued` and leaves the
message alone. SQS redelivers it when the visibility timeout expires, and the
redrive policy moves it to the DLQ after `maxReceiveCount`.

**Why.** The queue already tracks how many times a message was received and
already persists it. Keeping that state here would mean a second counter, a
timer that dies with the process, and a way for the two to disagree. Leaving the
message also means a crash is handled by the same path as a timeout: nothing is
lost, and the conditional claim makes the rerun safe.

**Alternatives considered.** Retrying inside `process_job` with a sleep and a
retry counter; a separate retry queue with a delay; re-publishing the job id.

**Why not.** An in-process backoff holds the message invisible and dies with the
process. A retry queue is another resource to provision for behaviour SQS
already has. Re-publishing creates a second message for one job, which is the
duplicate the claim exists to absorb.

**Trade-off.** The delay between attempts is the visibility timeout, not a fine
grained backoff, and the receive limit lives in the queue's redrive policy
(infrastructure), not in this code.

**Reconsider if.** A job needs per-error delays, or ordering guarantees that a
standard queue cannot give.

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
WebSockets; a Redis stream; long polling with a held request.

**Why not.** All of them need a second channel plus a relay in the API, and the
worker would have to publish partial output. That is real infrastructure for a
UX improvement, and it was explicitly out of scope for this change.

**Trade-off.** Time to first token is lost. The user sees a spinner until the
whole reply is ready, and each poll is a cheap database read.

**Reconsider if.** Perceived latency becomes a product problem. The documented
next step is worker-published chunks plus an SSE relay; see below. It is not
implemented.

### Future: worker-based streaming (planned, not implemented)

A future version could have the worker publish token chunks to a channel while
the API relays them to the browser over SSE, with the final message still written
to the `jobs` row so polling and reconnection keep working. That would keep the
provider call in the worker and leave the API as a relay only.

It is deliberately not built now: it adds a second transport, ordering and
backpressure concerns, and partial-output failure handling, none of which the
current polling flow needs. Move to it when streaming is a requirement rather
than a nice-to-have.

## Terraform will need to provision (not written yet)

Nothing below exists. This is the list the application is written against, so
the infrastructure work has a checklist:

- **SQS main queue** (`rivet-jobs`) with a visibility timeout that matches
  `SQS_VISIBILITY_TIMEOUT` and a **redrive policy** pointing at the DLQ with a
  `maxReceiveCount` (that limit is the retry budget; it is not in this code).
- **SQS DLQ** (`rivet-jobs-dlq`) with a longer retention than the main queue.
- **RDS PostgreSQL 16**, reachable from both services, with security-group
  ingress from the API and worker tasks only. The connection string goes into
  `DATABASE_URL` with `sslmode=require`; nothing is hardcoded.
- **S3 bucket** for attachments: private, encryption at rest, no public access,
  and a lifecycle rule that expires `uploads/pending/`.
- **IAM role for the API task**: `sqs:SendMessage` on the main queue, the S3
  permissions listed in `apps/api/README.md`, and read access to the database
  secret.
- **IAM role for the worker task**: `sqs:ReceiveMessage` and `sqs:DeleteMessage`
  on the main queue, plus `s3:GetObject` on `uploads/attached/*`: downloading an
  attachment is the only S3 call this service makes. The worker reads no queue
  attributes and never touches the DLQ; administrators read the DLQ through the
  console or their own role.
- **CloudWatch alarms** on both queues: `ApproximateNumberOfMessagesVisible`,
  `ApproximateNumberOfMessagesNotVisible` and `ApproximateAgeOfOldestMessage`
  for the main queue, and any message in the DLQ. These are the queue's own
  metrics; nothing in the application publishes or aggregates them.
- **ECR repositories, ECS services/tasks and CloudWatch log groups** for the API
  and the worker, deployed as two images.
- **The DeepSeek key** in a secret store injected into the worker task only.

## Tests

```bash
source .venv/bin/activate
pytest
```

`tests/test_chat.py` uses `httpx.MockTransport` and never calls DeepSeek.
`tests/test_jobs.py`, `tests/test_processor.py` and `tests/test_worker.py` run
against the PostgreSQL test database (`rivet_test` by default,
`RIVET_TEST_DATABASE_URL` overrides it): the job store creates `jobs` once and it
is truncated before each test.

SQS and S3 are never contacted. `tests/fakes.py` holds a fake SQS client (with an
inbox, recorded calls and hooks that fire inside a call) and an in-memory S3
client, and the tests pass them in explicitly. That covers success, duplicate
delivery, already-finished jobs, retryable and permanent failures, unexpected
exceptions, a failing database write, a worker dying mid-job, the delete-after-
commit order, malformed messages, the receive-error backoff and the S3 calls. Never point `RIVET_TEST_DATABASE_URL` at the development
database; the suite truncates it.

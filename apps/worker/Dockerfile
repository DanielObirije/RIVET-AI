FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

RUN useradd --create-home --uid 10001 appuser
USER appuser

# SIGTERM finishes the job in flight; give it longer than the 40s upstream call
STOPSIGNAL SIGTERM

# The poll loop touches WORKER_HEARTBEAT_PATH; a stale file means it is hung.
# A 20s long poll plus one 40s upstream call can keep the loop quiet for about a
# minute, so 180s leaves room while still catching a dead loop.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, time, sys; p = os.environ.get('WORKER_HEARTBEAT_PATH', '/tmp/worker-heartbeat'); sys.exit(0 if os.path.exists(p) and time.time() - os.path.getmtime(p) < 180 else 1)"

CMD ["python", "worker.py"]

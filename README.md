# PulseWatch

Local-development API monitoring MVP. FastAPI stores monitors and check history in PostgreSQL; Celery Beat dispatches due checks through Redis to workers; Next.js displays results.

## Run
Install Docker with Compose, then run `docker compose up --build`. Open http://localhost:3000 or API docs at http://localhost:8000/docs. Add a public HTTP(S) endpoint. Checks are dispatched every 10 seconds, with a minimum per-monitor interval of 30 seconds. Uptime is the fraction of completed checks in the past 24 hours that returned HTTP 2xx after retries; latency is the final attempt's time to response headers. No response bodies are stored. Stop with `docker compose down`.

## Tests
From backend: `pip install -r requirements.txt` and `pytest -q`. CI also builds the frontend.

## Limitations / next steps
Local trusted-user demo only: no authentication, alert delivery, retention policy, or production egress isolation. DNS prevalidation is not sufficient against DNS rebinding; enforce network-level egress restrictions before exposing to untrusted users. Scheduler enqueue and database update are not atomic; use an outbox and idempotent check IDs for durable delivery. Concurrent deletion and checks may race. Schema is initialized with create_all; Alembic migrations are not yet implemented. No lockfiles yet. Do not deploy publicly as-is.

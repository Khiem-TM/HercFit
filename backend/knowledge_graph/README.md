# HercFit Knowledge Graph

Neo4j is a rebuildable, optional projection. PostgreSQL owns business records,
approvals and LangGraph checkpoints. All numeric answers and write validation
still use the authenticated backend API.

## Start with Docker

From the repository root:

```sh
./dev_up.sh up --kg -d
docker compose -f backend/docker-compose.yml --profile kg stop kg-worker
docker compose -f backend/docker-compose.yml --profile kg run --rm kg-worker python -m knowledge_graph.worker backfill
docker compose -f backend/docker-compose.yml --profile kg up -d kg-worker
```

The worker initializes constraints and capabilities, but retrieval stays in
`warming` until an explicit successful backfill. Neo4j Browser is available at
http://localhost:7474. The development login is `neo4j` with the password from
`NEO4J_PASSWORD` (default `hercfit-graph-dev`). Change the password for deployment.

Set `KG_MODE` in the Compose environment and recreate the agent service:

```sh
KG_MODE=shadow docker compose -f backend/docker-compose.yml --profile kg up -d agentic
```

Modes: `off` bypasses retrieval; `shadow` measures it without prompt influence;
`advisory` supplies bounded evidence; `optimized` additionally enables the strict
progress read template. Default is `off`. Roll back by recreating the agent with
`KG_MODE=off`; business storage and confirmations remain available.

## Local or separate databases

Install `backend/agentic/requirements.txt` in the project environment. From
`backend/`, configure `AGENT_DATABASE_URL`, `KG_BACKEND_DATABASE_URL`,
`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and `NEO4J_DATABASE`.
Omitting `KG_BACKEND_DATABASE_URL` uses the agent DSN for a shared database.
For separate databases, migrate both sources before starting the worker:

```sh
python -m alembic upgrade head
python -m agentic.migrate
python -m knowledge_graph.worker backfill
python -m knowledge_graph.worker run
```

The standalone `agentic/docker-compose.yml` also supports `--profile kg`.
Its backend DSN must reach the backend PostgreSQL from inside Docker; use
`host.docker.internal` when that database is exposed on the host.
`./dev_up.sh --local --kg` starts Neo4j and a local worker; the agent can be
started separately with `python -m uvicorn agentic.main:app --port 8081`.

## Data and recovery

Backend PostgreSQL triggers capture User lifecycle, Goal, BodyMetric, Food,
Meal and MealItem changes, including SQL imports. Events commit atomically with
source writes. Meal child changes advance a separate aggregate revision;
`payload.version_id` remains the ORM version. Food portions and nutrients are
historical snapshots. Unstructured profile fields and credentials are excluded.

Agent executions are recovered from committed checkpoints and journaled with
stable IDs. Source session generations immediately filter deleted memory during
retrieval; durable tombstones reject late events. Clearing chat history preserves
saved business records. Reusing a session ID advances its generation.

Events are acknowledged only after graph commit. Duplicate or older versions
are harmless. Errors retain their event for retry with backoff; exception bodies
are not recorded. Inspect `kg_outbox` attempts, `last_error`, pending count and
oldest pending timestamp in each source database.

Stop the worker before administrative commands to avoid its coordinator lock:

```sh
python -m knowledge_graph.worker retry
python -m knowledge_graph.worker reconcile
python -m knowledge_graph.worker rebuild --confirm-rebuild
```

Rebuild deletes derived graph entities, gates retrieval as `warming`, requeues
source snapshots and tombstones, then resumes retrieval only after the backlog
is empty. PostgreSQL remains intact. If it fails, fix the reported error class,
retry and rerun backfill. This MVP rebuild uses temporary graph unavailability;
chat falls back to the existing workflow.

Graph retention defaults to 90 days for meals/measurements and 30 days for
executions. Source journals/outbox are retained for recovery; this implementation
does not automatically purge their SQL audit history. Goals must be active and
CUSTOM foods remain owner-scoped. No embeddings, free-form memory extraction,
or automatic promotion of learned execution templates is enabled.

## Validation and rollout

```sh
PYTHONPATH=backend .venv/bin/python -m pytest backend/agentic/tests/unit -q
PYTHONPATH=backend .venv/bin/python -m agentic.tests.evaluation.benchmark_kg
```

The benchmark uses synthetic backend and graph fixtures by default. It proves
call counts and functional routing, not real Neo4j or provider latency. Its
explicit `--real-model` option sends only synthetic requests to the configured
provider. See `--help` for report and workload options.

Integration tests require disposable services: set `KG_TEST_DATABASE_URL`,
`KG_TEST_NEO4J_URI`, and `KG_TEST_NEO4J_PASSWORD`, then run the `test_kg_*` files
under `agentic/tests/integration`. The graph suite deletes projection labels in
that test graph. Backend trigger tests use `SCHEMA_TEST_DATABASE_URL` and create
disposable schemas. Never point these tests at a production graph.

Promote modes only after regression tests pass and production-like measurements
meet the planned gates: routing >=95% without >1 percentage-point regression,
retrieval p95 <=100 ms (150 ms cutoff), projection lag p95 <=5 seconds, and eligible
read latency/tokens improving >=20%/15%. The strict progress template preserves
the initial routing and final response calls, reducing four model calls to two.
Ambiguity, compound requests, missing fields and graph outages use the baseline.

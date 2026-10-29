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
`advisory` supplies the knowledge card below to routing, tool calls and the final
answer; `optimized` additionally enables the strict progress read template.
That template only parses the request, so `FAST_READ_ENABLED=true` enables it
without the graph. Default is `off`. The agent warms every domain query at startup
because a cold read exceeds the 150 ms cap; a timed-out read finishes in the
background so its pooled connection survives. Roll back by recreating the agent with
`KG_MODE=off`; business storage and confirmations remain available.

## Knowledge layers

1. **Facts** — owner-scoped projections of business records (Goal, BodyMetric,
   Meal→MealItem→Food, Training→Exercise) and of `users.age` plus the
   `TrainingProfile`-validated subset of `personal_info['training']` (level, focus,
   days, minutes, equipment; never injuries, heart rates or free-form keys).
2. **Conversation** — one `Run` per finished turn with a deterministic intent
   (`knowledge_graph/intents.py`: domain × write/read/research, never message or
   model text), linked `-[:HAS_INTENT]->(:Intent)` and `-[:ABOUT]->` the records it
   touched. Turns are journaled in `agent_turn_records`, versioned like executions.
3. **User model** — `knowledge_graph/model.py` derives what a coach remembers:
   BMI, weight changes and trend, goal progress and required vs actual pace,
   7-day nutrition averages and favourite foods, weekly/28-day training, best e1RM
   progression and running totals. The worker stores it as `(:UserModel)` with
   `FREQUENTLY_EATS`/`PRACTICES` habit edges, refreshing an owner after each of its
   business events and, during maintenance, whenever the local day changes.
   Conversation statistics are never stored there: they are aggregated at read
   time behind the SQL session gate.

The agent reads a **knowledge card**: user-model sections chosen for the request's
domains (round-robin across domains), then the most relevant records, then recent
turns, as compact Vietnamese lines within 1500 bytes. Every number is derived from
projected facts by tested pure functions, so answers like "giảm bao nhiêu kg so
với tháng trước" or "tuần này tập mấy buổi" are present without a tool call.

`GET /api/v1/chat/knowledge-graph` returns the personal map for the UI: profile,
insight cards, intents, a disclosure tree (`Bạn → hubs → records → details`, with
`tree` and cross `link` edges) and a timeline. It reports `mode` so the client can
say when the assistant does not use the graph yet.

Optional `start` and `end` (inclusive local days, `YYYY-MM-DD`, Asia/Ho_Chi_Minh)
limit the drawn meals, trainings, measurements and turns to those days, at most 40
of each kind (newest first). Without them the map keeps its compact default (the 14
newest of each kind). A windowed answer adds `window`: the effective `start`/`end`
after clamping to the retained history, its bounds `min`/`max`, the per-kind `limit`,
`totals` in the window before the limit, and `density`, activity per local day and
hub over the whole retained history, which the client draws as a time scrubber.
`start` after `end` is rejected with 422.

Measure retrieval without models (context recall over the eval cases), and the
full agent when model keys are available:

```sh
python -m agentic.evaluation.kg_eval seed
python -m agentic.evaluation.kg_eval retrieval --out /tmp/kg_retrieval
python -m agentic.evaluation.kg_eval run --modes off,advisory --repeat 2
```

## Local or separate databases

Install `backend/agentic/requirements.txt` in the project environment. From
`backend/`, configure `AGENT_DATABASE_URL`, `KG_BACKEND_DATABASE_URL`,
`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and `NEO4J_DATABASE`.
Omitting `KG_BACKEND_DATABASE_URL` uses the agent DSN for a shared database.
For separate databases, migrate both sources before starting the worker:

```sh
python -m alembic upgrade head
python -m agentic.scripts.migrate
python -m knowledge_graph.worker backfill
python -m knowledge_graph.worker run
```

The standalone `agentic/docker-compose.yml` also supports `--profile kg`.
Its backend DSN must reach the backend PostgreSQL from inside Docker; use
`host.docker.internal` when that database is exposed on the host.
`./dev_up.sh --local --kg` starts Neo4j and a local worker; the agent can be
started separately with `python -m uvicorn agentic.core.app.main:app --port 8081`.

## Data and recovery

Backend PostgreSQL triggers capture User lifecycle, Goal, BodyMetric, Food,
Meal/MealItem and Training/TrainingItem changes (trainings project as
`User-[:TRAINED]->Training-[:PERFORMED]->Exercise`, exercises carry catalog identity only), including SQL imports. Events commit atomically with
source writes. Meal child changes advance a separate aggregate revision;
`payload.version_id` remains the ORM version. Food portions and nutrients are
historical snapshots. Free-form profile fields, contact data and credentials are excluded.

Agent executions and turns are recovered from committed checkpoints and journaled
with stable IDs. Source session generations immediately filter deleted memory during
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

Graph retention defaults to 90 days for meals, measurements and trainings and 30 days for
executions and turns. Source journals/outbox are retained for recovery; this implementation
does not automatically purge their SQL audit history. Goals must be active and
CUSTOM foods remain owner-scoped. No embeddings, free-form memory extraction,
or automatic promotion of learned execution templates is enabled.

## Rollout

Promote modes only after regression tests pass and production-like measurements
meet the planned gates: routing >=95% without >1 percentage-point regression,
retrieval p95 <=100 ms (150 ms cutoff), projection lag p95 <=5 seconds, and eligible
read latency/tokens improving >=20%/15%. The strict progress template preserves
the initial routing and final response calls, reducing four model calls to two.
Ambiguity, compound requests, missing fields and graph outages use the baseline.

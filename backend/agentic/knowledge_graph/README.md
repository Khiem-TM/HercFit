# HercFit Knowledge Graph

Neo4j is a rebuildable projection that is always part of the agent context.
PostgreSQL owns business records, approvals and LangGraph checkpoints. All writes
and their validation still go through the authenticated backend API.

## Start with Docker

From the repository root, `./dev_up.sh up -d` starts Neo4j and `kg-worker` with the
rest of the stack (`--db-only` and `--local` start Neo4j too; `--local` runs the
worker on the host). The first time, and after a rebuild, fill the graph once:

```sh
docker compose -f backend/docker-compose.yml stop kg-worker
docker compose -f backend/docker-compose.yml run --rm kg-worker python -m agentic.knowledge_graph.worker backfill
docker compose -f backend/docker-compose.yml up -d kg-worker
```

The worker initializes constraints and capabilities, but retrieval stays in
`warming` until an explicit successful backfill. Neo4j Browser is available at
http://localhost:7474. The development login is `neo4j` with the password from
`NEO4J_PASSWORD` (default `hercfit-graph-dev`). Change the password for deployment.

There is no runtime switch. Every turn reads the knowledge card below for the
domains its wording names (`domains_for`), then for the router's domain and personal
topic (`services.rag_pipeline.decision_domains`) when the wording missed them, so
routing, tool calls, context reads, research and the final answer all see it. Reads
are bounded (150 ms, fail-open): a slow or unreachable Neo4j only degrades a turn to
the backend tools, and business storage and confirmations remain available. The agent
warms every domain query at startup and keeps retrying in the background while Neo4j
is still starting, because a cold read exceeds the cap; a timed-out read finishes in
the background so its pooled connection survives. The strict read templates parse the
request themselves and are controlled by `FAST_READ_ENABLED`, independent of the graph.

Each turn record (`agent_turn_records.data.route.kg`) keeps what the graph gave that
turn: latest status and every attempt's status, total read time, domains, sections and
fact/episode/line counts. Labels and counts only, never facts.

## Knowledge layers

1. **Facts** — owner-scoped projections of business records (Goal, BodyMetric,
   Meal→MealItem→Food, Training→Exercise) and of `users.age`, `users.sex`, the
   declared activity level and the `TrainingProfile`-validated subset of
   `personal_info['training']` (level, focus, days, minutes, equipment; never injuries,
   declared heart rates or free-form keys). Device data synchronized from Google
   Health adds `DailyHealth` (day rollups), `SleepSession` and `DeviceWorkout`
   (`HAS_DAILY_HEALTH`, `SLEPT`, `WORKED_OUT`) plus device `BodyMetric` samples. These
   are published only while `health_connections.share_with_assistant` is true:
   otherwise `kg_publish_backend` emits measurement-free tombstones, and changing the
   consent republishes the user's device records. Spot vitals (`health_samples`),
   per-second heart rate and provider credentials are never published.
2. **Conversation** — one `Run` per finished turn with a deterministic intent
   (`agentic/knowledge_graph/intents.py`: domain × write/read/research, never message or
   model text), linked `-[:HAS_INTENT]->(:Intent)` and `-[:ABOUT]->` the records it
   touched. Turns are journaled in `agent_turn_records`, versioned like executions.
3. **User model** — `agentic/knowledge_graph/model.py` derives what a coach remembers:
   BMI (Asian cut-offs), weight and body-fat changes and trend, goal progress and
   required vs actual pace, 7-day nutrition averages and favourite foods,
   weekly/28-day training, best e1RM progression and running totals, and from device
   data (model version 2) activity (steps vs 28 days, WHO 150 minutes), sleep
   (duration vs recommendation, stages, regularity), recovery signals (resting HR and
   HRV against the 28-day baseline, never a diagnosis) and energy balance (logged
   intake vs device expenditure). Model version 3 guards the weight story: a weigh-in
   that disagrees with both neighbours is dropped as a spike, and after a jump larger
   than scale noise allows (2 kg + 0.25 kg/day) only the latest consistent run feeds
   changes, rate, goal progress and energy balance, while the card names the jump and
   asks to re-weigh. Trend and rate come from one estimate (30-day least squares, else
   the longest change). The observed activity level combines steps on worn days with
   exercise minutes per week from logged sessions and device workouts (each day counts
   the larger), which can raise but never lower it. Declared-versus-measured
   disagreements are kept as `conflicts` and shown as notes; logged exercise alone never
   contradicts a higher declaration. The worker stores it as `(:UserModel)`, and the
   `(:User)` node gets `FREQUENTLY_EATS`/`PRACTICES` habit edges, refreshing an owner after each of its
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
`tree` and cross `link` edges) and a timeline.

Optional `start` and `end` (inclusive local days, `YYYY-MM-DD`, Asia/Ho_Chi_Minh)
limit the drawn meals, trainings, measurements and turns to those days, at most 40
of each kind (newest first). Without them the map keeps its compact default (the 14
newest of each kind). A windowed answer adds `window`: the effective `start`/`end`
after clamping to the retained history, its bounds `min`/`max`, the per-kind `limit`,
`totals` in the window before the limit, and `density`, activity per local day and
hub over the whole retained history, which the client draws as a time scrubber.
`start` after `end` is rejected with 422.

Measure retrieval without models (context recall over the eval cases), and the
full agent when model keys are available. `run` compares the app with and without a
graph service (`no_kg` is an ablation by dependency injection, not a setting):

```sh
python -m agentic.evaluation.kg_eval seed
python -m agentic.evaluation.kg_eval retrieval --out /tmp/kg_retrieval
python -m agentic.evaluation.kg_eval run --variants no_kg,kg --repeat 2
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
python -m agentic.knowledge_graph.worker backfill
python -m agentic.knowledge_graph.worker run
```

The standalone `agentic/docker-compose.yml` also starts Neo4j and `kg-worker`.
Its backend DSN must reach the backend PostgreSQL from inside Docker; use
`host.docker.internal` when that database is exposed on the host.
`./dev_up.sh --local` starts Neo4j and a local worker; the agent can be
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
python -m agentic.knowledge_graph.worker retry
python -m agentic.knowledge_graph.worker reconcile
python -m agentic.knowledge_graph.worker rebuild --confirm-rebuild
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

## Measured gates

Keep regression tests green and check production-like measurements against the planned
gates: routing >=95% without >1 percentage-point regression, retrieval p95 <=100 ms
(150 ms cutoff), projection lag p95 <=5 seconds, and `kg_eval run` showing the `kg`
variant no worse than `no_kg` on tool choice and grounded content. Ambiguity, compound
requests, missing fields and graph outages fall back to the backend tools.

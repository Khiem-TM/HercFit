# Deployment and verification

## Runtime layout

The agent depends on sibling backend packages (`schemas`, `models`). The
`knowledge_graph`, `research` and `observability` packages live inside `agentic/`
(and the backend imports `agentic.research` / `agentic.observability`). Run from `backend/` or put that
directory on `PYTHONPATH`. The Docker build context remains `backend/`, not the
agent folder alone. Dependency versions and SQL migrations are unchanged.

Environment precedence remains explicit constructor values, process environment,
`backend/agentic/.env`, then `backend/.env`. Stable package roots in `core/paths.py`
ensure moving configuration code does not change dotenv resolution. Secrets stay
outside Git; `.env.example` lists supported settings.

## Local and production startup

From the repository root with the existing environment/dependencies configured:

```sh
PYTHONPATH=backend .venv/bin/python -m agentic.scripts.migrate
PYTHONPATH=backend .venv/bin/python -m uvicorn agentic.core.app.main:app --host 0.0.0.0 --port 8081
```

For a fresh environment install the existing `backend/requirements.txt` and
`backend/requirements-dev.txt` as appropriate. The agent Dockerfile already
installs backend requirements using its existing build context.

Run migrations as a separate deployment step before starting production replicas.
Development mode retains the existing missing-schema auto-migration behavior.
Do not change database URLs, migration files or persisted graph threads for this
directory migration. Pending confirmations resume through the same node names.

```sh
docker compose -f backend/agentic/docker-compose.yml up --build
```

The `memory` and `kg` Compose profiles remain optional; configure
`SESSION_MEMORY_MODE`, `REDIS_URL`, `KG_MODE` and Neo4j settings when enabling them.
Use `/health` for liveness and `/health/ready` for agent-store/backend readiness.
Optional Redis health is reported without making Redis mandatory for chat.

Replace any external deployment commands that still use the removed paths:

| Existing command/import | Canonical replacement |
| --- | --- |
| `agentic.main:app` | `agentic.core.app.main:app` |
| `python -m agentic.migrate` | `python -m agentic.scripts.migrate` |
| `python -m agentic.maintenance` | `python -m agentic.scripts.maintenance` |
| `python -m agentic.jev_preflight` | `python -m agentic.scripts.jev_preflight` |
| `python -m agentic.tests.evaluation.<runner>` | `python -m agentic.evaluation.<runner>` |

Old import/CLI paths have been removed. All repository deployment commands and
workers now use the canonical paths; external launch configurations must do the same.

## Evaluation and operations

From `backend/`, inspect runner help before running experiments:

```sh
python -m agentic.evaluation.jev_eval --help
python -m agentic.evaluation.kg_eval --help
python -m agentic.evaluation.memory_eval --help
python -m agentic.evaluation.jev_shadow_gates --help
python -m agentic.evaluation.jev_shadow_workflow --help
python -m agentic.scripts.maintenance --help
python -m agentic.scripts.jev_preflight --help
```

Golden sets are under `evaluation/datasets/`. Existing runners retain their own
seed/live-run safeguards and output formats. Live runs may call providers or
write synthetic evaluation data; they are separate from the offline test command.

Shared Langfuse configuration lives in `agentic/observability`. Agent node
latency, input/output tokens, unknown-cost flags, JEV billing and retrieval status
continue through that collector. The app closes clients/checkpointers on shutdown
and unwinds acquired resources if startup fails.

## Local-only analysis

Docker excludes docs, tests, evaluation, reports and traces. The Langfuse exporter
ships in the image but stays off unless `LANGFUSE_TRACING=true` and both Langfuse keys
are set; without them the non-exporting runtime adapter keeps request IDs, node error
handling and model cost accounting.

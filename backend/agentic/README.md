# HercFit Agentic

FastAPI + LangGraph service for authenticated nutrition, training, catalog and
research workflows. The implementation was reorganized in place; public HTTP
contracts, database migrations and existing graph behavior remain compatible.

- [Architecture, module ownership and workflow](docs/architecture.md)
- [Audit and prioritized refactoring plan](docs/refactoring-plan.md)
- [Exact old-to-new module map](docs/module-map.json)
- [Deployment and verification](docs/deployment.md)
- [Coding rules](docs/coding-rules.md) and [AI development instructions](AGENTS.md)
- [Session memory design](services/memory/README.md)

From the repository root, using the existing virtual environment:

```sh
PYTHONPATH=backend .venv/bin/python -m uvicorn agentic.core.app.main:app --port 8081
.venv/bin/python -m pytest -c backend/agentic/pytest.ini backend/agentic/tests
```

Apply database migrations before production startup:

```sh
PYTHONPATH=backend .venv/bin/python -m agentic.scripts.migrate
```

Canonical module ownership:

| Package | Responsibility |
| --- | --- |
| `core/app` | FastAPI entrypoint, configuration, dependencies and API schemas |
| `agents` | LangGraph state, workflows, orchestration, research and tool agents |
| `services` | Runtime, routing, RAG, JEV, catalog logic and conversation memory |
| `components` | Hybrid retrieval adapter, ranking and context filtering |
| `prompts` | Versioned templates and registry |
| `tools` | Tool registry, definitions, policies, schemas and integrations |
| `security` | Input, content and output checks |
| `knowledge_graph` | Optional Neo4j projection, user model, graph retrieval and outbox worker |
| `research` | Research contracts, evidence audit, source registry and finalization attestation |
| `observability` | Shared runtime adapter (request/trace IDs, middleware, propagation), execution guards and telemetry |
| `evaluation` | Evaluation runners and golden datasets |
| `scripts` | Migration, maintenance and JEV preflight commands |

Legacy module/CLI aliases have been removed. Use `agentic.core.app.main:app` for
the server and `agentic.scripts.*` / `agentic.evaluation.*` for commands. Docker,
Compose, the development script and the Knowledge Graph worker use these paths.

`docs/` and `tests/` are retained locally and ignored by Git throughout the
repository. The linked local documentation and test commands require those local
files; a fresh checkout does not include them.

## Development-only tracing and evaluation

Offline evaluation (`evaluation/`), test suites, architecture notes under `docs/`,
trace output and analysis reports are local assets excluded from Git and Docker.
The optional LangSmith exporter lives at `backend/agentic/observability/_dev/`; it is
loaded only when `MODE=dev` and enabled by the existing LangSmith configuration.
A clean checkout or deployment image uses `agentic/observability/runtime.py`, which
keeps request correlation and disables trace export even with inherited SDK flags.
Run local setup with `python -m agentic.observability._dev.bootstrap` from `backend/`.
Node guards, token/cost accounting and JEV runtime decisions remain versioned.
The local evaluation commands above require the developer's evaluation files.

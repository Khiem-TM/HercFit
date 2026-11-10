# Agentic architecture refactor

## Audit and scope

This is an incremental reorganization of the current working tree, including its
uncommitted implementations. It does not replace the agents or change backend
contracts. Baseline: 439 unit tests passed before edits (2026-10-29).

Findings:

- `core/` mixes state, routing, UI clarification, catalog business logic, model
  adapters, safety, prompt layout and telemetry.
- FastAPI composition, configuration, API dependencies and schemas are spread
  across top-level packages. Settings depend on their physical file location.
- Workflow assembly contains retrieval policy; research embeds source ranking,
  query guards, output verification and prompt templates.
- Evaluation runners and frozen datasets live under `tests/evaluation`, with
  source-path inspection of research prompts.
- Root ignore rules exclude tests and docs, including regression coverage already
  present on disk. Scoped exceptions are needed for this service.
- The backend owns approved-document hybrid retrieval (`embedding/retrieval.py`:
  pgvector + PostgreSQL full-text + reciprocal-rank fusion), database models,
  These remain in place; knowledge graph projection, research and shared observability were later moved under `agentic/`.
- Nutrition and Training are domains of the existing ToolAgent, not independent
  LangGraph nodes. Redis provides session memory; Tavily/JEV use exact caching.
  BM25, semantic response caching and a separate query-rewriter are not implemented.

## Prioritized steps

1. **P0 — Freeze compatibility.** Run existing tests; snapshot OpenAPI, registry
   fingerprint, prompt text and migration hashes. Preserve the working tree.
2. **P0 — Move ownership.** Establish `core/app`, `services`, `components`,
   `prompts`, `security`, `observability`, `evaluation` and `scripts`. Move existing
   implementations and update internal imports. Keep lightweight aliases for old
   module paths and runnable wrappers for old commands.
3. **P1 — Extract existing boundaries.** Move prompts without wording changes;
   separate source ranking/context filtering, query/output guards and graph
   retrieval from agent orchestration. Retain constructor injection and all
   graph node names, state fields, reducers, budgets and confirmation rules.
4. **P1 — Verify contracts and workflows.** Run unit, workflow and service tests;
   compare OpenAPI/tool/migration/prompt contracts and check import boundaries.
   Run database integration tests only against explicitly isolated test services.
5. **P1 — Document and hand over.** Publish the source-to-target map, workflow
   diagram, deployment commands, extension points and coding rules in `AGENTS.md`.

## Explicitly deferred

New retrieval algorithms, semantic caches, extra model calls, dedicated Nutrition
or Training graph nodes, database/schema changes, provider upgrades and a new DI
framework require their own behavior change and evaluation. They are not needed
to reorganize this service safely.

Compatibility aliases were initially retained, then removed at the user's request
after migrating all repository consumers and deployment commands (see cleanup below).

## Implementation and validation result

All five steps above are implemented. Forty-two old module paths alias their
canonical implementations; the exact mapping is in `module-map.json`. Major
instructions and JEV gate questions are versioned without text changes. Source
ranking, context bounds, research guards and node telemetry have dedicated owners.
App composition additionally cleans up resources after partial startup failures.

Validation on 2026-10-29:

| Check | Result |
| --- | --- |
| Original Agentic unit baseline | 439 passed |
| Refactored Agentic suite, including new contract/workflow tests | 499 passed, 13 skipped |
| Backend and Knowledge Graph regression suites | 82 passed, 25 skipped, 1 existing failure |
| Canonical and historical maintenance/evaluation CLI `--help` | 14 commands passed |
| Agentic Docker Compose configuration | `config --quiet` passed |
| OpenAPI, tool fingerprint, SQL, prompts, state and golden datasets | Frozen contract checks passed |

Skipped tests require isolated PostgreSQL, Redis or Neo4j services. No production
database, live provider evaluation or container deployment was run.

The existing failure is
`backend/agentic/tests/knowledge_graph/test_visualization.py::test_owner_gate_and_output_allowlist`.
Its fake query result supplies the old `nodes`/`edges` shape, while the current
visualization implementation reads `model`, `records`, `runs` and `habits`.
The same failure was reproduced using the saved pre-refactor Agentic sources.
Neither the unrelated visualization implementation nor its test was changed.


## Follow-up cleanup

At the user's request, removed all 42 legacy module/CLI wrappers, `_compat.py`
and seven obsolete packages. Updated both main backend container entrypoints,
`dev_up.sh`, the Knowledge Graph worker and its operational README to canonical
paths. Old import/CLI paths are no longer supported; the public HTTP API and
persisted state remain unchanged.

All `docs/` and `tests/` directories are now ignored throughout the repository.
Their local contents are retained, except the obsolete evaluation wrappers.
Existing tracked test files are removed from the Git index without deleting their
remaining local contents. The original validation results above describe the
pre-cleanup refactor; cleanup tests check canonical imports and absence of aliases.

Cleanup validation: 499 Agentic tests passed, 13 integration tests skipped; all
7 canonical CLI help commands, canonical app/worker imports, both Compose configs
and the development script syntax check passed. No removed-module imports remain.

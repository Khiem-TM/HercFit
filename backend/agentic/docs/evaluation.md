# Evaluation

One evaluation pipeline for every HercFit quality signal. Pydantic Evals orchestrates golden datasets on the
real LangGraph runtime; Ragas scores semantic RAG quality in an isolated environment; deterministic Python
metrics cover retrieval, routing, tools, cost and latency; Langfuse stores experiments and trace-linked scores.

```text
golden dataset (JSONL, versioned, fingerprinted)
        │
        ▼
Pydantic Evals Dataset ──► GraphRuntimeAdapter ──► build_workflow (real graph, real agents, real HITL gate)
        │                       │                     isolated EvalStore + stateful EvalBackend (no prod data)
        │                       ▼
        │              AgentExecutionRecord / RetrievalRecord   (vendor-neutral contracts.py)
        ▼
case evaluators (agent.py, safety.py)  +  report evaluators (confusion matrix)
        │
        ▼
EvaluationRun ──► reporting.py: aggregates · hard-safety gate · quality gates · baseline regression · exit code
        │                                   │
        ▼                                   ▼
langfuse_sync.py (dataset, experiment,      run.json / report.json / report.md / index.md (CI artifact)
trace-linked scores, no duplicates)
```

## Modules

| Module | Role |
|---|---|
| `evaluation/contracts.py` | Typed records: `EvaluationCase`, `AgentExecutionRecord`, `ToolExecutionRecord`, `RetrievalRecord`, `EvaluationScore`, `EvaluationRun`, `EvaluationReport`. Depends only on Pydantic. |
| `evaluation/adapters/graph_runtime.py` | Runs the real graph for a case (`deterministic`: scripted models; `live`: configured models) and records route, agents, tools, confirmations, verified backend state, usage. |
| `evaluation/adapters/fixtures.py` | In-memory action store (real `Store.authorize` checks) and a stateful backend with per-user ownership, idempotency replay and fault injection. |
| `evaluation/evaluators/agent.py` | Routing, agent selection, tool selection/arguments/order/budget, forbidden tools, confirmation gate, user isolation, duplicate writes, verified business outcome, code rules, reply checks. |
| `evaluation/evaluators/safety.py` | Safety verdict, no write on a safety block, prompt-injection resistance, medical reply language (live), optional LLM judge with a versioned rubric. |
| `evaluation/scoring.py` | Hit/Precision/Recall@K, MRR, nDCG, P/R/F1, macro-F1, confusion matrix, latency percentiles, token/cost totals (unknown price stays unknown). |
| `evaluation/runner.py` | Pydantic Evals orchestration and conversion to the contract; run metadata (commit, release, dataset fingerprint, models, prompt versions, graph version, evaluator versions). |
| `evaluation/reporting.py` + `quality_gates.json` | Gates, baseline comparison, Markdown/JSON reports, exit codes. |
| `evaluation/rag_suite.py` | Retrieval variants with raw → reranked → final context stages; answer drafting for Ragas. |
| `evaluation/ragas_scoring.py` | Ragas 0.4.3 `metrics.collections` bridge, run in `.venv-ragas`. |
| `evaluation/adapters/legacy.py` | Daily Health backtest, JEV holdout import (split leakage checks), KG/memory/personalization/benchmark imports, `report` index. |
| `evaluation/performance.py` | Deterministic load benchmark (1/8/32 concurrent turns) with isolation checks. |
| `evaluation/langfuse_sync.py` | Langfuse datasets/experiments/scores, regression candidates, model prices. |

The pre-existing runners (`agent_model_eval.py`, `rag_eval.py`, `kg_eval.py`, `jev_eval.py`, `memory_eval.py`,
`personalization_eval.py`, `system_benchmark.py`) are unchanged and still usable directly.

## Commands

Run from `backend/` (or use the root `Makefile`: `make eval-agent`, `make eval-report`, …).

| Logical entry | Command | Needs |
|---|---|---|
| eval:agent | `python -m agentic.evaluation agent [--mode live --allow-paid] [--repeat N] [--trace] [--langfuse]` | live: model key + explicit spend |
| eval:safety | `python -m agentic.evaluation safety [--mode live --allow-paid]` | as above |
| eval:rag | `python -m agentic.evaluation rag --allow-paid --variants vector bm25 hybrid hybrid_rerank hybrid_rerank_multiquery [--ragas]` | DB + paid embeddings/rerank |
| eval:kg | `python -m agentic.evaluation kg --import-only <kg_eval out dir>` | run `kg_eval` in the agentic container first |
| eval:jev | `python -m agentic.evaluation jev --split holdout --import-only <prefix>` | Jev gateway run + human reviews |
| daily health | `python -m agentic.evaluation daily-health` | nothing (synthetic, seeded) |
| performance | `python -m agentic.evaluation performance` | nothing (scripted models) |
| eval:full | `python -m agentic.evaluation full [--live --allow-paid --judge]` | per suite |
| eval:report | `python -m agentic.evaluation report --out eval_results/quality` | previous runs |
| Ragas | `.venv-ragas/bin/python backend/agentic/evaluation/ragas_scoring.py <ragas-input.jsonl> --out <scores.jsonl>` | `RAGAS_JUDGE_*`, `RAGAS_EMBEDDING_*` |

Exit codes: `0` pass · `1` quality or regression gate failed · `2` hard safety gate failed · `3` runner or
infrastructure error · `4` blocked (missing credential/service, or a paid run without `--allow-paid`).
A blocked suite is never reported as passing.

Setup: `pip install -r backend/requirements-dev.txt -r backend/agentic/requirements-eval.txt`. Ragas:
`python3.13 -m venv .venv-ragas && .venv-ragas/bin/pip install -r backend/agentic/requirements-ragas.txt`
(ragas 0.4.x needs openai<3.4, which conflicts with the agent runtime, so it never shares the runtime venv).

## Deterministic versus live

Deterministic runs replace only the language models with per-case scripts (`input.script`); routing rules, tool
policy, the meal fast path, the food-gap card, the confirmation gate, store authorization, safety assessment and
receipts are the production code. They are free, run in CI and must reproduce exactly (thresholds 1.0). Live runs
use the configured models and measure model routing and tool use; thresholds come from `agent_model_eval`
(`FLOOR`, `TOLERANCE`) and the 2026-11-07 agent × model run. The adapter runs the graph, not the HTTP/session
layer (that needs PostgreSQL).

## Gates

`quality_gates.json` holds every threshold with its justification, per `suite:mode`.

1. **Hard safety** — `no_unconfirmed_write`, `user_isolation`, `no_forbidden_tool_executed`,
   `confirmation_required`, `no_duplicate_write`, `safety_verdict`, `no_write_on_safety_block`,
   `injection_resisted`, plus suite-specific ones (`needs_review_neutral`, `load_isolation`). Zero violations;
   a perfect semantic score cannot compensate.
2. **Quality** — absolute minimums (`task_success`, `routing_accuracy`, `tool_selection_accuracy`,
   `argument_accuracy`, …). A metric with no labelled case is reported as "no labelled cases", and fails only
   when the gate is `required`.
3. **Regression** — drop versus the committed baseline (`evaluation/baselines/<suite>-<mode>.json`), only when the
   dataset fingerprint matches. A changed dataset is reported `not_comparable` until re-baselined.

Update a baseline only from a passing run on a reviewed commit:
`python -m agentic.evaluation agent --update-baseline` (refuses a dirty tree unless `--allow-dirty`, which is
recorded in the baseline).

## Adding a golden case

1. Append one JSON line to `evaluation/datasets/agent_golden.jsonl` (fields: `id`, `suite`, `severity`, `modes`,
   `tags`, `input`, `reference`). `reference` is written by a person; never paste a model output as the
   expected answer.
2. `input.turns` holds messages (`mode`: `normal` or `plan`; profile/health writes need `plan`), optional
   `food_choices`, `confirm` (`approve`, `reject` or a list per confirmation) and `backend_failures`
   (`{"tool": status}`). Deterministic cases add `input.script` (`decision` RouteDecision dicts, `tool` call lists,
   `reply`).
3. Supported reference keys: `route`, `agents`, `tools_required`, `tool_order`, `arguments` (dotted paths such as
   `items[0].food_id`), `confirmation_required`, `final_status` (value or list), `expected_writes`,
   `max_tool_calls`, `tools_forbidden`, `route_rules`, `reply_must`, `reply_must_not`, `foreign_resource_ids`,
   `injection`, `safety_category`, `medical_reply`, `allow_duplicate_writes`. The unit test
   `test_golden_dataset_is_valid_and_critical_cases_carry_safety_expectations` rejects unknown keys.
4. Bump `DATASET_VERSION` in `runner.py`; the fingerprint changes automatically and the baseline becomes
   `not_comparable` until it is re-baselined after review.
5. Use synthetic users (`u-eval-1`, `u-eval-2`) and the catalog in `fixtures.py`. Never copy production
   conversations.

## RAG and Ragas

`rag_suite.py` reuses the 87-case dataset (`rag_cases.jsonl`, page-range gold labels) and records three stages
per case: fused candidates (before rerank), reranked candidates and the final contexts. Deterministic metrics:
Hit/Precision@1/3/5/10, Recall@5 (expected page ranges found), MRR@10, nDCG@5, chapter@3, candidate recall,
out-of-domain rejection. Variants: `vector`, `bm25` (PostgreSQL full-text `ts_rank_cd`, the BM25 role),
`hybrid` (RRF), `hybrid_rerank` (production), `hybrid_rerank_multiquery` (the dataset's human-written
paraphrases; this is not LLM query rewriting). With/without the knowledge graph is the `kg` suite (`kg_eval`
no_kg/kg ablation): the personal graph is a separate pipeline from book retrieval.

`--ragas` drafts answers with the system's research model from exactly the retrieved contexts and exports
`ragas-input-<variant>.jsonl`. `ragas_scoring.py` computes faithfulness, answer relevancy and context precision
(reference-free) for every record; context recall and factual correctness only for records with a
human-verified `reference_answer`. The dataset has none today, so these two metrics are reported as "not
computed"; references are never generated by an LLM. Record the judge model and versions printed by the scorer.

## JEV

`jev_eval.load_cases` keeps the 100 calibration / 200 holdout split and refuses scenario-level leakage;
`legacy.split_leakage` additionally rejects the same normalized message in both splits. The JEV report is
blocked unless every case has paired `off`/`enforce` runs with matching fixture, model and case fingerprints,
complete human reviews and known usage/price. `JEV_MODE=enforce` is not evidence of quality.

## Langfuse

`--langfuse` (or `python -m agentic.evaluation langfuse-sync <run.json>`) upserts dataset `hercfit-<suite>`
(item id = uuid5 of suite, case and dataset fingerprint), runs `Langfuse.run_experiment` over the recorded
outputs (no re-execution) so each case gets an experiment trace with its scores, and adds run-level scores
(`run_<aggregate>`). Experiment metadata carries commit, dirty flag, release, environment, dataset version and
fingerprint, models, prompt versions, graph version, RAG/JEV config and evaluator versions. With `--trace`, each
case also runs inside its own trace and the scores are attached to that trace with deterministic `score_id`s.
A `.langfuse-synced` marker prevents a second ingestion of the same run (`--force` to override).

Regression feedback loop: `python -m agentic.evaluation regression-candidates --max-value 0` lists traces with
failing `task_success`/`user_feedback` scores as trace ids plus metadata only (`content_copied: false`). A
reviewer reads the trace in Langfuse, writes a sanitized synthetic case into the golden dataset, runs the
deterministic suite, compares with the baseline and only then re-baselines. Production health conversations
are never copied automatically.

## CI

`.github/workflows/quality.yml`:

* **PR/commit gate** (every PR and push to `main`, no paid calls): pinned ruff, import checks,
  deterministic agent and safety suites, Daily Health backtest, load smoke, `eval:report`; reports uploaded as an
  artifact. The frontend job type-checks.
* **Pre-release** (tags `v*` or manual, `release` environment with approval and secrets): deterministic first,
  then live agent/safety benchmark with tracing and Langfuse sync, JEV holdout import.
* **Scheduled** (weekly): `full --live --judge --repeat 3` (stability), alert check on the reports.

## Troubleshooting a failed case

1. Open `report.md` (failed gates and cases) and `run.json` (`results[].record`: route, `route_rules`, tools with
   outcome/approval/execution, `verified_state.writes`, errors; `results[].scores[].explanation`).
2. Re-run one case: `python -m agentic.evaluation agent --cases <id>`; add `--trace` with tracing configured to
   inspect node/model/tool spans in Langfuse (`eval.case` root).
3. `infrastructure` errors mean the adapter or a dependency failed, not the agent: check the error code first.
4. A `not_comparable` baseline means the dataset changed; review and re-baseline instead of loosening a gate.

## Rollback and migration

All changes are additive: evaluation code is not imported by the runtime. Observability changes are additive
metadata keys, a new `/health/metrics` endpoint (internal network only; Caddy proxies only `/api/v1/*` to the
agent) and logging configuration. To roll back a gate change, revert `quality_gates.json` and the baseline
together. Removing the CI workflow does not affect the application.

## Remaining external requirements

* Paid runs (live agent, RAG embeddings/rerank, Ragas judge, LLM judge) need provider credentials and an
  explicit `--allow-paid`; none were run while building this pipeline.
* Human-verified reference answers for RAG (Ragas context recall, factual correctness).
* JEV holdout results with human reviews.
* GitHub `release` environment with secrets (`FPT_API_KEY`, `LANGFUSE_*`, `JUDGE_*`) and variables.

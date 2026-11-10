# Observability

Langfuse (SDK 5.1, OpenTelemetry) is the only tracing and experiment backend. There is one tracer provider per
process, owned by the Langfuse client; nothing else installs an OpenTelemetry provider or exporter.

## Trace shape

```text
http.agentic (ObservabilityMiddleware, root; request_id ↔ trace_id, x-request-id / x-trace-id headers)
 └─ runtime.chat / runtime.confirm (observed)
     └─ LangGraph nodes, model generations, tools (one Langfuse CallbackHandler via graph_config)
         └─ backend.tool → backend.request → backend.http_attempt (one span per HTTP attempt)
              └─ backend service continues the same trace (signed traceparent + baggage, HMAC)
background workers: worker.* roots, linked through durable_context (outbox, confirmation, KG projection)
```

Cross-service continuation only accepts headers signed with `LANGFUSE_PROPAGATION_SECRET`
(`propagation.trusted_parent`); unsigned or stale headers start a new trace.

## Application-level chat outcomes

SSE returns HTTP 200 as soon as the stream opens, so failures after that point are invisible in `http_status`.
`observability/outcomes.py` gives every `/chat`, `/chat/stream` and `/chat/confirm` session exactly one terminal
outcome:

| Event (log `hercfit.chat`) | Meaning |
|---|---|
| `chat_started` | session accepted (after auth, rate and daily limits) |
| `chat_first_token` | first answer token delivered to the client (`first_token_ms`) |
| `chat_completed` | terminal event delivered; `result_status` = completed / needs_input / pending_confirmation |
| `chat_failed` | `failure_class`: `provider` (model/SDK error), `server` (HercFit code, backend, checkpoint), `client` (4xx rejection inside the stream) |
| `chat_timeout` | the run exceeded its time budget |
| `chat_cancelled` | the client disconnected before the terminal event was delivered (`client_disconnect`); the run is cancelled |

The outcome is recorded only after the terminal event has actually been sent. Errors deep in the graph (node
failures, model errors, run timeouts) are noted on the active session so the class is correct even though the
runtime converts them into a `failed` ChatResponse. The root trace receives `chat_outcome`, `failure_class`,
`chat_duration_ms`, `first_token_ms` and `chat_mode`, and its status follows the application outcome, not the
HTTP status. Request completion logs (`request_finished`) carry the same status.

## Model calls: logical versus physical

`telemetry._MeasuredModel` counts per logical call: `llm_calls` (agent requests), `llm_attempts` (each model
started: primary plus every fallback), `llm_fallbacks`, `llm_attempt_errors` by kind (`rate_limit`, `timeout`,
`connection`, `server`, `auth`, `other`), `llm_sdk_retries` (OpenAI SDK internal retries, observed from its
`Retrying request` log line) and retry exhaustion. Per-node values reach the node span; per-run totals are in
the checkpoint telemetry and the evaluation records. Every physical attempt is also its own Langfuse
generation (LangChain callback). Cost: `MODEL_PRICES` only; a model without a verified price is
`cost_status=unknown` and `total_model_cost=None`, never 0. `langfuse_sync.sync_model_prices` pushes the same
verified prices to Langfuse model definitions.

## Process metrics and alerts

`observability/metrics.py` keeps bounded-cardinality counters and histograms per process (labels only from
finite sets; more than 200 label sets per metric collapse into `other`). `GET /health/metrics` (agent
service, internal network only) returns the snapshot plus exporter status.

| Metric | Labels |
|---|---|
| `chat_started_total`, `chat_sessions_total` | endpoint, chat_mode, outcome, failure_class, result_status |
| `chat_ttft_ms`, `chat_duration_ms` (histograms, p50/p95/p99) | endpoint, chat_mode / outcome |
| `llm_calls_total`, `llm_attempts_total`, `llm_attempt_errors_total`, `llm_retry_exhausted_total`, `llm_sdk_retries_total` | agent, outcome, kind |
| `tool_calls_total` | tool (registry name), outcome |
| `backend_http_attempts_total`, `backend_http_retries_total`, `backend_http_retry_exhausted_total` | method, outcome, reason |
| `agent_node_failures_total` | node, error_class |
| `worker_failures_total`, `worker_last_success_ts` (gauge) | worker, error |
| `telemetry_export_errors_total`, `telemetry_spans_dropped_total` | source |

`python -m agentic.observability.alerts --url http://agentic:8081/health/metrics --state <file>` evaluates
window deltas (cron, e.g. every 5 minutes) against `alerts.RULES` (each with a minimum volume and a written
reason): chat failure rate, SSE failure rate, TTFT p95, chat duration p95, provider retry exhaustion and rate
limits, tool backend errors, worker failures/stalls, telemetry export errors, evaluation regressions
(`--reports eval_results/quality`). Exit 0/1/2 = none/warning/critical. Thresholds are initial proposals without
production data; recalibrate after two weeks. Paging (Slack, e-mail, on-call) is not wired yet: connect the
exit code or JSON output to the team's notifier.

Counters are per process: with several workers, scrape each worker or aggregate in the monitoring system.

## Logging

`observability/logs.configure_logging` applies `LOG_LEVEL` (default WARNING) to the root logger and
`REQUEST_LOG_LEVEL` (default INFO) to `hercfit.requests` and `hercfit.chat`, so correlation logs are emitted even
when the application level is WARNING. Both services and the KG worker call it at startup. Logs never contain
message content, exception bodies or identifiers other than request/trace ids.

## Exporter health and collector outages

Export runs on the SDK's background thread; requests never wait for it. `Observer.close` flushes with a bound of
`LANGFUSE_FLUSH_SECONDS`. `/health/ready` and `/health/metrics` report `export_errors` (Langfuse logger),
`export_failures` (OTLP exporter failures), `spans_dropped` (queue full) and `delivery_verified: false`: zero
errors do not prove delivery. `python -m agentic.observability.bootstrap --smoke` sends a synthetic trace and
reads it back from Langfuse; run it after each deployment.

## Release, environment and pricing

`LANGFUSE_RELEASE` falls back to `HERCFIT_RELEASE` or `GIT_COMMIT_SHA` (passed by `dev_up.sh`, docker-compose and
the Docker build arg); `/health/ready` shows the effective release. Set `LANGFUSE_TRACING_ENVIRONMENT`
(`dev`, `staging`, `production`) per deployment. Production values to set: `LANGFUSE_CAPTURE_MODE` (consider
`metadata_only` in production), `LANGFUSE_SAMPLE_RATE`, explicit `LANGFUSE_PSEUDONYM_SECRET` and
`LANGFUSE_PROPAGATION_SECRET` (otherwise derived from the secret key and rotated with it), and `MODEL_PRICES`
from the provider contract.

## Health-data privacy

Controls in code:

* Inputs, outputs and metadata pass through `privacy.bounded` before export: secrets, identity fields, images,
  embeddings and health values (body metrics, vitals, device sleep/readiness/ECG values, free-text values such as
  "62 kg") are masked; payloads are size-bounded.
* Users and sessions are HMAC pseudonyms; raw ids are additionally masked wherever they appear.
* Metadata is an allowlist (`META_KEYS`): unknown keys are dropped.
* `metadata_only` removes all input/output attributes at export.
* Metrics and logs carry no content and no identifiers.
* Evaluation datasets are synthetic; the regression loop copies trace ids only.

Not verified or not implemented (owner action required):

| Requirement | Status |
|---|---|
| Langfuse data region and processor agreement (current base URL is the US cloud region) | not verified |
| Trace retention period configured in the Langfuse project | not verified |
| Access control: Langfuse project roles, SSO, key rotation | not verified |
| Erasure: `DELETE /api/v1/chat/me` removes checkpoints and memory but does not delete the user's Langfuse traces (they are pseudonymized; deletion needs the trace delete API keyed by the HMAC pseudonym) | not implemented |
| Masking of free-text health statements that do not match a known pattern | partial (pattern-based) |

Do not claim compliance until these are closed.

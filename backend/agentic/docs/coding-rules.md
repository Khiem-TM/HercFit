# Coding rules

1. **One owner per concern.** FastAPI composition belongs in `core/app`, graph
   coordination in `agents`, business/session logic in `services`, retrieval
   primitives in `components`, transport adapters in `tools/integrations`, safety
   checks in `security`, and model/node metrics in `observability`.
2. **Reuse contracts.** Import backend Pydantic schemas. Tool-only wrappers belong
   in `tools/schemas`; reusable declarations belong in `tools/definitions`.
   Execution goes through ToolAgent, never a StructuredTool declaration.
3. **Inject resources.** Pass models, settings, store, checkpointer and clients
   explicitly. Initialize network clients at lifespan/runtime boundaries, with
   cleanup and deadlines. Use async I/O in async paths.
4. **Protect state compatibility.** Keep one AgentState and RouteDecision. Return
   partial updates, preserve message reducers and serialized fields. A renamed
   graph node/state key needs checkpoint migration analysis and regression tests.
5. **Keep prompts reviewable.** Stable instructions are versioned and independent
   of run-specific data. Add a prompt version for a behavioral change; evaluate
   it before changing callers. Do not interpolate secrets or private histories
   into public research/JEV projections.
6. **Keep approval durable.** Validate/normalize a payload, create a preview,
   persist the pending action, and wait for structured confirmation. Verify
   owner/revision/hash and use the same idempotency key on retries. A rejected or
   stale action cannot execute. A changed catalog finalization needs a new preview.
7. **Degrade deliberately.** KG/Redis outages preserve the established fallback.
   An empty catalog differs from a failed backend. Bound provider calls and
   research budgets; retain unknown billing signals. Log error type and safe
   metadata rather than upstream bodies.
8. **Test observable contracts.** Cover auth, routing, retrieval, output evidence,
   streaming, approval/resume and cleanup using synthetic dependencies. Use a
   disposable database/Redis only via explicit test environment variables.
9. **Avoid migration churn.** Do not reformat unrelated code, update providers,
   change schemas or add speculative abstractions during a directory refactor.
   Legacy import/CLI aliases have been removed; update consumers instead of restoring them.

The import-boundary and frozen-contract tests enforce the migration invariants.
These rules guide future edits; they do not imply that all legacy formatting or
every possible safety failure has been addressed by this refactor.

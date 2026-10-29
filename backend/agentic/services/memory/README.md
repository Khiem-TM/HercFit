# Agent session memory (Redis)

PostgreSQL checkpoints stay authoritative for approvals, recovery and the
verbatim conversation window. Redis is an optional, rebuildable hot tier
(`session_memory.py`, pure helpers in `transcript.py`) that adds what a
checkpoint-only turn forgets:

- **Transcript** — every turn of the session (user message + final replies,
  exactly what `/history` shows), not only the last 40 messages.
- **Rolling summary** — turns that left the verbatim window are folded into a
  short Vietnamese summary by the `summary` model role, in the background,
  about once every `SESSION_MEMORY_SUMMARY_TRIGGER_TURNS` turns. Turns that left
  the window but are not summarized yet are shown verbatim, so nothing is lost
  in between.
- **Touched records** — foods, exercises, meals, trainings, goals, metrics and
  plans the conversation read or wrote, taken from backend outputs (no model).

At the start of a turn this memory is prepended as one bounded system message
marked as data, not instructions. Summary and records are also stored in the
graph state (`session_memory`), so a Redis loss never loses them.

## Start

```sh
# Images built before this feature lack the redis package: rebuild once.
docker compose -f backend/docker-compose.yml build agentic
./dev_up.sh up --memory -d            # Redis on 127.0.0.1:6379 (profile "memory")
# Set SESSION_MEMORY_MODE=shadow in backend/.env, then recreate the agent.
```

Modes: `off` (default) never imports or touches Redis; `shadow` writes the
transcript, records and summaries (summaries cost model calls) and measures them,
while prompts, `/history` and `/sessions` still read checkpoints; `on` serves them
from Redis. Promote after the memory eval passes (it reuses the KG eval user):

```sh
python -m agentic.evaluation.kg_eval seed
python -m agentic.evaluation.memory_eval run --modes off,on
```

Then consider lowering `SESSION_MEMORY_WINDOW_MESSAGES` (40 = checkpoint-only
behaviour) to cut prompt tokens.

## Keys

All keys of a session share the hash tag `{session_id}` and expire after
`SESSION_MEMORY_TTL_SECONDS` without activity (default 30 days, matching
`KG_MEMORY_RETENTION_DAYS`).

| Key | Type | Content |
|---|---|---|
| `hf:agent:s:{sid}:meta` | hash | owner, generation, fixed title, counts, last run |
| `hf:agent:s:{sid}:turns` | hash | run ID → turn JSON |
| `hf:agent:s:{sid}:order` | zset | run IDs by sequence |
| `hf:agent:s:{sid}:summary` | hash | text, last summarized sequence, covered messages |
| `hf:agent:s:{sid}:entities` | string | recent records (JSON) |
| `hf:agent:s:{sid}:summarizing` | string | single-flight lock for the summarizer |

## Consistency and failure

Request-path writes happen inside the session's PostgreSQL advisory lock. The
background summarizer holds a `SET NX` lock and commits with `WATCH/MULTI`, so a
concurrent trim, clear or reused session discards its result. Every request-path
call is bounded by `REDIS_TIMEOUT_MS`; a failure opens a 5 second breaker and
the turn proceeds from checkpoints. A turn that ended without recording (cancelled
stream, crash) is recorded from its checkpoint the next time the session is used.
Sessions created before Redis are seeded from their checkpoint window.

## Privacy and deletion

Redis holds message text and summaries. Bind it to localhost or a private
network, use a password (`rediss://` in production) and never log memory
content. Clearing a session unlinks its keys; if Redis is unreachable at that
moment, the reconcile loop purges keys of recently deleted sessions, and reads
always reject a stale session generation. Summaries use the same model provider
that already receives the conversation; research and Jev still never see history.

To drop all memory (no business data is lost):

```sh
redis-cli -a "$REDIS_PASSWORD" --scan --pattern 'hf:agent:s:*' | xargs redis-cli -a "$REDIS_PASSWORD" unlink
```

"""Durable PostgreSQL work queue (jobs table, migration 0018).

queue.py   enqueue with dedupe, claim with SKIP LOCKED and a fencing epoch,
           heartbeat, complete/retry/needs-attention, reaper
retry.py   error classes -> what happens next, full-jitter backoff
quota.py   token buckets for provider quotas (per user, per project)
"""

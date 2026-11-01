"""Feature switches read from settings (backend/.env).

READER_V2_DOMAINS moves one consumer at a time onto the health platform's records
(docs/GOOGLE_HEALTH_PLATFORM_2026-11-01.md). Each domain changes one documented
behaviour; an empty list keeps every reader on its v1 behaviour.

  training   device runs (Google) count in running analytics unless a manual run
             covers the same time; no workout type, RPE or sets are invented for them
  nutrition  daily intake also counts meals logged in other apps (Google nutrition
             logs not linked to a HercFit meal)
  body       one weigh-in seen twice (manual + scale within 10 min, <= 0.2 kg apart)
             counts once in weight trends, the manual reading wins
  wellbeing  the overview context carries a counts-only wellbeing summary (needs the
             separate sensitive consent; never symptom names or moods)
  analytics  baselines use complete past days only, served from ANALYTICS_RECOMPUTE
             when stored, recomputed live with the same algorithm otherwise
  agent      the assistant reads health through the context API; raw tools whose v1
             routes are superseded are not offered (agent service, same .env)
"""
from __future__ import annotations

from core.settings import READER_V2_CHOICES, settings


def reader_v2(domain: str) -> bool:
    if domain not in READER_V2_CHOICES:
        raise ValueError(f"unknown reader domain {domain!r}")
    return domain in settings.READER_V2_DOMAINS


__all__ = ["READER_V2_CHOICES", "reader_v2"]

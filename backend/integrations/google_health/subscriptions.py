"""Provision the webhook subscriber (admin task, separate from any user's OAuth).

    GH_ADMIN_ACCESS_TOKEN=$(gcloud auth print-access-token) \\
        python -m integrations.google_health.subscriptions ensure [--dry-run]
    python -m integrations.google_health.subscriptions show

The subscriber uses AUTOMATIC subscriptions for every webhook-capable type the
registry enables: Google subscribes each consenting user itself (no backfill:
onboarding imports history through the job pipeline). Creating the subscriber or
changing its URI/secret triggers Google's handshake against our endpoint, so the
API must already run with GH_WEBHOOK_ENABLED and the same GH_WEBHOOK_SECRET.
`subscriberConfigs` is replaced as a whole on update (PATCH with updateMask).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx

from core.settings import settings
from integrations.google_health.client import ROOT_URL
from integrations.google_health.contract.registry import DATA_TYPES, Op, runtime_enabled


def webhook_types() -> list[str]:
    return sorted(item.id for item in DATA_TYPES.values() if item.webhook and item.readable
                  and runtime_enabled(item.id, Op.LIST if Op.LIST in item.read_ops else Op.DAILY_ROLLUP,
                                      verified=settings.verified_capabilities))


def payload() -> dict:
    if not settings.GH_WEBHOOK_PUBLIC_URL or not settings.GH_WEBHOOK_SECRET:
        raise SystemExit("Set GH_WEBHOOK_PUBLIC_URL (https://…) and GH_WEBHOOK_SECRET first")
    uri = settings.GH_WEBHOOK_PUBLIC_URL.rstrip("/") + f"/api/v2/integrations/google-health/webhooks/{settings.GH_SUBSCRIBER_ID}"
    return {"endpointUri": uri, "endpointAuthorization": {"secret": settings.GH_WEBHOOK_SECRET.get_secret_value()},
            "subscriberConfigs": [{"dataTypes": webhook_types(), "subscriptionCreatePolicy": "AUTOMATIC"}]}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("ensure", "show"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not settings.GH_PROJECT_NUMBER:
        raise SystemExit("Set GH_PROJECT_NUMBER (the Cloud project number, not its id)")
    parent = f"projects/{settings.GH_PROJECT_NUMBER}"
    name = f"{parent}/subscribers/{settings.GH_SUBSCRIBER_ID}"
    body = payload() if args.command == "ensure" else None
    if args.dry_run:
        redacted = json.loads(json.dumps(body))
        redacted["endpointAuthorization"]["secret"] = "<redacted>"
        print(json.dumps({"name": name, **redacted}, indent=2))
        return 0
    token = os.environ.get("GH_ADMIN_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set GH_ADMIN_ACCESS_TOKEN (e.g. $(gcloud auth print-access-token))")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=f"{ROOT_URL}/v4", headers=headers, timeout=60) as http:
        existing = await http.get(name)
        if args.command == "show":
            print(json.dumps(existing.json(), indent=2))
            return 0 if existing.status_code == 200 else 1
        if existing.status_code == 404:
            response = await http.post(f"{parent}/subscribers", params={"subscriberId": settings.GH_SUBSCRIBER_ID},
                                       json=body)
        else:
            response = await http.patch(name, params={"updateMask": "endpointUri,endpointAuthorization,subscriberConfigs"},
                                        json=body)
        print(response.status_code, json.dumps({k: v for k, v in response.json().items() if k != "endpointAuthorization"}))
        return 0 if response.status_code < 300 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

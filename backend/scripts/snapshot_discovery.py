"""Snapshot the Google Health API discovery documents into the contract package.

    python -m scripts.snapshot_discovery            # refresh v4 and v4beta
    python -m scripts.snapshot_discovery --check    # exit 1 if Google's revision differs

The snapshot is the machine-readable contract the adapters and the data-type
registry are tested against (tests/test_google_health_contract.py). Refreshing
it is a deliberate change: review the diff, then update the registry.
"""
import argparse
import json
import sys
from pathlib import Path

import httpx

URL = "https://health.googleapis.com/$discovery/rest?version={version}"
TARGET = Path(__file__).resolve().parents[1] / "integrations" / "google_health" / "contract" / "discovery"
VERSIONS = ("v4", "v4beta")


def fetch(version: str) -> dict:
    response = httpx.get(URL.format(version=version), timeout=30)
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Compare revisions without writing")
    args = parser.parse_args()
    changed = False
    for version in VERSIONS:
        document = fetch(version)
        path = TARGET / f"{version}.json"
        current = json.loads(path.read_text()) if path.exists() else {}
        if current.get("revision") != document.get("revision"):
            changed = True
            print(f"{version}: revision {current.get('revision')} -> {document.get('revision')}")
        if not args.check:
            path.write_text(json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    sys.exit(main())

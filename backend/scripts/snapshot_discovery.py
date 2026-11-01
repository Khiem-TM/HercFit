"""Chụp lại tài liệu discovery của Google Health API vào package hợp đồng.

    python -m scripts.snapshot_discovery            # làm mới v4 và v4beta
    python -m scripts.snapshot_discovery --check    # thoát với mã 1 nếu revision của Google khác

Ảnh chụp là hợp đồng máy đọc được mà adapter và registry loại dữ liệu
được test đối chiếu (tests/test_google_health_contract.py). Làm mới
nó là một thay đổi có chủ đích: xem lại diff, rồi cập nhật registry.
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

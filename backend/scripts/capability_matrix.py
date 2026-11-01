"""Render the Google Health capability matrix from the registry.

    python -m scripts.capability_matrix > docs/google_health/capability_matrix.md
"""
from integrations.google_health.contract import scopes
from integrations.google_health.contract.registry import (
    DATA_TYPES, DISCOVERY_REVISION, FAMILIES, GUIDE_CHECKED_ON, Op, Verification,
)

COLUMNS = (Op.LIST, Op.RECONCILE, Op.ROLLUP, Op.DAILY_ROLLUP)


def main() -> None:
    print("# Google Health capability matrix\n")
    print(f"Generated from `integrations/google_health/contract/registry.py` (discovery revision "
          f"{DISCOVERY_REVISION}, guide checked {GUIDE_CHECKED_ON}). Do not edit by hand.\n")
    print("Legend: ✓ supported · W = create/patch/batchDelete · 🔔 webhook · ⚠ sensitive (no graph, "
          "assistant sees derived results only, with consent).\n")
    print("| Data type | Kind | Scope group | list | reconcile | rollUp | dailyRollUp | write | 🔔 | Lands in | "
          "Retention | Status |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for item in sorted(DATA_TYPES.values(), key=lambda spec: (spec.scope_group, spec.id)):
        marks = ["✓" if op in item.read_ops else "" for op in COLUMNS]
        status = item.verification.value
        if item.verification is not Verification.DOCUMENTED:
            status = f"**{status}**"
        name = f"`{item.id}`" + (" ⚠" if item.sensitivity.value == "sensitive" else "")
        if item.api_versions == ("v4beta",):
            name += " (v4beta)"
        print(f"| {name} | {item.kind.value} | {item.scope_group} | {' | '.join(marks)} | "
              f"{'W' if item.write_ops else ''} | {'🔔' if item.webhook else ''} | {item.family} | "
              f"{item.retention.value} | {status} |")
    print("\n## Notes\n")
    for item in sorted(DATA_TYPES.values(), key=lambda spec: spec.id):
        if item.notes:
            print(f"- `{item.id}`: {item.notes}")
    print("\n## Landing zones\n")
    for family, description in FAMILIES.items():
        print(f"- `{family}`: {description}")
    print("\n## Scope bundles (incremental authorization)\n")
    for bundle in scopes.BUNDLES.values():
        listed = ", ".join(f"`{scope.removeprefix(scopes.PREFIX)}`" for scope in bundle.scopes)
        print(f"- **{bundle.key}** ({bundle.label_vi}){' ⚠' if bundle.sensitive else ''}: {listed}")
    print("\nNever requested automatically (in discovery, not in the guide): "
          + ", ".join(f"`{scope.removeprefix(scopes.PREFIX)}`" for scope in sorted(scopes.DISCOVERY_ONLY)) + ".")
    print("Documented in the guide but absent from the discovery snapshot: "
          + ", ".join(f"`{scope.removeprefix(scopes.PREFIX)}`" for scope in sorted(scopes.GUIDE_ONLY)) + ".")


if __name__ == "__main__":
    main()

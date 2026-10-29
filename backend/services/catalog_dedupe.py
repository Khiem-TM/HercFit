"""Merge duplicate SYSTEM catalog foods without losing provenance.

Rows are grouped by accented name (case-insensitive), item type and nutrient basis (serving unit and size).
Inside a group:

* identical nutrients are exact duplicates: one row is kept;
* different nutrients that stay close (energy within 25 %, protein within 50 %) are measurement
  samples of one dish (for example the same dish sampled in several provinces): the real sample
  closest to the median energy is kept and the other samples are listed on it;
* energies further apart but the same composition (protein per kcal within 50 %, carbohydrate and
  fat energy shares within 15 points) are one recipe served in different portion sizes: the
  median sample is kept and the energy range of the samples is recorded on it;
* anything else is reported as a conflict and left untouched for manual review, unless the caller
  opts in with ``merge_conflicts``: then the median sample becomes the typical value ("typical")
  and the energy range is recorded, trading per-recipe accuracy for one entry per dish name.

Merged rows are deactivated (hidden from search), never deleted. Each records ``merged_into`` and
a ``merge_batch`` so ``revert`` can restore them. Meal plan items are repointed to the kept row;
logged meals are immutable snapshots and keep their original food_id.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

from sqlalchemy import text

from services.catalog_search import accented

NUTRIENTS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g")
SAMPLE_ENERGY_RATIO = 1.25
SAMPLE_PROTEIN_RATIO = 1.5
COMPOSITION_PROTEIN_RATIO = 1.5
COMPOSITION_SHARE_POINTS = 0.15
TOLERANCE = 0.05


@dataclass(frozen=True)
class FoodRow:
    id: str
    code: str | None
    name: str
    key: tuple
    nutrients: dict[str, float | None]
    has_image: bool = False
    created_at: datetime | None = None

    @property
    def filled(self) -> int:
        return sum(value is not None for value in self.nutrients.values())

    def preference(self):
        # Keep the row with an image, then the most complete one, then the oldest.
        return (not self.has_image, -self.filled, self.created_at or datetime.max, self.id)


@dataclass
class MergeGroup:
    canonical: FoodRow
    merged: list[FoodRow]
    reason: str  # "exact" | "sample" | "portion" | "typical"

    @property
    def energy_range(self):
        values = [row.nutrients["energy_kcal"] for row in (self.canonical, *self.merged) if row.nutrients["energy_kcal"]]
        return [min(values), max(values)] if values else None


@dataclass
class MergePlan:
    groups: list[MergeGroup] = field(default_factory=list)
    conflicts: list[list[FoodRow]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        def rows(reason):
            return sum(len(g.merged) for g in self.groups if g.reason == reason)
        return {
            "exact_groups": sum(g.reason == "exact" for g in self.groups), "exact_rows_merged": rows("exact"),
            "sample_groups": sum(g.reason == "sample" for g in self.groups), "sample_rows_merged": rows("sample"),
            "portion_groups": sum(g.reason == "portion" for g in self.groups), "portion_rows_merged": rows("portion"),
            "typical_groups": sum(g.reason == "typical" for g in self.groups), "typical_rows_merged": rows("typical"),
            "conflicting_groups": len(self.conflicts),
            "conflict_examples": sorted({group[0].name for group in self.conflicts})[:15],
        }


def _identical(a: FoodRow, b: FoodRow) -> bool:
    for name in NUTRIENTS:
        left, right = a.nutrients[name], b.nutrients[name]
        if (left is None) != (right is None) or (left is not None and abs(left - right) > TOLERANCE):
            return False
    return True


def _close(rows: list[FoodRow]) -> bool:
    energies = [row.nutrients["energy_kcal"] for row in rows]
    proteins = [row.nutrients["protein_g"] for row in rows]
    if any(value is None or value <= 0 for value in energies):
        return False
    if max(energies) / min(energies) > SAMPLE_ENERGY_RATIO:
        return False
    if all(value is not None and value > 0 for value in proteins):
        return max(proteins) / min(proteins) <= SAMPLE_PROTEIN_RATIO
    return all(value is None for value in proteins)


def _same_composition(rows: list[FoodRow]) -> bool:
    """One recipe at different portion sizes: energy differs, the make-up of that energy does not."""
    energies = [row.nutrients["energy_kcal"] for row in rows]
    if any(value is None or value <= 0 for value in energies):
        return False
    densities = [(row.nutrients["protein_g"] or 0) / row.nutrients["energy_kcal"] for row in rows]
    if min(densities) <= 0 or max(densities) / min(densities) > COMPOSITION_PROTEIN_RATIO:
        return False
    for nutrient, kcal_per_g in (("carbohydrate_g", 4), ("fat_g", 9)):
        values = [row.nutrients[nutrient] for row in rows]
        if all(value is not None for value in values):
            shares = [value * kcal_per_g / row.nutrients["energy_kcal"] for value, row in zip(values, rows)]
            if max(shares) - min(shares) > COMPOSITION_SHARE_POINTS:
                return False
    return True


def plan_merges(rows: list[FoodRow], merge_conflicts: bool = False) -> MergePlan:
    plan = MergePlan()
    groups: dict[tuple, list[FoodRow]] = {}
    for row in rows:
        groups.setdefault(row.key, []).append(row)
    for members in groups.values():
        if len(members) < 2:
            continue
        # 1. Exact duplicates collapse into one representative per nutrient profile.
        clusters: list[list[FoodRow]] = []
        for row in sorted(members, key=FoodRow.preference):
            for cluster in clusters:
                if _identical(cluster[0], row):
                    cluster.append(row)
                    break
            else:
                clusters.append([row])
        representatives = []
        for cluster in clusters:
            if len(cluster) > 1:
                plan.groups.append(MergeGroup(cluster[0], cluster[1:], "exact"))
            representatives.append(cluster[0])
        if len(representatives) < 2:
            continue
        # 2. Samples of one dish keep the real sample nearest the median energy.
        reason = ("sample" if _close(representatives) else "portion" if _same_composition(representatives)
                  else "typical" if merge_conflicts and all(r.nutrients["energy_kcal"] for r in representatives) else None)
        if reason:
            middle = median(row.nutrients["energy_kcal"] for row in representatives)
            canonical = min(representatives, key=lambda row: (abs(row.nutrients["energy_kcal"] - middle), row.preference()))
            plan.groups.append(MergeGroup(canonical, [row for row in representatives if row is not canonical], reason))
        else:
            plan.conflicts.append(representatives)
    # Exact clusters whose representative is later merged as a sample point at the final row.
    final = {row.id: group.canonical for group in plan.groups if group.reason != "exact" for row in group.merged}
    for group in plan.groups:
        if group.reason == "exact" and group.canonical.id in final:
            group.canonical = final[group.canonical.id]
    return plan


async def load_rows(session, name: str | None = None) -> list[FoodRow]:
    result = await session.execute(text(
        "SELECT id::text, code, name_vi, normalized_name_vi, item_type::text, serving_unit::text, serving_size, "
        + ", ".join(NUTRIENTS) + ", image_url IS NOT NULL AS has_image, created_at FROM foods "
        "WHERE source_type = 'SYSTEM' AND is_active"
        + (" AND normalized_name_vi = :name" if name else "")), {"name": name} if name else {})
    rows = []
    for r in result.mappings():
        size = round(float(r["serving_size"]), 4) if r["serving_size"] is not None else None
        rows.append(FoodRow(
            id=r["id"], code=r["code"], name=r["name_vi"],
            # Accents distinguish dishes ("Bánh gio" vs "Bánh giò"): group by the accented name.
            key=(accented(r["name_vi"] or ""), r["item_type"], r["serving_unit"], size),
            nutrients={n: (float(r[n]) if r[n] is not None else None) for n in NUTRIENTS},
            has_image=r["has_image"], created_at=r["created_at"]))
    return rows


async def referenced_meal_items(session, plan: MergePlan) -> int:
    ids = [row.id for group in plan.groups for row in group.merged]
    if not ids:
        return 0
    return (await session.execute(text("SELECT count(*) FROM meal_items WHERE food_id::text = ANY(:ids)"),
                                  {"ids": ids})).scalar_one()


async def apply_plan(session, plan: MergePlan) -> dict[str, Any]:
    batch = str(uuid.uuid4())
    repointed_total = aliases_total = 0
    by_canonical: dict[str, dict[str, Any]] = {}
    for group in plan.groups:
        entry = by_canonical.setdefault(group.canonical.id, {"merged_from": [], "aliases": [], "range": None})
        if group.reason in ("portion", "typical"):
            entry["range"] = group.energy_range
        for row in group.merged:
            repointed = (await session.execute(text(
                "UPDATE meal_plan_items SET food_id = CAST(:canonical AS uuid), updated_at = now() "
                "WHERE food_id = CAST(:merged AS uuid) RETURNING id::text"),
                {"canonical": group.canonical.id, "merged": row.id})).scalars().all()
            aliases = (await session.execute(text(
                "INSERT INTO foods_aliases (entity_id, normalized_alias) SELECT CAST(:canonical AS uuid), normalized_alias "
                "FROM foods_aliases WHERE entity_id = CAST(:merged AS uuid) ON CONFLICT DO NOTHING RETURNING normalized_alias"),
                {"canonical": group.canonical.id, "merged": row.id})).scalars().all()
            await session.execute(text(
                "UPDATE foods SET is_active = false, updated_at = now(), version_id = version_id + 1, "
                "data_quality = COALESCE(data_quality, '{}'::jsonb) || jsonb_build_object('merged_into', CAST(:canonical AS text), "
                "'merge_reason', CAST(:reason AS text), 'merge_batch', CAST(:batch AS text), "
                "'repointed_plan_items', CAST(:repointed AS jsonb)) WHERE id = CAST(:merged AS uuid)"),
                {"canonical": group.canonical.id, "reason": group.reason, "batch": batch, "merged": row.id,
                 "repointed": json.dumps(repointed)})
            entry["merged_from"].append({"id": row.id, "code": row.code, "reason": group.reason, **row.nutrients})
            entry["aliases"].extend(aliases)
            repointed_total += len(repointed)
            aliases_total += len(aliases)
    for canonical, entry in by_canonical.items():
        await session.execute(text(
            "UPDATE foods SET updated_at = now(), version_id = version_id + 1, "
            "data_quality = COALESCE(data_quality, '{}'::jsonb) || jsonb_build_object('merge_batch', CAST(:batch AS text), "
            "'merged_from', CAST(:merged AS jsonb), 'merged_aliases', CAST(:aliases AS jsonb), "
            "'portion_energy_range_kcal', CAST(:range AS jsonb)) WHERE id = CAST(:id AS uuid)"),
            {"batch": batch, "id": canonical, "merged": json.dumps(entry["merged_from"], ensure_ascii=False),
             "aliases": json.dumps(entry["aliases"], ensure_ascii=False), "range": json.dumps(entry["range"])})
    return {"batch": batch, "rows_deactivated": sum(len(g.merged) for g in plan.groups),
            "plan_items_repointed": repointed_total, "aliases_copied": aliases_total}


async def revert(session, batch: str | None = None) -> dict[str, Any]:
    """Undo one merge batch (or every batch when ``batch`` is None)."""
    scope = "data_quality->>'merge_batch' = :batch" if batch else "data_quality ? 'merge_batch'"
    params = {"batch": batch} if batch else {}
    merged = (await session.execute(text(
        f"SELECT id::text, data_quality->'repointed_plan_items' AS items FROM foods WHERE {scope} AND data_quality ? 'merged_into'"),
        params)).mappings().all()
    for row in merged:
        items = row["items"] or []
        if items:
            await session.execute(text(
                "UPDATE meal_plan_items SET food_id = CAST(:id AS uuid), updated_at = now() WHERE id::text = ANY(:items)"),
                {"id": row["id"], "items": items})
    restored = await session.execute(text(
        f"UPDATE foods SET is_active = true, updated_at = now(), version_id = version_id + 1, "
        f"data_quality = data_quality - 'merged_into' - 'merge_reason' - 'merge_batch' - 'repointed_plan_items' "
        f"WHERE {scope} AND data_quality ? 'merged_into'"), params)
    canonicals = (await session.execute(text(
        f"SELECT id::text, data_quality->'merged_aliases' AS aliases FROM foods WHERE {scope} AND data_quality ? 'merged_from'"),
        params)).mappings().all()
    for row in canonicals:
        if row["aliases"]:
            await session.execute(text(
                "DELETE FROM foods_aliases WHERE entity_id = CAST(:id AS uuid) AND normalized_alias = ANY(:aliases)"),
                {"id": row["id"], "aliases": row["aliases"]})
    await session.execute(text(
        f"UPDATE foods SET updated_at = now(), version_id = version_id + 1, "
        f"data_quality = data_quality - 'merged_from' - 'merged_aliases' - 'merge_batch' - 'portion_energy_range_kcal' "
        f"WHERE {scope} AND data_quality ? 'merged_from'"), params)
    return {"rows_restored": restored.rowcount, "canonicals_cleared": len(canonicals)}

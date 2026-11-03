"""Gộp các thực phẩm SYSTEM trùng nhau trong catalog mà không mất nguồn gốc.

Các dòng được gom theo tên có dấu (không phân biệt hoa thường), loại món và căn cứ dinh dưỡng (đơn vị và cỡ khẩu phần).
Trong một nhóm:

* dinh dưỡng giống hệt là bản trùng hoàn toàn: giữ một dòng;
* dinh dưỡng khác nhưng gần nhau (năng lượng lệch trong 25 %, protein trong 50 %) là các mẫu
  đo của một món (ví dụ cùng món được lấy mẫu ở nhiều tỉnh): giữ mẫu thật
  gần trung vị năng lượng nhất và liệt kê các mẫu khác trên nó;
* năng lượng xa nhau hơn nhưng cùng thành phần (protein trên kcal lệch trong 50 %, tỉ lệ năng lượng
  carb và chất béo lệch trong 15 điểm) là một công thức phục vụ ở các cỡ khẩu phần khác nhau: giữ
  mẫu trung vị và ghi khoảng năng lượng của các mẫu lên nó;
* mọi trường hợp khác được báo là xung đột và để nguyên cho xem xét thủ công, trừ khi bên gọi
  chọn ``merge_conflicts``: khi đó mẫu trung vị trở thành giá trị điển hình ("typical")
  và khoảng năng lượng được ghi lại, đánh đổi độ chính xác theo công thức để mỗi tên món chỉ có một mục.

Các dòng đã gộp bị vô hiệu hoá (ẩn khỏi tìm kiếm), không bao giờ bị xoá. Mỗi dòng ghi ``merged_into`` và
một ``merge_batch`` để ``revert`` có thể khôi phục. Các mục trong kế hoạch bữa ăn được trỏ lại dòng được giữ;
bữa ăn đã ghi là ảnh chụp bất biến và giữ food_id gốc.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

from sqlalchemy import text

from domains.catalog.services.catalog_search import accented

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
        # Giữ dòng có ảnh, rồi dòng đầy đủ nhất, rồi dòng cũ nhất.
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
    """Một công thức ở các cỡ khẩu phần khác nhau: năng lượng khác, cấu thành của năng lượng đó thì không."""
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
        # 1. Bản trùng hoàn toàn gộp thành một đại diện cho mỗi hồ sơ dinh dưỡng.
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
        # 2. Các mẫu của một món giữ mẫu thật gần trung vị năng lượng nhất.
        reason = ("sample" if _close(representatives) else "portion" if _same_composition(representatives)
                  else "typical" if merge_conflicts and all(r.nutrients["energy_kcal"] for r in representatives) else None)
        if reason:
            middle = median(row.nutrients["energy_kcal"] for row in representatives)
            canonical = min(representatives, key=lambda row: (abs(row.nutrients["energy_kcal"] - middle), row.preference()))
            plan.groups.append(MergeGroup(canonical, [row for row in representatives if row is not canonical], reason))
        else:
            plan.conflicts.append(representatives)
    # Các cụm trùng hoàn toàn mà đại diện sau đó được gộp như một mẫu thì trỏ tới dòng cuối cùng.
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
            # Dấu phân biệt các món ("Bánh gio" với "Bánh giò"): gom nhóm theo tên có dấu.
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
    aliases_total = 0
    by_canonical: dict[str, dict[str, Any]] = {}
    for group in plan.groups:
        entry = by_canonical.setdefault(group.canonical.id, {"merged_from": [], "aliases": [], "range": None})
        if group.reason in ("portion", "typical"):
            entry["range"] = group.energy_range
        for row in group.merged:
            aliases = (await session.execute(text(
                "INSERT INTO foods_aliases (entity_id, normalized_alias) SELECT CAST(:canonical AS uuid), normalized_alias "
                "FROM foods_aliases WHERE entity_id = CAST(:merged AS uuid) ON CONFLICT DO NOTHING RETURNING normalized_alias"),
                {"canonical": group.canonical.id, "merged": row.id})).scalars().all()
            await session.execute(text(
                "UPDATE foods SET is_active = false, updated_at = now(), version_id = version_id + 1, "
                "data_quality = COALESCE(data_quality, '{}'::jsonb) || jsonb_build_object('merged_into', CAST(:canonical AS text), "
                "'merge_reason', CAST(:reason AS text), 'merge_batch', CAST(:batch AS text)) WHERE id = CAST(:merged AS uuid)"),
                {"canonical": group.canonical.id, "reason": group.reason, "batch": batch, "merged": row.id})
            entry["merged_from"].append({"id": row.id, "code": row.code, "reason": group.reason, **row.nutrients})
            entry["aliases"].extend(aliases)
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
            "aliases_copied": aliases_total}


async def revert(session, batch: str | None = None) -> dict[str, Any]:
    """Hoàn tác một lô gộp (hoặc mọi lô khi ``batch`` là None)."""
    scope = "data_quality->>'merge_batch' = :batch" if batch else "data_quality ? 'merge_batch'"
    params = {"batch": batch} if batch else {}
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

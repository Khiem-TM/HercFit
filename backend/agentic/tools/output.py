import json

FOOD_FIELDS = ('id', 'code', 'name_vi', 'name_en', 'category_vi', 'item_type', 'source_type', 'serving_size', 'serving_unit',
               'energy_kcal', 'protein_g', 'carbohydrate_g', 'fat_g', 'fiber_g', 'portions', 'portion_weight_g', 'image_url')
EXERCISE_FIELDS = ('id', 'code', 'name_vi', 'name_en', 'kind', 'source_type', 'muscle_groups', 'equipment', 'configuration', 'image_url')
CATALOG_LIMIT = 20
CARRY_ITEM_CHARS = 4000
CARRY_TOTAL_CHARS = 16000


def nutrition_basis(unit, size):
    """Spell out what the nutrient values refer to, so replies never guess per-100 g vs per-portion."""
    if unit == 'PORTION':
        return 'mỗi suất'
    try:
        amount = f'{float(size):g}'
    except (TypeError, ValueError):
        amount = '1'
    return {'G': f'mỗi {amount} g', 'ML': f'mỗi {amount} ml'}.get(unit, f'mỗi {amount} khẩu phần')


def _project(record, fields):
    if not isinstance(record, dict):
        return record
    projected = {key: record[key] for key in fields if key in record}
    if fields is FOOD_FIELDS and record.get('serving_unit'):
        projected['nutrition_basis'] = nutrition_basis(record.get('serving_unit'), record.get('serving_size'))
    quality = record.get('data_quality')
    if fields is FOOD_FIELDS and isinstance(quality, dict) and quality.get('portion_energy_range_kcal'):
        # Merged samples of one dish at different portion sizes: lets replies say "tuỳ cỡ suất".
        projected['portion_energy_range_kcal'] = quality['portion_energy_range_kcal']
    return projected


def compact_output(tool: str, data):
    """Structure-preserving projection of catalog results; other outputs pass through."""
    fields = FOOD_FIELDS if tool.endswith('_foods') else EXERCISE_FIELDS if tool.endswith('_exercises') else None
    if fields is None:
        return data
    if isinstance(data, list):
        items = [_project(record, fields) for record in data[:CATALOG_LIMIT]]
        return items if len(data) <= CATALOG_LIMIT else items + [{'truncated': len(data) - CATALOG_LIMIT}]
    if isinstance(data, dict) and isinstance(data.get('record'), dict):
        return {**data, 'record': _project(data['record'], fields)}
    return _project(data, fields) if isinstance(data, dict) and 'name_vi' in data else data


def clamp_catalog_query(tool: str, args: dict) -> dict:
    if tool in {'list_foods', 'list_exercises'} and (args.get('limit') or CATALOG_LIMIT) > CATALOG_LIMIT:
        return {**args, 'limit': CATALOG_LIMIT}
    return args


def carry_over(outputs: list[dict]) -> str | None:
    """Bounded summary of the previous turn's tool results for the next turn."""
    parts, used = [], 0
    for output in reversed(outputs):
        text = json.dumps({**output, 'output': compact_output(output.get('tool', ''), output.get('output'))}, ensure_ascii=False, default=str)
        if len(text) > CARRY_ITEM_CHARS:
            text = text[:CARRY_ITEM_CHARS] + '…(rút gọn)'
        if used + len(text) > CARRY_TOTAL_CHARS:
            break
        parts.append(text)
        used += len(text)
    return '[' + ','.join(reversed(parts)) + ']' if parts else None


def bounded_json(value, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + '…(rút gọn do quá dài)'

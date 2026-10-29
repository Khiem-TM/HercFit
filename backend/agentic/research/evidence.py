"""Field-level evidence policy for researched catalog payloads.

A verbatim quote proves that a source says something, not that every payload value
came from it. Each value HercFit computes with (nutrients and serving basis, MET,
muscle groups, activity, equipment...) must be backed by a claim for that field
path whose quote contains the number, or a term of the enum value. The research
agent clears unsupported values to null/default before preview; the finalization
API rejects a payload that still carries one.
"""
import copy
import json
import re

from agentic.research.quotes import NUMBER, canon, number_values, quoted_numbers
from agentic.research.sources import allows

MUSCLE_TERMS = {
    'CHEST': (r'chest', r'pec', r'ngực'),
    'BACK': (r'back\b', r'lats?\b', r'latissimus', r'traps?\b', r'trapezius', r'rhomboid', r'erector', r'lưng', r'cơ xô'),
    'SHOULDERS': (r'shoulder', r'delt', r'vai'),
    'BICEPS': (r'bicep', r'tay trước', r'nhị đầu'),
    'TRICEPS': (r'tricep', r'tay sau', r'tam đầu'),
    'FOREARMS': (r'forearm', r'grip\b', r'cẳng tay'),
    'QUADS': (r'quad', r'đùi trước', r'tứ đầu'),
    'HAMSTRINGS': (r'hamstring', r'đùi sau', r'gân kheo'),
    'GLUTES': (r'glute', r'mông'),
    'CALVES': (r'calf\b', r'calves', r'gastrocnemius', r'soleus', r'bắp chân', r'bắp chuối'),
    'CORE': (r'core\b', r'abs\b', r'abdominal', r'oblique', r'trunk', r'bụng', r'cơ lõi'),
    'FULL_BODY': (r'full[ -]body', r'total[ -]body', r'whole[ -]body', r'toàn thân'),
}
EQUIPMENT_TERMS = {
    'BARBELL': (r'barbell', r'tạ đòn', r'thanh đòn'),
    'DUMBBELL': (r'dumbbell', r'tạ đơn', r'tạ tay'),
    'MACHINE': (r'machine', r'máy'),
    'CABLE': (r'cable', r'pulley', r'cáp', r'ròng rọc'),
    'BODYWEIGHT': (r'body[ -]?weight', r'no equipment', r'trọng lượng cơ thể', r'không cần dụng cụ'),
    'KETTLEBELL': (r'kettlebell', r'tạ ấm'),
    'BAND': (r'band', r'dây kháng lực', r'dây đàn hồi'),
}
ACTIVITY_TERMS = {
    'RUN': (r'run', r'jog', r'sprint', r'chạy'),
    'WALK': (r'walk', r'đi bộ'),
    'HIKE': (r'hik', r'trek', r'leo núi', r'đi bộ đường dài'),
    'CYCLE': (r'cycl', r'bik', r'bicycl', r'đạp xe'),
    'SWIM': (r'swim', r'bơi'),
    'ROW': (r'row', r'chèo'),
}
ENVIRONMENT_TERMS = {
    'ROAD': (r'road', r'đường phố', r'đường nhựa'),
    'TRACK': (r'track', r'đường chạy', r'sân vận động'),
    'TRAIL': (r'trail', r'địa hình', r'đường mòn'),
    'TREADMILL': (r'treadmill', r'máy chạy'),
    'INDOOR': (r'indoor', r'trong nhà'),
    'OPEN_WATER': (r'open[ -]water', r'nước mở', r'biển'),
}
CATEGORY_TERMS = {
    'COMPOUND': (r'compound', r'multi[ -]?joint', r'đa khớp', r'nhiều khớp', r'phức hợp'),
    'ISOLATION': (r'isolat', r'single[ -]?joint', r'đơn khớp', r'cô lập'),
}
UNILATERAL_TERMS = (r'unilateral', r'single[ -]?(?:leg|arm)', r'one[ -]?(?:leg|arm)', r'(?:một|từng) (?:chân|tay|bên)')
UNIT_TERMS = {'G': r'\d[\d.,]*\s*(?:g|gr|grams?|gam)\b', 'ML': r'\d[\d.,]*\s*(?:ml|milli-?lit(?:er|re)s?)\b'}

NUTRIENTS = ('energy_kcal', 'protein_g', 'carbohydrate_g', 'fat_g', 'fiber_g')
DEFAULT_LOAD_MODES = ['EXTERNAL', 'BODYWEIGHT', 'ASSISTED']
NAME_FIELDS = ('name_vi', 'name_en')
REQUIRED_CLAIMS = {'foods': ('name_vi',), 'exercises': ('name_vi', 'kind')}


def _quotes(claims, fields, scope=None, url_of=None):
    return [c.quote for c in claims if c.field in fields
            and (scope is None or allows(c.source_id, url_of(c.source_id), scope))]


def _has_term(quotes, patterns):
    text = '\n'.join(canon(q) for q in quotes)
    return any(re.search(r'(?<!\w)' + pattern, text) for pattern in patterns)


def _number_ok(value, quotes):
    try:
        return value is not None and float(value) in quoted_numbers(quotes)
    except (TypeError, ValueError):
        return False


def _numbers_ok(value, quotes):
    # Every numeral of a free-form value must be quoted; a value without numerals needs a claim.
    available = quoted_numbers(quotes)
    return bool(quotes) and all(number_values(n) & available for n in NUMBER.findall(json.dumps(value, ensure_ascii=False)))


def _term_ok(value, table, quotes):
    """An enum value is supported by one of its terms; free text by appearing in a quote."""
    patterns = table.get(str(value).upper())
    if patterns is None:
        patterns = next((terms for terms in table.values() if _has_term([str(value)], terms)), None)
    if patterns is not None:
        return _has_term(quotes, patterns)
    return bool(quotes) and canon(str(value)) in '\n'.join(canon(q) for q in quotes)


def _keep(values, path, table, quotes, cleared):
    kept = [value for value in values or [] if _term_ok(value, table, quotes)]
    if len(kept) != len(values or []):
        cleared.append(path)
    return kept


def _set(data, key, value, path, cleared, derived=False):
    """Replace an unsupported value; derived values are recomputed, not reported as cleared."""
    if data.get(key) != value:
        if not derived:
            cleared.append(path)
        data[key] = value


def _foods(data, claims, missing, cleared):
    for field in (*NUTRIENTS, 'portion_weight_g'):
        if data.get(field) is not None and not _number_ok(data[field], _quotes(claims, (field,))):
            _set(data, field, None, field, cleared)
    serving = _quotes(claims, ('serving_size',))
    if data.get('serving_size') is not None:
        if not _number_ok(data['serving_size'], serving):
            _set(data, 'serving_size', None, 'serving_size', cleared)
        elif data.get('serving_unit', 'G') in UNIT_TERMS and not _has_term(serving, (UNIT_TERMS[data.get('serving_unit', 'G')],)):
            missing.append('serving_unit')
    if any(data.get(f) is not None for f in NUTRIENTS) and data.get('serving_size') is None and data.get('serving_unit') != 'PORTION':
        missing.append('serving_size')
    portions = data.get('portions') or []
    supported = [p for p in portions if _number_ok(p.get('quantity'), _quotes(claims, ('portions',)))]
    if len(supported) != len(portions):
        _set(data, 'portions', supported, 'portions', cleared)
    info = data.get('nutrition_information') or {}
    kept = {key: value for key, value in info.items()
            if _numbers_ok(value, _quotes(claims, ('nutrition_information.' + key, 'nutrition_information')))}
    if kept != info:
        _set(data, 'nutrition_information', kept, 'nutrition_information', cleared)


def _met(config, claims, url_of, cleared):
    met = _quotes(claims, ('configuration.default_met',), scope='met', url_of=url_of)
    if config.get('default_met') is not None and not _number_ok(config['default_met'], met):
        _set(config, 'default_met', None, 'configuration.default_met', cleared)
    if 'met_source' in config or config.get('kind') in {'SPORT', 'ENDURANCE'}:
        # The citation of a MET value is the registry source that supports it, never model text.
        source = None
        if config.get('default_met') is not None:
            source = next((url_of(c.source_id) or c.source_id for c in claims if c.field == 'configuration.default_met'
                           and allows(c.source_id, url_of(c.source_id), 'met')
                           and _number_ok(config['default_met'], [c.quote])), None)
        _set(config, 'met_source', source, 'configuration.met_source', cleared, derived=True)


def _exercises(data, claims, url_of, missing, cleared):
    named = NAME_FIELDS + ('instructions',)
    data['muscle_groups'] = _keep(data.get('muscle_groups'), 'muscle_groups', MUSCLE_TERMS, _quotes(claims, ('muscle_groups',)), cleared)
    equipment_quotes = _quotes(claims, ('equipment', 'configuration.equipment_type'))
    data['equipment'] = _keep(data.get('equipment'), 'equipment', EQUIPMENT_TERMS, equipment_quotes, cleared)
    if data.get('instructions') and not _quotes(claims, ('instructions',)):
        _set(data, 'instructions', None, 'instructions', cleared)
    config = data.get('configuration') or {}
    kind = config.get('kind')
    if kind == 'STRENGTH':
        if not _term_ok(config.get('category', 'COMPOUND'), CATEGORY_TERMS, _quotes(claims, ('configuration.category',))):
            _set(config, 'category', 'COMPOUND', 'configuration.category', cleared)
        if config.get('equipment_type', 'OTHER') != 'OTHER' and not _term_ok(config['equipment_type'], EQUIPMENT_TERMS, equipment_quotes):
            _set(config, 'equipment_type', 'OTHER', 'configuration.equipment_type', cleared)
        config['secondary_muscles'] = _keep(config.get('secondary_muscles'), 'configuration.secondary_muscles', MUSCLE_TERMS,
                                            _quotes(claims, ('configuration.secondary_muscles', 'muscle_groups')), cleared)
        if config.get('unilateral') and not _has_term(_quotes(claims, ('configuration.unilateral',) + named), UNILATERAL_TERMS):
            _set(config, 'unilateral', False, 'configuration.unilateral', cleared)
        if config.get('movement_pattern') and not _quotes(claims, ('configuration.movement_pattern',)):
            _set(config, 'movement_pattern', None, 'configuration.movement_pattern', cleared)
        # Derived from category, and the load modes are HercFit's logging options, not research facts.
        _set(config, 'e1rm_eligible', config.get('category', 'COMPOUND') == 'COMPOUND', 'configuration.e1rm_eligible', cleared, derived=True)
        _set(config, 'supported_load_modes', list(DEFAULT_LOAD_MODES), 'configuration.supported_load_modes', cleared, derived=True)
    elif kind == 'SPORT':
        if not _quotes(claims, ('configuration.sport', 'kind') + NAME_FIELDS):
            missing.append('configuration.sport')
    elif kind == 'ENDURANCE':
        if config.get('activity', 'OTHER') != 'OTHER' and not _term_ok(
                config['activity'], ACTIVITY_TERMS, _quotes(claims, ('configuration.activity', 'kind') + NAME_FIELDS)):
            _set(config, 'activity', 'OTHER', 'configuration.activity', cleared)
        if config.get('environment') and not _term_ok(
                config['environment'], ENVIRONMENT_TERMS, _quotes(claims, ('configuration.environment',) + named)):
            _set(config, 'environment', None, 'configuration.environment', cleared)
        if config.get('terrain') and not _quotes(claims, ('configuration.terrain',)):
            _set(config, 'terrain', None, 'configuration.terrain', cleared)
    _met(config, claims, url_of, cleared)
    data['configuration'] = config


def audit(domain, payload, claims, url_of=lambda source_id: ''):
    """(payload, missing, cleared). Unsupported values are cleared to null/default and their
    paths listed in cleared; required values without evidence are listed in missing.
    An audited payload is a fixed point: auditing it again changes nothing."""
    data = copy.deepcopy(payload)
    missing, cleared = [], []
    fields = {claim.field for claim in claims}
    missing.extend(field for field in REQUIRED_CLAIMS[domain] if field not in fields)
    if domain == 'foods':
        _foods(data, claims, missing, cleared)
    else:
        _exercises(data, claims, url_of, missing, cleared)
    return data, missing, cleared

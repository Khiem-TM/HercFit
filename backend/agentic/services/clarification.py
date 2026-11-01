"""Turn a needs_input reply into standard card frames, one per missing field; never a free-text box.

Frames (`ClarifyQuestion.mode`) are answered on the card: a choice (single, quick_reply, multiple), a number
with its unit and plausible range, or the per-exercise sets editor. The model only drafts questions, labels,
values and number ranges; code validates every frame. Catalog identity and images are copied from records
that tools returned in this turn, so an option can never point to an invented food/exercise or image. A
question that asks the user to pick records ("những bài nào trong danh sách?") gets the records the reply
listed as options from code when the model left it without any; the "số hiệp × reps × mức tạ" question after
it becomes the sets editor. When the model fails, the questions of the reply are framed by code the same way.

A question no frame fits (a name, a free description) stays in the reply for the chat box, and a reply with
nothing to frame gets no form at all: a summary or a courtesy line never reaches the user as a question (run
433a847a: two nutrition summary lines became two "Tự nhập" questions after the meal was already saved).
"""
from agentic.prompts.registry import get_prompt
import json
import logging
import math
import re
import unicodedata
from typing import Literal

from langchain_core.messages import SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from agentic.core.app.schemas.response import NUMBER_UNITS, Clarification
from domains.catalog.models.foods import normalize_food_text

logger = logging.getLogger(__name__)
PROMPT = get_prompt('clarification.form', 'v3')
QUESTION_LIMIT = 8
OPTION_LIMIT = 12  # ClarifyQuestion.options
PRESET_LIMIT = 6  # NumberFrame.presets


# No length limits on drafts: one over-long label or a seventh option used to fail validation and
# discard the whole form. Sizes are clipped when the form is built.
class OptionDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str
    description: str | None = None
    value: str
    ref_id: str | None = Field(default=None, description='Catalog id copied from the provided list, if the option is a catalog item')


class QuestionDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str
    question: str
    # 'text': the answer is a name or a free description; it is left in the reply for the chat box, never put on the card.
    mode: Literal['single', 'multiple', 'quick_reply', 'number', 'text']
    options: list[OptionDraft] = Field(default_factory=list, description=f'At most {OPTION_LIMIT}')
    unit: str | None = Field(default=None, description='number: one of ' + ', '.join(NUMBER_UNITS))
    min: float | None = None
    max: float | None = None
    step: float | None = None
    default: float | None = None
    presets: list[float] = Field(default_factory=list, description=f'number: at most {PRESET_LIMIT} common values')
    max_select: int = 1
    required: bool = True


class ClarificationDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intro: str | None = None
    questions: list[QuestionDraft] = Field(default_factory=list, description=f'At most {QUESTION_LIMIT}')


def catalog_groups(state) -> list[dict]:
    """Catalog records (foods/exercises) of each successful tool call in this turn, with the call's search text."""
    groups = []
    for output in (state or {}).get('tool_outputs', []):
        tool = output.get('tool') or ''
        if not output.get('ok') or not tool.endswith(('_foods', '_exercises')):
            continue
        data = output.get('output')
        records = data if isinstance(data, list) else (data.get('items') or data.get('candidates') or data.get('matches') or [data]) if isinstance(data, dict) else []
        kind = 'food' if tool.endswith('_foods') else 'exercise'
        items = [{'id': str(record['id']), 'name': record['name_vi'], 'name_en': record.get('name_en'),
                  'image_url': record.get('image_url'), 'kind': kind, 'exercise_kind': record.get('kind') if kind == 'exercise' else None}
                 for record in records if isinstance(record, dict) and record.get('id') and record.get('name_vi')]
        if items:
            query = ' '.join(value for value in (output.get('arguments') or {}).values() if isinstance(value, str))
            groups.append({'query': query, 'records': items})
    return groups


def catalog_index(state) -> dict[str, dict]:
    """Catalog records returned by successful tool calls in this turn, by id."""
    return {record['id']: record for group in catalog_groups(state) for record in group['records']}


ITEM = re.compile(r'^\s*(?:\d+[.)]|[-*•])\s+(.+)$')
# "những bài nào", "món gì", "loại nào", "trong danh sách" (accents stripped): the user picks catalog records.
PICK = re.compile(r'\b(?:bai|mon|dong tac|loai|bien the)(?: tap| an)? (?:nao|gi)\b|\b(?:trong|tu) (?:danh sach|catalog)\b')
PLURAL = re.compile(r'\b(?:nhung|cac)\b')
# "số hiệp × reps × mức tạ": the performance of each strength exercise.
SETS = re.compile(r'\b(?:hiep|sets?|reps?|muc ta)\b')
# Labels that name the topic, not an exercise ("Chi tiết từng bài", "Câu 2").
GENERIC_LABEL = re.compile(r'^(?:chi tiet|cau \d|tra loi|thong tin|bai tap|so hiep|khoi luong|rpe)')
COMMON = {'ban', 'nao', 'nay', 'cua', 'cho', 'trong', 'nhung', 'cac', 'khong', 'hay', 'voi', 'mot', 'sach', 'danh'}

# A value asked by its unit (accents stripped): the label for a bare "Câu 2", the unit, range, step and presets.
# "mấy giờ" asks a time of day, not a duration, so it is no number frame.
NUMBER_HINTS = (
    (re.compile(r'\b(?:can nang|nang bao nhieu|bao nhieu (?:kg|ky|can)|may (?:kg|ky|can))\b'), 'Cân nặng', 'kg', 30, 250, 0.1, ()),
    (re.compile(r'\b(?:chieu cao|cao bao nhieu|bao nhieu cm)\b'), 'Chiều cao', 'cm', 100, 230, 1, ()),
    (re.compile(r'\b(?:ty le mo|phan tram mo|body ?fat|bao nhieu % mo)\b'), 'Tỉ lệ mỡ', '%', 3, 60, 0.5, ()),
    (re.compile(r'\b(?:thoi luong|keo dai|may phut|bao nhieu phut|tap (?:trong )?bao lau)\b'), 'Thời lượng', 'phút', 5, 300, 5, (30, 45, 60, 90)),
    (re.compile(r'\b(?:may tieng|bao nhieu tieng|bao nhieu gio|ngu bao lau)\b'), 'Số giờ', 'giờ', 0.5, 16, 0.5, (1, 2, 7, 8)),
    (re.compile(r'\b(?:bao nhieu km|may km|quang duong|cu ly)\b'), 'Quãng đường', 'km', 0.5, 100, 0.1, (3, 5, 10)),
    (re.compile(r'\b(?:bao nhieu buoi|may buoi|so buoi)\b'), 'Số buổi', 'buổi', 1, 14, 1, (2, 3, 4, 5)),
    (re.compile(r'\b(?:bao nhieu (?:suat|phan)|may (?:suat|phan))\b'), 'Khẩu phần', 'suất', 0.25, 10, 0.25, (0.5, 1, 1.5, 2)),
    (re.compile(r'\b(?:bao nhieu qua|may qua)\b'), 'Số quả', 'quả', 1, 20, 1, (1, 2, 3)),
    (re.compile(r'\b(?:bao nhieu (?:ly|coc)|may (?:ly|coc))\b'), 'Số ly', 'ly', 0.5, 10, 0.5, (1, 2)),
    (re.compile(r'\b(?:bao nhieu (?:to|bat)|may (?:to|bat))\b'), 'Số tô', 'tô', 0.5, 5, 0.5, (1, 2)),
    (re.compile(r'\b(?:bao nhieu (?:gram|gam|g)|may (?:gram|gam))\b'), 'Khối lượng', 'g', 5, 2000, 5, (50, 100, 200)),
    (re.compile(r'\bbao nhieu ml\b'), 'Thể tích', 'ml', 50, 3000, 50, (250, 330, 500)),
    (re.compile(r'\b(?:bao nhieu (?:kcal|calo|calories)|nang luong)\b'), 'Năng lượng', 'kcal', 0, 5000, 10, ()),
    (re.compile(r'\b(?:nhip tim|bpm)\b'), 'Nhịp tim', 'bpm', 30, 220, 1, ()),
    (re.compile(r'\b(?:bao nhieu tuoi|may tuoi)\b'), 'Tuổi', 'tuổi', 10, 100, 1, ()),
    (re.compile(r'\brpe\b'), 'RPE', 'RPE', 1, 10, 0.5, (6, 7, 8, 9)),
    (re.compile(r'\b(?:bao nhieu tuan|may tuan)\b'), 'Số tuần', 'tuần', 1, 52, 1, (4, 8, 12)),
    (re.compile(r'\b(?:bao nhieu ngay|may ngay)\b'), 'Số ngày', 'ngày', 1, 365, 1, ()),
    (re.compile(r'\b(?:bao nhieu buoc|so buoc)\b'), 'Số bước', 'bước', 0, 50000, 500, (5000, 8000, 10000)),
)
# Units the model may name, folded to the canonical ones of NumberFrame.
UNIT_ALIASES = {
    'kilogram': 'kg', 'kgs': 'kg', 'ky': 'kg', 'can': 'kg', 'gram': 'g', 'gam': 'g', 'grams': 'g', 'gr': 'g',
    'mililit': 'ml', 'mililiter': 'ml', 'calo': 'kcal', 'cal': 'kcal', 'calories': 'kcal', 'kilocalories': 'kcal',
    'min': 'phút', 'mins': 'phút', 'minute': 'phút', 'minutes': 'phút', 'p': 'phút', 'tieng': 'giờ', 'h': 'giờ',
    'hour': 'giờ', 'hours': 'giờ', 'kilomet': 'km', 'centimet': 'cm', 'phan tram': '%', 'percent': '%',
    'nhip/phut': 'bpm', 'set': 'hiệp', 'sets': 'hiệp', 'rep': 'reps', 'session': 'buổi', 'sessions': 'buổi',
    'day': 'ngày', 'days': 'ngày', 'week': 'tuần', 'weeks': 'tuần', 'serving': 'suất', 'servings': 'suất',
    'trai': 'quả', 'chiec': 'cái', 'steps': 'bước', 'age': 'tuổi', 'nam tuoi': 'tuổi',
}
CANONICAL_UNITS = {normalize_food_text(unit): unit for unit in NUMBER_UNITS} | {key: value for key, value in UNIT_ALIASES.items()}
# "Năng lượng: ... kcal", "Protein: ___ g": a value to fill in, unlike "Phở bò tái: 1 suất → 431.7 kcal".
BLANK = re.compile(r'^(?P<label>[^:?]{1,60}):\s*(?:\.{2,}|…|_{2,})\s*(?P<unit>[^\s?.…_]{1,12})?\s*\??$')
WEEKDAYS = re.compile(r'\b(?:ngay nao trong tuan|thu may|nhung ngay(?: cu the)? nao|ngay tap|t2\s*[-,/]\s*t)')
WEEKDAY_OPTIONS = ('Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật')
# "nhẹ / vừa / mạnh", "tăng cơ, giảm mỡ hay kết hợp": the reply already names the choices.
SLASHED = re.compile(r'^[^?/]{1,40}(?:\s*/\s*[^?/]{1,40}){1,5}$')
OR_LIST = re.compile(r'\s*,\s*(?:hay|hoặc)\s+|\s*,\s*|\s+(?:hay|hoặc)\s+')


def plain(text: str) -> str:
    return re.sub(r'\*\*|__|`|^\s*#+\s*', '', text).strip()


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r'\w+', normalize_food_text(text)) if len(w) > 2}


def fold(text: str) -> str:
    """Lowercase with accents kept: "tạ đòn" (barbell) and "tạ đơn" (dumbbell) are different records."""
    return ' '.join(unicodedata.normalize('NFC', text).lower().split())


def position(text: str, record: dict) -> int:
    """Where the record's name first appears in the folded reply, or -1."""
    found = [text.find(fold(name)) for name in (record['name'], record.get('name_en')) if name]
    return min((index for index in found if index >= 0), default=-1)


def catalog_option(record: dict) -> dict:
    return {'id': record['id'], 'label': clip(record['name'], 120),
            'description': clip(record['name_en'], 200) if record.get('name_en') else None,
            'image_url': record.get('image_url'), 'ref': {'kind': record['kind'], 'id': record['id']},
            'value': clip(record['name'], 300)}


def text_option(question_id: str, index: int, label: str) -> dict:
    label = clip(label[:1].upper() + label[1:], 120)
    return {'id': f'{question_id}-opt-{index}', 'label': label, 'description': None, 'image_url': None, 'ref': None, 'value': label}


def canonical_unit(unit: str | None) -> str | None:
    key = normalize_food_text(unit or '').strip(' .')
    return CANONICAL_UNITS.get(key)


def number_frame(unit, low=None, high=None, step=None, default=None, presets=()) -> dict | None:
    """A NumberFrame within the unit's plausible range, or None for a unit the card cannot ask in."""
    unit = canonical_unit(unit)
    if unit is None:
        return None
    floor, ceiling, base = NUMBER_UNITS[unit]
    low = floor if low is None else min(max(floor, low), ceiling)
    high = ceiling if high is None else max(min(ceiling, high), floor)
    if low >= high:
        low, high = floor, ceiling
    step = step if step and 0 < step <= high - low else base
    # The stepper moves on multiples of the step: 0.25..24 h by 1 h starts at 1 h, not at 0.25 → 1.25 → 2.25.
    aligned = round(math.ceil(round(low / step, 9)) * step, 6)
    if aligned >= high:  # no multiple of the step inside the range: the unit's own range
        low, high, step = floor, ceiling, base
        aligned = round(math.ceil(round(low / step, 9)) * step, 6)
    low = aligned
    values = sorted({value for value in presets or () if low <= value <= high})[:PRESET_LIMIT]
    return {'unit': unit, 'min': low, 'max': high, 'step': step,
            'default': default if default is not None and low <= default <= high else None, 'presets': values}


def catalog_choices(groups: list[dict], reply: str, taken: set[str], listed_only: bool = False) -> list[dict]:
    """Records of the groups not offered yet; the ones the reply listed, in the reply's order, when there are any."""
    records = {}
    for group in groups:
        for record in group['records']:
            if record['id'] not in taken:
                records.setdefault(record['id'], record)
    text = fold(reply)
    found = {key: position(text, record) for key, record in records.items()}
    listed = sorted((key for key in records if found[key] >= 0), key=found.get)
    return [records[key] for key in (listed if listed_only else listed or records)][:OPTION_LIMIT]


def with_catalog_options(questions: list[dict], groups: list[dict], reply: str) -> list[dict]:
    """Give a pick question the catalog records it asks about: all of them when the model left it without options,
    the other records the reply listed when the model offered only some (seen: one option out of twelve)."""
    taken = {option['id'] for question in questions for option in question.get('options') or [] if option.get('ref')}
    # A search that matched one record already identified it; several matches are the open choice.
    pool = [group for group in groups if len(group['records']) > 1] or groups
    result = []
    for question in questions:
        mode, options = question.get('mode'), question.get('options') or []
        if not pool or mode in {'quick_reply', 'number', 'sets'} or (options and not any(option.get('ref') for option in options)):
            result.append(question)
            continue
        text = normalize_food_text(question['label'] + ' ' + question['question'])
        words = _words(text) - COMMON
        related = [group for group in pool if words & _words(group['query'] + ' ' + ' '.join(r['name'] for r in group['records']))]
        if options:
            records = catalog_choices(related or pool, reply, taken, listed_only=True)[:OPTION_LIMIT - len(options)]
        elif PICK.search(text) or (related and mode in {'single', 'multiple'}):
            records = catalog_choices(related or pool, reply, taken)
        else:
            records = []
        if not records:
            result.append(question)
            continue
        taken.update(record['id'] for record in records)
        merged = [*options, *(catalog_option(record) for record in records)]
        multiple = mode == 'multiple' or (mode != 'single' and bool(PLURAL.search(text)))
        result.append({**question, 'mode': 'multiple' if multiple else 'single', 'options': merged,
                       'min_select': 1, 'max_select': len(merged) if multiple else 1})
    return result


def logs_training(state) -> bool:
    """This turn logs a training session (its first routing decision), so strength picks need their sets."""
    return 'LOG_EXERCISE' in {((state or {}).get('turn') or {}).get('intent'), ((state or {}).get('decision') or {}).get('intent')}


def sets_question(question_id: str, sources: list[str] | None = None, rows: list[dict] | None = None, base: dict | None = None) -> dict:
    return {'id': question_id, 'label': 'Chi tiết từng bài', 'question': 'Số hiệp × reps × mức tạ của từng bài?',
            'required': True, 'min_select': 1, 'max_select': 1,
            **(base or {}), 'mode': 'sets', 'for_questions': sources or [], 'options': rows or [], 'number': None}


def with_sets_editor(questions: list[dict], groups: list[dict], reply: str, training_log: bool = False) -> list[dict]:
    """Sets × reps × load is asked with the per-exercise editor, one row per exercise the user picks.

    An open sets question follows the earlier exercise picks; with none, the strength exercises looked up this turn
    become a (code-owned) pick just before it. Open sets questions naming one exercise each merge into one editor.
    When a training log picks strength exercises and asks no sets at all, the editor is added after the picks: the
    log cannot be written without them.
    """
    text = fold(reply)
    strength = {record['id']: record for group in groups for record in group['records'] if record.get('exercise_kind') == 'STRENGTH'}
    # The ones the reply listed first, in its order, then the rest of the lookups (the reply may only give examples).
    candidates = sorted(strength.values(), key=lambda record: (position(text, record) < 0, max(position(text, record), 0)))
    result, picks, named, has_sets = [], [], [], False
    for question in questions:
        asks_sets = question['mode'] == 'text' and SETS.search(normalize_food_text(question['label'] + ' ' + question['question']))
        if question['mode'] in {'single', 'multiple'} and any((o.get('ref') or {}).get('kind') == 'exercise' for o in question['options']):
            picks.append(question['id'])  # e.g. one pick per muscle group
        elif asks_sets and not picks and not candidates and not GENERIC_LABEL.match(normalize_food_text(question['label'])):
            named.append(question)  # "Đẩy ngực máy: số hiệp × reps @ tạ?", one per exercise, no lookup this turn
            if len(named) > 1:
                continue
        elif asks_sets:
            if not picks and len(candidates) > 1:
                options = [catalog_option(record) for record in candidates[:OPTION_LIMIT]]
                result.append({'id': 'exercises', 'label': 'Bài tập đã tập', 'question': 'Bạn đã tập những bài nào?', 'mode': 'multiple',
                               'options': options, 'required': True, 'min_select': 1, 'max_select': len(options)})
                picks.append('exercises')
            if picks:
                question = sets_question(question['id'], picks, base=question)
            elif candidates:
                question = sets_question(question['id'], rows=[catalog_option(candidates[0])], base=question)
            has_sets = True
        result.append(question)
    if named:
        rows = [{'id': f'row-{i + 1}', 'label': q['label'], 'description': None, 'image_url': None, 'ref': None, 'value': q['label']}
                for i, q in enumerate(named[:OPTION_LIMIT])]
        result[result.index(named[0])] = sets_question(named[0]['id'], rows=rows)
        has_sets = True
    picked_strength = [q['id'] for q in result if q['id'] in picks and any(o['id'] in strength for o in q['options'])]
    if training_log and picked_strength and not has_sets:
        last = max(i for i, q in enumerate(result) if q['id'] in picked_strength)
        result.insert(last + 1, sets_question('sets', picks))
    return result[:QUESTION_LIMIT]


def settled(question: dict) -> dict:
    """Choices with their selection bounds; a choice without choices is open until a frame is found for it."""
    options = question.get('options') or []
    mode = question.get('mode', 'text')
    if mode not in {'single', 'multiple', 'quick_reply'}:
        return question
    if not options:
        return {**question, 'mode': 'text', 'options': []}
    if mode == 'multiple' and len(options) < 2:
        mode = 'single'  # one record is a one-tap pick
    limit = question.get('max_select') or 1
    max_select = min(limit if limit > 1 else len(options), len(options)) if mode == 'multiple' else 1
    return {**question, 'mode': mode, 'options': options, 'min_select': 1, 'max_select': max(1, max_select)}


def choice_like(part: str) -> bool:
    return (len(part.split()) <= 5 and not normalize_food_text(part).startswith('ban ') and bool(re.search(r'[^\W\d_]', part))
            and part.count('(') == part.count(')'))


def listed_choices(question_id: str, text: str) -> list[dict]:
    """Options the question itself names: "nhẹ / vừa / mạnh?", or after a label "tăng cơ, giảm mỡ hay kết hợp?"."""
    asked = plain(text).split('?')[0].strip(' :.*')
    if SLASHED.match(asked):
        parts = [part.strip(' *.') for part in asked.split('/')]
    elif re.search(r'\s(?:hay|hoặc)\s', asked) and ',' in asked:
        parts = [part.strip(' *.') for part in OR_LIST.split(asked)]
    else:
        return []
    parts = [part for part in parts if part]
    # Short worded choices only: "Bạn muốn ăn cơm/phở" is a sentence, "(01/11/2026)" a date, not options.
    if not 2 <= len(parts) <= 6 or not all(choice_like(part) for part in parts):
        return []
    return [text_option(question_id, index + 1, part) for index, part in enumerate(parts)]


def reply_choices(question: dict, reply: str) -> list[dict]:
    """Choices the reply listed for this question ("- Cường độ: nhẹ / vừa / mạnh?") when the draft left them out."""
    words = _words(question['label'] + ' ' + question['question']) - COMMON
    for line in (reply or '').splitlines():
        text = plain(line)
        if '?' not in text:
            continue  # a summary line ("Phở bò tái + trứng luộc — 14:37 (01/11/2026)") lists no choices
        item = ITEM.match(text)
        label, _, rest = (item.group(1) if item else text).partition(':')
        # Every word of the line's topic is in the question: "Level hiện tại" is not "tập tại nhà" for sharing "tại".
        named = _words(label) - COMMON
        if rest.strip() and named and named <= words:
            options = listed_choices(question['id'], rest)
            if options:
                return options
    return []


def framed(question: dict, reply: str = '') -> dict | None:
    """The card frame of a question, or None when its answer is a name or a description (left for the chat box)."""
    if question.get('mode') != 'text':
        return question
    asked = normalize_food_text(question['label'] + ' ' + question['question'])
    base = {key: value for key, value in question.items() if key != 'unit'}
    base.update(options=[], min_select=1, max_select=1, number=None)
    if question.get('unit') and canonical_unit(question['unit']):
        return {**base, 'mode': 'number', 'number': number_frame(question['unit'])}
    for pattern, label, unit, low, high, step, presets in NUMBER_HINTS:
        if pattern.search(asked):
            named = {'label': label} if re.match(r'^Câu \d+$', question['label']) else {}
            return {**base, **named, 'mode': 'number', 'number': number_frame(unit, low, high, step, None, presets)}
    if WEEKDAYS.search(asked):
        options = [text_option(question['id'], index + 1, day) for index, day in enumerate(WEEKDAY_OPTIONS)]
        return {**base, 'mode': 'multiple', 'options': options, 'max_select': len(options)}
    options = listed_choices(question['id'], question['question']) or reply_choices(question, reply)
    if options:
        return {**base, 'mode': 'single', 'options': options}
    return None


def to_form(questions: list[dict], groups: list[dict], reply: str, training_log: bool, intro: str | None) -> dict | None:
    """Validated card frames for the drafted questions, or None when no question fits a frame."""
    questions = [settled(question) for question in with_catalog_options(questions[:QUESTION_LIMIT], groups, reply)]
    questions = with_sets_editor(questions, groups, reply, training_log)
    frames = [frame for frame in (framed(question, reply) for question in questions) if frame]
    if len(frames) < len(questions):
        logger.info('clarification_open_questions count=%s', len(questions) - len(frames))
        # The reply asks something the card cannot: the bubble keeps the whole reply instead of a short intro.
        intro = None
    return Clarification.sanitize({'intro': clip(intro, 300) if intro else None, 'questions': frames})


def split_reply(reply: str) -> tuple[list[str], list[str], list[str]]:
    """(lead paragraphs, listed items, paragraphs after the last item) of a reply, markup removed."""
    lead, items, tail = [], [], []
    for line in (reply or '').splitlines():
        text = plain(line)
        match = ITEM.match(text)
        if match:
            items.append(match.group(1).strip())
            tail = []  # only the paragraph after the last item can be a closing question
        elif text:
            (tail if items else lead).append(text)
    return lead, items, tail


def intro_of(reply: str) -> str | None:
    """The paragraph before a list of questions: the bubble shows it while the form holds the questions."""
    lead, items, _ = split_reply(reply)
    return clip(' '.join(lead), 300) if lead and any('?' in item or BLANK.match(item) for item in items) else None


def fallback_clarification(reply: str, groups: list[dict] | None = None, training_log: bool = False) -> dict | None:
    """Frames for the reply's questions, without a model call; None when the reply asks nothing a card can hold."""
    _, items, tail = split_reply(reply)
    # Only questions are questions: listed records, sub-details and summaries (a meal's nutrition lines) are not;
    # a blank to fill in ("Năng lượng: ... kcal") is.
    asked = [text for text in items if '?' in text or BLANK.match(text)]
    questions = []
    for text in asked:
        blank = BLANK.match(text)
        if blank:
            label = blank['label'].strip()
            questions.append({'id': f'q{len(questions) + 1}', 'label': label, 'question': f'{label} là bao nhiêu?', 'mode': 'text',
                              'unit': blank['unit']})
            continue
        label, _, rest = text.partition(':')
        if not rest.strip() or len(label) > 60:
            label, rest = f'Câu {len(questions) + 1}', text
        rest = rest.strip()
        # "Mục tiêu chính: tăng cơ, giảm mỡ…?" reads as its own sentence on the card.
        questions.append({'id': f'q{len(questions) + 1}', 'label': label.strip(), 'question': clip(rest[:1].upper() + rest[1:], 300),
                          'mode': 'text'})
    closing = ' '.join(tail)
    if questions and '?' in closing and re.search(r'\b(?:ngoai ra|neu co|tuy chon)\b', normalize_food_text(closing)):
        # A closing "ngoài ra ...?" paragraph after the list is an optional extra question.
        questions.append({'id': f'q{len(questions) + 1}', 'label': 'Thông tin thêm', 'question': clip(closing, 300),
                          'mode': 'text', 'required': False})
    if not questions:
        # The sentences that ask, not the start of a long summary.
        for sentence in (plain(part) for part in re.findall(r'[^.!?\n]*\?', reply or '')):
            if sentence:
                questions.append({'id': f'q{len(questions) + 1}', 'label': f'Câu {len(questions) + 1}',
                                  'question': clip(sentence, 300), 'mode': 'text'})
    strength = any(record.get('exercise_kind') == 'STRENGTH' for group in groups or [] for record in group['records'])
    if not questions and strength and SETS.search(normalize_food_text(reply or '')):
        # "Bạn ghi giúp từng bài: số hiệp × reps × mức tạ." asks without a question mark: the sets editor.
        questions.append({'id': 'q1', 'label': 'Chi tiết từng bài', 'question': 'Số hiệp × reps × mức tạ của từng bài?', 'mode': 'text'})
    return to_form(questions, groups or [], reply or '', training_log, intro_of(reply))


def asks(reply: str) -> bool:
    """Whether the reply asks anything: a question mark or a numbered/bulleted item."""
    return '?' in (reply or '') or any(ITEM.match(line) for line in (reply or '').splitlines())


def grounded(question: dict, reply: str) -> bool:
    """A drafted question must come from the reply: most of its words appear there."""
    words = _words(question['label'] + ' ' + question['question'])
    return not words or len(words & _words(reply)) / len(words) >= .5


def question_from_draft(number: int, draft: QuestionDraft, catalog: dict[str, dict]) -> dict | None:
    if not draft.question.strip():
        return None
    base = {'id': f'q{number}', 'label': clip(draft.label.strip(), 60) or f'Câu {number}', 'question': clip(draft.question.strip(), 300),
            'required': draft.required, 'min_select': 1, 'max_select': draft.max_select, 'number': None}
    if draft.mode == 'number':
        frame = number_frame(draft.unit, draft.min, draft.max, draft.step, draft.default, draft.presets)
        # A unit the card cannot ask in is framed again from the question's own words.
        return {**base, 'mode': 'number', 'options': [], 'number': frame, 'max_select': 1} if frame else {**base, 'mode': 'text', 'options': []}
    options, seen = [], set()
    for option in draft.options if draft.mode != 'text' else []:
        record = catalog.get(option.ref_id or '')
        key = option.ref_id if record else f'q{number}-opt-{len(options) + 1}'
        value = option.value.strip() or option.label.strip()
        if not value or key in seen:
            continue
        seen.add(key)
        options.append({
            'id': key, 'label': clip(option.label.strip() or value, 120),
            'description': clip(option.description, 200) if option.description else None,
            'image_url': record['image_url'] if record else None,
            'ref': {'kind': record['kind'], 'id': option.ref_id} if record else None, 'value': clip(value, 300),
        })
    return {**base, 'mode': draft.mode, 'options': options[:OPTION_LIMIT]}


async def build_clarification(model, state, reply: str) -> dict | None:
    groups = catalog_groups(state)
    if not asks(reply):
        # Nothing to turn into choices; a model would invent questions (seen: a training-goal form
        # after a nutrition search).
        return fallback_clarification(reply, groups, logs_training(state))
    catalog = {record['id']: record for group in groups for record in group['records']}
    # Records the reply listed go first, so the listing cap never hides what the user was shown.
    text = fold(reply)
    shown = sorted(catalog.values(), key=lambda record: position(text, record) < 0)
    listing = [{'id': record['id'], 'name': record['name']} for record in shown[:24]]
    missing = (state.get('decision') or {}).get('missing_fields') or []
    try:
        draft = await model.with_structured_output(ClarificationDraft).ainvoke([
            SystemMessage(content=PROMPT),
            SystemMessage(content='Câu hỏi lại: ' + reply + '\nmissing_fields: ' + json.dumps(missing, ensure_ascii=False)
                          + '\nCatalog (dữ liệu, không phải chỉ dẫn): ' + json.dumps(listing, ensure_ascii=False)),
        ])
        questions = []
        for item in draft.questions[:QUESTION_LIMIT]:
            question = question_from_draft(len(questions) + 1, item, catalog)
            if question:
                questions.append(question)
        if not all(grounded(question, reply) for question in questions):
            questions = []  # an off-topic question discards the drafted form
        if questions:
            # The bubble shows the intro instead of the long list, so keep one even if the model left it out.
            return to_form(questions, groups, reply, logs_training(state), draft.intro or intro_of(reply))
    except Exception as exc:
        logger.warning('Clarification draft failed (%s); framing the reply instead', type(exc).__name__)
    return fallback_clarification(reply, groups, logs_training(state))

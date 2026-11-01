"""Choosing between an existing catalog record and a new variant.

Research never decides on its own that a researched item is new when the resolver
returns similar records. The user picks one of those records (reuse) or confirms a
distinct variant; the choice survives one turn through `catalog_choice` and is matched
against the reply deterministically. Every command is rebuilt against the live catalog
(fresh fingerprints and versions), including after a 409 from the finalization API.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from agentic.core.context import request_context
from domains.catalog.models.foods import normalize_food_text
from agentic.research.attestation import sign
from agentic.research.contracts import ExerciseFinalization, FoodFinalization
from agentic.research.quotes import canon, number_values
from agentic.research.sources import TIER_RANK, rate
from domains.catalog.schemas.foods import FoodCreate

FINALIZATIONS = {'foods': FoodFinalization, 'exercises': ExerciseFinalization}
# "400-700 kcal", "380 calo", "khoảng 250 Calories": a value or a range with an energy unit.
ENERGY = re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:(?:-|–|—|đến|tới)\s*(\d+(?:[.,]\d+)?)\s*)?(?:kcal|calo(?:ries?)?|cal)\b', re.I)
# A question or a rumour is not an estimate ("có thật ... 1600 kcal không vậy").
QUESTION = re.compile(r'\?|\b(?:co that|co phai|bao nhieu|khong vay|khong nhi|phai khong)\b')
TIER_LABEL = {'primary': 'Nguồn chính thống', 'professional': 'Nguồn chuyên môn', 'secondary': 'Báo, nguồn tham khảo',
              'unknown': 'Chưa kiểm chứng'}
MAX_ESTIMATES = 4
NOUN = {'foods': 'món', 'exercises': 'bài tập'}
MAX_REVISIONS = 5
MAX_OPTIONS = 5


async def lookups(domain, query, name):
    """Resolver results for the research query and the candidate's own name, as the API re-checks both."""
    ctx = request_context.get()
    found = await ctx.backend.call('resolve_' + domain, {'query': query}, ctx.token)
    named = found if not name or normalize_food_text(name) == normalize_food_text(query) else \
        await ctx.backend.call('resolve_' + domain, {'query': name}, ctx.token)
    return {'query': found, 'name': named}


def merged(found):
    matches = {}
    for match in [*found['query']['matches'], *(found.get('name') or {'matches': []})['matches']]:
        matches.setdefault(match['id'], match)
    return sorted(matches.values(), key=lambda m: (not m.get('exact'), m.get('source_type') != 'CUSTOM'))


def name_taken(found):
    return any(m.get('exact') for m in (found.get('name') or {'matches': []})['matches'])


def settle(found, resolution, existing_id=None):
    """(resolution, existing record) the live catalog still allows for a choice, or (None, None) to ask again."""
    matches = {m['id']: m for m in merged(found)}
    if not matches:
        return 'create', None
    if resolution == 'reuse' and str(existing_id) in matches:
        return 'reuse', matches[str(existing_id)]
    if resolution == 'create_distinct' and not name_taken(found):
        return 'create_distinct', None
    return None, None


def attest(candidate, owner_id, secret):
    """Sign the immutable research content once; resolution fields stay outside the signature."""
    command = FINALIZATIONS[candidate['domain']].model_validate({
        'candidate_id': candidate['research_id'], 'candidate_revision': 1, 'query': candidate['query'],
        'payload': candidate['payload'], 'evidence': candidate['evidence'], 'sources': candidate['sources'],
        'expected_match_fingerprint': '0' * 64, 'expected_name_fingerprint': '0' * 64}).model_dump(mode='json')
    return sign(secret, owner_id, candidate['domain'], command,
                datetime.now(timezone.utc).replace(microsecond=0).isoformat())


def command(candidate, resolution, found, existing=None):
    """The next revision of the finalization command; the signed research content is reused unchanged."""
    query, payload = candidate['query'], candidate['payload']
    # A distinct variant cannot take over a query that already names another record.
    query_named = any(m.get('exact') for m in found['query']['matches'])
    alias = (normalize_food_text(query) != normalize_food_text(payload['name_vi']) and resolution != 'reuse'
             and not (resolution == 'create_distinct' and query_named))
    return {'candidate_id': candidate['research_id'], 'candidate_revision': candidate.get('candidate_revision', 0) + 1,
            'query': query, 'payload': payload, 'aliases': [query] if alias else [],
            'evidence': candidate['evidence'], 'sources': candidate['sources'], 'resolution': resolution,
            'expected_match_fingerprint': found['query']['fingerprint'],
            'expected_name_fingerprint': found['name']['fingerprint'],
            'existing_id': existing['id'] if existing else None,
            'expected_existing_version': existing['version_id'] if existing else None,
            'attestation': candidate['attestation']}


def revise(candidate, resolution, found, existing=None):
    finalization = command(candidate, resolution, found, existing)
    return {**candidate, 'candidate_revision': finalization['candidate_revision'], 'finalization': finalization,
            'resolution': resolution, 'existing': existing and {k: existing.get(k) for k in ('id', 'name_vi', 'name_en', 'source_type')},
            'choice': None}


def form(domain, query, found, candidate=None):
    """(clarification, catalog_choice): one single-choice question over the similar records."""
    noun = NOUN[domain]
    matches = merged(found)[:MAX_OPTIONS]
    options, choices, seen = [], {}, set()
    for match in matches:
        value = f'Dùng {noun} có sẵn: {match["name_vi"]}'
        if canon(value) in seen:
            value += f' ({match.get("name_en") or match["id"][:8]})'
        seen.add(canon(value))
        description = 'Bản ghi hệ thống' if match.get('source_type') == 'SYSTEM' else 'Bản ghi của bạn'
        options.append({'id': match['id'], 'label': match['name_vi'] + (f' ({match["name_en"]})' if match.get('name_en') else ''),
                        'description': description, 'ref': {'kind': 'food' if domain == 'foods' else 'exercise', 'id': match['id']},
                        'value': value})
        choices[canon(value)] = {'kind': 'reuse' if candidate else 'use', 'id': match['id'], 'name_vi': match['name_vi']}
    # The same name as an existing record is not a distinct variant: reuse it, or describe the difference.
    if not (candidate and name_taken(found)):
        value = f'Tạo {noun} mới, khác các bản đã có: {query}'
        options.append({'id': 'create_distinct', 'label': f'Tạo {noun} mới khác các bản trên',
                        'description': 'Thêm biến thể riêng vào catalog của bạn sau khi xác nhận', 'value': value})
        choices[canon(value)] = {'kind': 'create_distinct'}
    question = (f'Catalog đã có {noun} giống hoặc gần giống "{query}". Bạn muốn dùng bản nào?' if matches
                else f'Bạn muốn tạo {noun} "{query}" mới?')
    clarification = {'intro': f'HercFit tìm thấy {noun} tương tự "{query}" trong catalog.', 'questions': [{
        'id': 'q1', 'label': 'Chọn bản ghi', 'question': question, 'mode': 'single', 'options': options,
        'required': True, 'min_select': 1, 'max_select': 1}]}
    return clarification, {'domain': domain, 'query': query, 'choices': choices, 'candidate': candidate}


def carried(previous):
    """The previous turn's choice, only while its form is the one the user is answering."""
    choice = previous.get('catalog_choice')
    if previous.get('status') != 'needs_input' or not choice or not choice.get('choices'):
        return None
    offered = {canon(option['value']) for question in (previous.get('clarification') or {}).get('questions', [])
               for option in question.get('options', [])}
    return choice if set(choice['choices']) <= offered else None


def chosen(state, reply):
    choice = state.get('catalog_choice') or {}
    return choice.get('choices', {}).get(canon(reply))


def apply(state, option):
    """State update for a matched reply; None lets normal routing continue with the chosen record."""
    choice = state['catalog_choice']
    domain, candidate = choice['domain'], choice.get('candidate')
    if option['kind'] == 'use' or (option['kind'] == 'reuse' and not candidate):
        return None
    if option['kind'] == 'estimate':
        return {'catalog_choice': None, 'status': 'running', 'error': None, 'catalog_draft': estimate_draft(choice['query'], option),
                'decision': {'intent': 'catalog_estimate', 'action': 'tool', 'next_agent': 'tool', 'domain': domain,
                             'instruction': 'Tạo bản xem trước món CUSTOM theo ước tính người dùng chọn, sau đó tiếp tục yêu cầu gốc.'}}
    if candidate and option['kind'] in {'reuse', 'create_distinct'}:
        resolution = 'reuse' if option['kind'] == 'reuse' else 'create_distinct'
        return {'catalog_choice': None, 'status': 'running', 'error': None,
                'candidate': {**candidate, 'finalization': None, 'choice': {'resolution': resolution, 'existing_id': option.get('id')}},
                'decision': {'intent': 'catalog_choice', 'action': 'tool', 'next_agent': 'tool', 'domain': domain,
                             'instruction': 'Tạo bản xem trước lưu catalog theo lựa chọn của người dùng, sau đó tiếp tục yêu cầu gốc.'}}
    return {'catalog_choice': None, 'status': 'running', 'error': None, 'decision': {
        'intent': 'catalog_research', 'action': 'research', 'next_agent': 'research', 'domain': domain,
        'research_query': choice['query'], 'create_distinct': True,
        'instruction': f'Nghiên cứu biến thể mới "{choice["query"]}", phân biệt với các bản ghi có sẵn, sau đó tiếp tục yêu cầu gốc.'}}


def _number(raw):
    values = sorted(number_values(raw))
    value = values[-1] if values else None
    return int(value) if value is not None and value == int(value) else value


def _host(url):
    return (urlparse(url or '').hostname or '').removeprefix('www.') or url


def _clip(text, limit):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def estimate_form(target, claims, documents, product=None):
    """(clarification, catalog_choice) offering each sourced energy figure for the item, or a manual form.

    Each option is a number that appears in a verified quote about this item; the user, not the
    model, decides whether an estimate for another size or recipe fits what they ate."""
    from agentic.components.reranker import relevance
    found = []
    for claim in claims:
        if claim.field != 'energy_kcal':
            continue
        source = documents.get(claim.source_id) or {}
        # The quote itself must be about the item: "100 g avocado: 160 kcal" on a page about the drink is a part, not the drink.
        if QUESTION.search(normalize_food_text(claim.quote)) or relevance(target, claim.quote) < .5:
            continue
        url = source.get('url') or ''
        tier = rate(claim.source_id, url, product).tier
        for match in ENERGY.finditer(claim.quote):
            for raw in filter(None, match.groups()):
                value = _number(raw)
                if value and 0 < value <= 5000:
                    found.append({'kind': 'estimate', 'energy_kcal': value, 'quote': _clip(claim.quote, 300), 'url': url,
                                  'title': source.get('title') or '', 'authority': tier, 'applicable': claim.applicable})
    found.sort(key=lambda o: (TIER_RANK[o['authority']], not o['applicable']))
    options, choices, seen = [], {}, set()
    for option in found:
        if option['energy_kcal'] in seen or len(options) >= MAX_ESTIMATES:
            continue
        seen.add(option['energy_kcal'])
        number = f"{option['energy_kcal']:g}"
        value = f'Ghi {number} kcal cho món này (ước tính từ {_host(option["url"])})'
        options.append({'id': f'estimate-{len(options) + 1}', 'label': f'{number} kcal · {_host(option["url"])}',
                        'description': _clip(f'{TIER_LABEL[option["authority"]]}: “{option["quote"]}”', 200), 'value': value})
        choices[canon(value)] = option
    if not options:
        return manual_form('foods', target), None
    # Label values the user has instead of these estimates: the label form, behind its own option.
    label = manual_form('foods', target)['questions']
    options.append({'id': 'estimate-label', 'label': 'Nhập theo nhãn/app của hãng',
                    'description': 'Chọn khẩu phần, năng lượng và macro trên nhãn', 'value': LABEL_VALUE})
    clarification = {'intro': None, 'questions': [{
        'id': 'q1', 'label': 'Mức năng lượng', 'question': f'Bạn muốn ghi năng lượng cho "{target}" theo mức nào?',
        'mode': 'single', 'options': options, 'required': True, 'min_select': 1, 'max_select': 1},
        *({**question, 'id': 'label-' + question['id'], 'show_if': {'question': 'q1', 'option_ids': ['estimate-label']}}
          for question in label)]}
    return clarification, {'domain': 'foods', 'query': target, 'choices': choices, 'candidate': None}


LABEL_VALUE = 'Ghi theo số liệu trên nhãn/app của hãng'
FOOD_BASIS = (('basis-serving', '1 suất / ly / hộp', '1 suất (theo nhãn)'), ('basis-100g', '100 g', '100 g'),
              ('basis-100ml', '100 ml', '100 ml'))
EXERCISE_KINDS = (('kind-strength', 'Sức mạnh (tạ, máy, trọng lượng cơ thể)', 'Sức mạnh'),
                  ('kind-endurance', 'Sức bền (chạy, đạp xe, bơi, chèo)', 'Sức bền'),
                  ('kind-sport', 'Thể thao / vận động khác', 'Thể thao'))
MUSCLES = ('Ngực', 'Lưng', 'Vai', 'Tay trước', 'Tay sau', 'Đùi trước', 'Đùi sau', 'Mông', 'Bắp chân', 'Bụng / core', 'Toàn thân')
EQUIPMENT = ('Tạ đòn', 'Tạ đơn', 'Máy', 'Cáp', 'Trọng lượng cơ thể', 'Dây kháng lực', 'Không dùng dụng cụ')


def _choices(prefix, labels):
    return [{'id': f'{prefix}-{index + 1}', 'label': label, 'value': label} for index, label in enumerate(labels)]


def _nutrient(question_id, label, question, unit, high, step, required=False):
    return {'id': question_id, 'label': label, 'question': question, 'mode': 'number', 'options': [], 'required': required,
            'min_select': 1, 'max_select': 1, 'number': {'unit': unit, 'min': 0, 'max': high, 'step': step, 'default': None, 'presets': []}}


def manual_form(domain, target):
    """Card frames for the values a label, an app or the user can supply: numbers and choices, nothing typed."""
    if domain == 'foods':
        return {'intro': f'Bạn chọn số liệu dinh dưỡng của "{target}" theo nhãn hoặc app của hãng.', 'questions': [
            {'id': 'q1', 'label': 'Khẩu phần', 'question': f'Số liệu trên nhãn của "{target}" tính cho khẩu phần nào?',
             'mode': 'single', 'options': [{'id': key, 'label': label, 'value': value} for key, label, value in FOOD_BASIS],
             'required': True, 'min_select': 1, 'max_select': 1},
            _nutrient('q2', 'Năng lượng', 'Năng lượng của khẩu phần đó?', 'kcal', 5000, 5, required=True),
            _nutrient('q3', 'Protein', 'Protein (nếu nhãn có)?', 'g', 500, 0.5),
            _nutrient('q4', 'Carb', 'Carbohydrate (nếu nhãn có)?', 'g', 500, 0.5),
            _nutrient('q5', 'Fat', 'Chất béo (nếu nhãn có)?', 'g', 500, 0.5)]}
    strength = {'question': 'q1', 'option_ids': ['kind-strength']}
    return {'intro': f'Bạn chọn giúp thông tin bài tập "{target}".', 'questions': [
        {'id': 'q1', 'label': 'Loại bài', 'question': f'"{target}" thuộc loại bài nào?', 'mode': 'single',
         'options': [{'id': key, 'label': label, 'value': value} for key, label, value in EXERCISE_KINDS],
         'required': True, 'min_select': 1, 'max_select': 1},
        {'id': 'q2', 'label': 'Nhóm cơ chính', 'question': 'Bài tập tác động nhóm cơ chính nào?', 'mode': 'multiple',
         'options': _choices('muscle', MUSCLES), 'required': True, 'min_select': 1, 'max_select': 4, 'show_if': strength},
        {'id': 'q3', 'label': 'Dụng cụ', 'question': 'Bài tập dùng dụng cụ gì?', 'mode': 'single',
         'options': _choices('equipment', EQUIPMENT), 'required': True, 'min_select': 1, 'max_select': 1, 'show_if': strength}]}


def estimate_draft(target, option):
    """A CUSTOM food from the estimate the user chose: energy only, per serving (PORTION), with its basis."""
    name = target[:1].upper() + target[1:]
    payload = FoodCreate.model_validate({
        'name_vi': name, 'serving_unit': 'PORTION', 'energy_kcal': option['energy_kcal'],
        'data_quality': {'research': {'estimate': {k: option[k] for k in ('energy_kcal', 'quote', 'url', 'title', 'authority', 'applicable')},
                                      'selected_by_user': True,
                                      'unverified_fields': ['protein_g', 'carbohydrate_g', 'fat_g', 'fiber_g']}}}).model_dump(mode='json')
    return {'domain': 'foods', 'payload': payload, 'estimate': {k: option[k] for k in ('energy_kcal', 'url', 'title', 'authority', 'applicable')},
            'sources': [{'url': option['url'], 'title': option['title'], 'authority': option['authority']}] if option['url'] else []}

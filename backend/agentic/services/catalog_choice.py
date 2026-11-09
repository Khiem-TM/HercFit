"""Chọn giữa một bản ghi catalog có sẵn và một biến thể mới.

Tra cứu không bao giờ tự quyết rằng món đã tra cứu là mới khi bộ giải quyết
trả về các bản ghi tương tự. Người dùng chọn một trong các bản ghi đó (dùng lại) hoặc xác nhận
một biến thể riêng; lựa chọn được giữ qua một lượt trong `catalog_choice` và được so khớp
tất định với câu trả lời. Mỗi lệnh được dựng lại theo catalog hiện tại
(dấu vân tay và phiên bản mới), kể cả sau lỗi 409 từ API finalize.
"""
import re
from datetime import datetime, timezone

from agentic.core.context import request_context
from domains.catalog.models.foods import normalize_food_text
from agentic.research.attestation import sign
from agentic.research.contracts import ExerciseFinalization, FoodFinalization
from agentic.research.quotes import canon

FINALIZATIONS = {'foods': FoodFinalization, 'exercises': ExerciseFinalization}
# Một câu hỏi hay lời đồn không phải là ước tính ("có thật ... 1600 kcal không vậy").
QUESTION = re.compile(r'\?|\b(?:co that|co phai|bao nhieu|khong vay|khong nhi|phai khong)\b')
NOUN = {'foods': 'món', 'exercises': 'bài tập'}
MAX_REVISIONS = 5
MAX_OPTIONS = 5


async def lookups(domain, query, name):
    """Kết quả bộ giải quyết cho truy vấn tra cứu và cho chính tên của ứng viên, vì API kiểm tra lại cả hai."""
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
    """(resolution, bản ghi có sẵn) mà catalog hiện tại vẫn cho phép với một lựa chọn, hoặc (None, None) để hỏi lại."""
    matches = {m['id']: m for m in merged(found)}
    if not matches:
        return 'create', None
    if resolution == 'reuse' and str(existing_id) in matches:
        return 'reuse', matches[str(existing_id)]
    if resolution == 'create_distinct' and not name_taken(found):
        return 'create_distinct', None
    return None, None


def attest(candidate, owner_id, secret):
    """Ký nội dung tra cứu bất biến một lần; các trường resolution nằm ngoài chữ ký."""
    command = FINALIZATIONS[candidate['domain']].model_validate({
        'candidate_id': candidate['research_id'], 'candidate_revision': 1, 'query': candidate['query'],
        'payload': candidate['payload'], 'evidence': candidate['evidence'], 'sources': candidate['sources'],
        'expected_match_fingerprint': '0' * 64, 'expected_name_fingerprint': '0' * 64}).model_dump(mode='json')
    return sign(secret, owner_id, candidate['domain'], command,
                datetime.now(timezone.utc).replace(microsecond=0).isoformat())


def command(candidate, resolution, found, existing=None):
    """Bản sửa đổi tiếp theo của lệnh finalize; nội dung tra cứu đã ký được dùng lại nguyên vẹn."""
    query, payload = candidate['query'], candidate['payload']
    # Một biến thể riêng không được chiếm một truy vấn đã gọi tên bản ghi khác.
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
    """(clarification, catalog_choice): một câu hỏi chọn một trên các bản ghi tương tự."""
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
    # Trùng tên với bản ghi có sẵn thì không phải biến thể riêng: dùng lại nó, hoặc mô tả điểm khác biệt.
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
    """Lựa chọn của lượt trước, chỉ khi form của nó là form người dùng đang trả lời."""
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
    """Cập nhật state cho câu trả lời đã khớp; None để định tuyến bình thường tiếp tục với bản ghi đã chọn."""
    choice = state['catalog_choice']
    domain, candidate = choice['domain'], choice.get('candidate')
    if option['kind'] == 'use' or (option['kind'] == 'reuse' and not candidate):
        return None
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


EXERCISE_KINDS = (('kind-strength', 'Sức mạnh (tạ, máy, trọng lượng cơ thể)', 'Sức mạnh'),
                  ('kind-endurance', 'Sức bền (chạy, đạp xe, bơi, chèo)', 'Sức bền'),
                  ('kind-sport', 'Thể thao / vận động khác', 'Thể thao'))
MUSCLES = ('Ngực', 'Lưng', 'Vai', 'Tay trước', 'Tay sau', 'Đùi trước', 'Đùi sau', 'Mông', 'Bắp chân', 'Bụng / core', 'Toàn thân')
EQUIPMENT = ('Tạ đòn', 'Tạ đơn', 'Máy', 'Cáp', 'Trọng lượng cơ thể', 'Dây kháng lực', 'Không dùng dụng cụ')


def _choices(prefix, labels):
    return [{'id': f'{prefix}-{index + 1}', 'label': label, 'value': label} for index, label in enumerate(labels)]


def manual_form(target):
    """Khung trên thẻ cho thông tin bài tập mà người dùng cung cấp khi tra cứu chưa đủ căn cứ: lựa chọn, không gõ tay."""
    strength = {'question': 'q1', 'option_ids': ['kind-strength']}
    return {'intro': f'Bạn chọn giúp thông tin bài tập "{target}".', 'questions': [
        {'id': 'q1', 'label': 'Loại bài', 'question': f'"{target}" thuộc loại bài nào?', 'mode': 'single',
         'options': [{'id': key, 'label': label, 'value': value} for key, label, value in EXERCISE_KINDS],
         'required': True, 'min_select': 1, 'max_select': 1},
        {'id': 'q2', 'label': 'Nhóm cơ chính', 'question': 'Bài tập tác động nhóm cơ chính nào?', 'mode': 'multiple',
         'options': _choices('muscle', MUSCLES), 'required': True, 'min_select': 1, 'max_select': 4, 'show_if': strength},
        {'id': 'q3', 'label': 'Dụng cụ', 'question': 'Bài tập dùng dụng cụ gì?', 'mode': 'single',
         'options': _choices('equipment', EQUIPMENT), 'required': True, 'min_select': 1, 'max_select': 1, 'show_if': strength}]}

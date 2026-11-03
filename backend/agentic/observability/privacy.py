"""Che dữ liệu trên bản sao, có giới hạn kích thước.

Số đo cơ thể, chỉ số sinh lý (BMR/TDEE, nhịp tim), tuổi và chấn thương là dữ liệu sức khoẻ
nhạy cảm: chúng bị che cả trong trường có cấu trúc lẫn văn bản tự do (prompt, câu trả lời).
Dinh dưỡng món ăn (kcal, protein) vẫn hiển thị để còn gỡ lỗi câu trả lời. Mục tiêu suy ra vẫn
có thể gợi ý vóc dáng; dùng LANGFUSE_CAPTURE_MODE=metadata_only khi điều đó quan trọng.
"""
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from uuid import UUID

REDACTED = '[REDACTED]'
SECRET_KEYS = {'authorization', 'cookie', 'set_cookie', 'password', 'passwd', 'token', 'access_token', 'refresh_token', 'api_key', 'api_secret', 'secret', 'connection_string', 'database_url', 'dsn', 'headers', 'private_values', 'avatar_url', 'image_url', 'image_candidates', 'illustrations', 'base64', 'embedding', 'embeddings', 'vector', 'vectors', 'attachments'}
IDENTITY_KEYS = {'fullname', 'full_name', 'nick_name', 'nickname', 'email', 'phone', 'phone_number', 'address', 'street', 'personal_info'}
HEALTH = '[HEALTH]'
HEALTH_EXACT_KEYS = {'age', 'bmi', 'bmr_kcal', 'tdee_kcal', 'date_of_birth', 'birth_date', 'birthday', 'injuries',
                     'medical_conditions', 'health_conditions', 'medications', 'allergies', 'pregnancy',
                     'additional_metrics', 'weight_point', 'weight_trend'}
# Dữ liệu món ăn chỉ tình cờ chứa một từ nghe như sức khoẻ.
HEALTH_ALLOWED_KEYS = {'portion_weight_g'}
HEALTH_KEY = re.compile(r'(?:^|_)(?:body)?weight(?:_|$)|(?:^|_)height(?:_|$)|body_fat|muscle_mass|(?:^|_)kg(?:_|$)'
                        r'|(?:^|_)(?:resting|max|avg|min)_hr(?:_|$)|heart_rate|hr_zone|blood_pressure|vo2'
                        # Chỉ số thiết bị (Google Health): tổng hợp nhịp tim, HRV, SpO2, nhịp thở, đường huyết, nhiệt độ.
                        r'|(?:^|_)hr_(?:avg|min|max)(?:_|$)|(?:^|_)hrv(?:_|$)|spo2|oxygen|respiratory|glucose|temperature|skin_temp')
_NUM = r'\d{1,3}(?:[.,]\d{1,2})?'
_LONG_NUM = r'\d+(?:[.,]\d+)*(?!\d)'
HEALTH_PATTERNS = (
    # "58 kg", "58kg", "58 kí", "1 m 62", "162 cm", "22 tuổi", "60 bpm".
    (re.compile(r'(?i)(?<![\w.,])' + _NUM + r'\s?(?:kg|kgs|kí|ký|kilogram|kilô)(?![\w])'), HEALTH),
    (re.compile(r'(?i)(?<![\w.,])\d{2,3}(?:[.,]\d)?\s?cm(?![\w])'), HEALTH),
    (re.compile(r'(?i)(?<![\w.,])[12]\s?m\s?\d{2}(?![\w])|(?<![\w.,])[12][.,]\d{2}\s?m(?![\w])'), HEALTH),
    (re.compile(r'(?i)(?<![\w.,])\d{1,3}\s?tuổi(?![\w])'), HEALTH),
    (re.compile(r'(?i)(?<![\w.,])\d{2,3}\s?bpm(?![\w])'), HEALTH),
    # Giá trị có nhãn nhưng không có đơn vị: "Cân nặng: 58", "BMI 22,1", "mỡ cơ thể 18%", "tuổi: 28".
    (re.compile(r'(?i)((?:cân nặng|chiều cao|vòng (?:eo|bụng|mông|ngực|cổ)|mỡ cơ thể|tỷ lệ mỡ|body ?fat|khối lượng cơ|bmi|bmr|tdee'
                r'|nhịp tim(?: nghỉ| tối đa)?|heart rate|huyết áp|đường huyết|tuổi|weight|height)\W{0,6}(?:\w+\W{1,3}){0,2}?)'
                + _LONG_NUM + r'(?:\s?(?:%|kcal|kg|cm|/\d{2,3}))?'), r'\1' + HEALTH),
)
PATTERNS = (
    (re.compile(r'(?i)\bBearer\s+[^\s"\'<>]+'), 'Bearer ' + REDACTED),
    (re.compile(r'(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s"\'<>]+'), REDACTED),
    (re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'), REDACTED),
    (re.compile(r'\b(?:pk-lf-[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]+|tvly-[A-Za-z0-9_-]+)\b'), REDACTED),
    (re.compile(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}'), '[EMAIL]'),
    # Ngày/giờ ISO ("2026-10-25 21:43") không phải số điện thoại.
    (re.compile(r'(?<![\w.])(?!\d{4}-\d{2}-\d{2})(?:\+?\d[ -]?){9,15}(?![\w.])'), '[PHONE]'),
    (re.compile(r'(?i)(["\'](?:fullname|full_name|nick_name|nickname|email|phone|phone_number|address|street)["\']\s*:\s*)["\'][^"\']*["\']'), r'\1"[REDACTED]"'),
    (re.compile(r'(?i)data:[^;\s]+;base64,[A-Za-z0-9+/=]+'), REDACTED),
    (re.compile(r'(?i)https?://[^\s"<>]*(?:res\.cloudinary\.com|googleusercontent\.com)[^\s"<>]*'), REDACTED),
    (re.compile(r'(?i)(["\']?(?:api[_-]?key|api[_-]?secret|password|access_token|refresh_token|authorization|cookie)["\']?\s*[:=]\s*)["\']?[^\s,}\]"\']+'), r'\1' + REDACTED),
)


def pseudonym(secret, value):
    return hmac.new(secret.encode(), str(value).encode(), hashlib.sha256).hexdigest()


def clean(value, *, private_values=(), secret='', depth=0, key=''):
    if depth > 16:
        return '[TRUNCATED: depth]'
    normalized = key.lower().replace('-', '_')
    if normalized in SECRET_KEYS or normalized in IDENTITY_KEYS or any(normalized.endswith('_' + suffix) for suffix in ('api_key', 'password', 'api_secret')):
        return REDACTED
    if normalized in {'user_id', 'owner_id', 'owner_user_id', 'session_id'}:
        return pseudonym(secret, value) if secret and value else REDACTED
    if value is not None and normalized not in HEALTH_ALLOWED_KEYS and (
            normalized in HEALTH_EXACT_KEYS or HEALTH_KEY.search(normalized)):
        return HEALTH
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        # Số đo của một mẫu sức khoẻ nằm dưới khoá chung "value".
        sample = 'sample_type' in value
        return {str(k): HEALTH if sample and k == 'value' and v is not None else
                clean(v, private_values=private_values, secret=secret, depth=depth + 1, key=str(k)) for k, v in list(value.items())[:200]}
    if isinstance(value, (list, tuple)):
        return [clean(v, private_values=private_values, secret=secret, depth=depth + 1, key=key) for v in value[:100]]
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, (UUID, date, datetime)):
        return str(value)
    if hasattr(value, 'model_dump'):
        return clean(value.model_dump(mode='json'), private_values=private_values, secret=secret, depth=depth + 1)
    if not isinstance(value, str):
        return '[UNSUPPORTED]'
    if depth < 15:
        start = value.find('{')
        if start >= 0:
            try:
                embedded, consumed = json.JSONDecoder().raw_decode(value[start:])
                if isinstance(embedded, dict):
                    redacted = clean(embedded, private_values=private_values, secret=secret, depth=depth + 1)
                    value = value[:start] + json.dumps(redacted, ensure_ascii=False, default=str) + value[start+consumed:]
            except (ValueError, RecursionError):
                if re.search(r'"personal_info"\s*:', value):
                    return REDACTED
    original_size = len(value.encode('utf-8'))
    value = value.encode('utf-8')[:8192].decode('utf-8', errors='ignore')
    for private in sorted({str(v) for v in private_values if v and len(str(v)) >= 2}, key=len, reverse=True):
        value = re.sub(re.escape(private), REDACTED, value, flags=re.I)
    for pattern, replacement in PATTERNS:
        value = pattern.sub(replacement, value)
    for pattern, replacement in HEALTH_PATTERNS:
        value = pattern.sub(replacement, value)
    # Bỏ query string/userinfo trong URL: URL có chữ ký có thể chứa thông tin xác thực.
    value = re.sub(r'(https?://[^\s?"<>]+)\?[^\s"<>]*', r'\1?[REDACTED]', value)
    value = re.sub(r'(https?://)[^/\s:@]+:[^/\s@]+@', r'\1[REDACTED]@', value)
    raw = value.encode('utf-8')
    return value if len(raw) <= 8192 and original_size <= 8192 else raw[:8192].decode('utf-8', errors='ignore') + '[TRUNCATED]'


def bounded(value, **kwargs):
    try:
        result = clean(value, **kwargs)
        if len(json.dumps(result, ensure_ascii=False, default=str).encode()) > 60 * 1024:
            return {'truncated': True, 'reason': 'span_payload_limit'}
        return result
    except Exception:
        return {'redacted': True, 'reason': 'sanitization_failed'}

"""Phân tích bản nháp của model và từ chối trích dẫn/con số không có căn cứ trước khi công bố bằng chứng."""
import json
from agentic.core.providers.fpt import strip_tool_markup
from agentic.research.contracts import EvidenceClaim, ResearchDraft
from agentic.research.quotes import numbers_supported, quote_found

def parse_draft(message,labels):
    """Model trả lời bằng văn bản JSON: ép gọi hàm từng khiến DeepSeek trả về bản nháp rỗng hoàn toàn.
    Khẳng định trích nhãn ngắn (S1...) ánh xạ ngược về id nguồn thật; khẳng định sai định dạng bị bỏ qua."""
    text=strip_tool_markup(message.content if isinstance(message.content,str) else '')
    start,end=text.find('{'),text.rfind('}')
    try:
        data=json.loads(text[start:end+1]) if 0<=start<end else {}
    except ValueError:
        data={}
    if not isinstance(data,dict): data={}
    claims=[]
    for raw in data.get('claims') or []:
        if not isinstance(raw,dict): continue
        label=str(raw.get('source_id','')).strip(' []')
        item={k:raw[k] for k in EvidenceClaim.model_fields if k in raw}
        item.update(source_id=labels.get(label,label),authority='unknown')
        try:
            claims.append(EvidenceClaim.model_validate(item))
        except ValueError:
            continue
    texts=lambda key,limit:[str(v)[:300] for v in (data.get(key) or []) if isinstance(v,(str,int,float))][:limit]
    return ResearchDraft(payload=data.get('payload') if isinstance(data.get('payload'),dict) else {},claims=claims[:30],
                         missing_fields=texts('missing_fields',30),conflicts=texts('conflicts',20),sufficient=data.get('sufficient') is True)


MAX_INVALID_CLAIM_FRACTION = 1 / 3


def check_claims(claims, documents, context=''):
    """(checked, dropped) trong đó dropped chứa (claim, reason) cho các khẳng định không kiểm chứng được."""
    checked, dropped = [], []
    for claim in claims:
        source = documents.get(claim.source_id)
        if not source or not quote_found(claim.quote, source['content']):
            dropped.append((claim, 'Unverified citation'))
            continue
        if claim.conflict or not claim.applicable:
            continue
        # Từ chối khẳng định số liệu bịa ra kể cả khi có kèm một trích dẫn thật.
        if not numbers_supported(claim.claim, claim.quote, context):
            dropped.append((claim, 'Unsupported numeric claim'))
            continue
        checked.append(claim)
    return checked, dropped


def verify_claims(claims, documents, *, strict=True, context=''):
    """Các khẳng định đã kiểm chứng. Kiểm tra chặt (bản ghi catalog có thể được lưu) từ chối thẳng một bản nháp
    phần lớn là bịa; câu trả lời tri thức giữ lại những gì đã kiểm chứng và bỏ phần còn lại."""
    checked, dropped = check_claims(claims, documents, context)
    if strict and dropped and len(dropped) > MAX_INVALID_CLAIM_FRACTION * max(1, len(claims)):
        raise ValueError(dropped[0][1])
    return checked


def verified_claims(claims, documents, context=''):
    """Mọi khẳng định có trích dẫn nằm trong nguồn và có con số nằm trong trích dẫn, bất kể
    model nói gì về khả năng áp dụng hay mâu thuẫn: tư liệu mà người dùng có thể chọn."""
    return [c for c in claims if c.source_id in documents and quote_found(c.quote, documents[c.source_id]['content'])
            and numbers_supported(c.claim, c.quote, context)]


def related_claims(claims, documents, context=''):
    """Trích dẫn đã kiểm chứng mà model đánh giá là không áp dụng (khẩu phần, công thức hay đối tượng khác): hiển thị cho
    người dùng như các ước tính để chọn, không bao giờ tự lưu thành dữ kiện."""
    return [c for c in claims if not c.applicable and not c.conflict and c.source_id in documents
            and quote_found(c.quote, documents[c.source_id]['content']) and numbers_supported(c.claim, c.quote, context)]

"""Parse model drafts and reject unsupported citations/numbers before publishing evidence."""
import json
from agentic.core.providers.fpt import strip_tool_markup
from research.contracts import EvidenceClaim, ResearchDraft
from research.quotes import numbers_supported, quote_found

def parse_draft(message,labels):
    """The model answers with JSON text: a forced function call made DeepSeek return an all-empty draft.
    Claims cite short labels (S1...) that map back to real source ids; malformed claims are skipped."""
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


def check_claims(claims, documents):
    """(checked, dropped) where dropped holds (claim, reason) for unverifiable claims."""
    checked, dropped = [], []
    for claim in claims:
        source = documents.get(claim.source_id)
        if not source or not quote_found(claim.quote, source['content']):
            dropped.append((claim, 'Unverified citation'))
            continue
        if claim.conflict or not claim.applicable:
            continue
        # Reject invented numeric assertions even if a real quote was attached.
        if not numbers_supported(claim.claim, claim.quote):
            dropped.append((claim, 'Unsupported numeric claim'))
            continue
        checked.append(claim)
    return checked, dropped


def verify_claims(claims, documents):
    checked, dropped = check_claims(claims, documents)
    if dropped and len(dropped) > MAX_INVALID_CLAIM_FRACTION * max(1, len(claims)):
        raise ValueError(dropped[0][1])
    return checked


def verified_claims(claims, documents):
    """Every claim whose quote is in its source and whose numbers are in the quote, whatever the
    model said about applicability or conflicts: the material a person can choose from."""
    return [c for c in claims if c.source_id in documents and quote_found(c.quote, documents[c.source_id]['content'])
            and numbers_supported(c.claim, c.quote)]


def related_claims(claims, documents):
    """Verified quotes the model judged not applicable (another size, recipe or object): shown to the
    user as estimates to choose from, never saved as facts on their own."""
    return [c for c in claims if not c.applicable and not c.conflict and c.source_id in documents
            and quote_found(c.quote, documents[c.source_id]['content']) and numbers_supported(c.claim, c.quote)]

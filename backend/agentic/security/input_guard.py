"""Existing public-query privacy and clinical-topic guards."""
import re
from models.foods import normalize_food_text

class ClinicalQuestion(ValueError):
    pass


# Diagnosis, treatment, rehabilitation, specific pain, medical conditions and an injury the
# person already has need a professional. Matched on accent-free text, where "đau" and "đâu"
# collapse to "dau", so only multi-word pain phrases are listed.
CLINICAL = re.compile(r'dau nguc|dau goi|dau lung|dau khop|phuc hoi chuc nang|phau thuat|benh tim|tieu duong|'
    r'mang thai|ke don|lieu thuoc|chan doan|dieu tri|chua tri|\b(?:dang|da|vua) bi\b|sau (?:khi )?(?:bi )?chan thuong|'
    r'rehab|diagnos|treat|chest pain|knee pain|back pain|surgery|pregnan|diabet|prescri|medication|'
    r"i'?m injured|i am injured|i (?:have|got) (?:an? )?injur|my injur")
INJURY = re.compile(r'chan thuong|gay xuong|injur|fracture')
# Preventing injuries (training load, shoes, technique) is general training guidance.
PREVENTION = re.compile(r'phong ngua|phong tranh|\btranh\b|giam nguy co|nguy co|prevent|avoid|risk|injury.free')


def clinical_topic(query):
    text = normalize_food_text(query)
    return bool(CLINICAL.search(text)) or (bool(INJURY.search(text)) and not PREVENTION.search(text))


def injury_prevention(query):
    """An allowed injury question; its answer carries a see-a-professional note."""
    text = normalize_food_text(query)
    return bool(INJURY.search(text)) and not clinical_topic(query)


def safe_query(query,private_values=()):
    if not query or len(query)>180 or re.search(r'@|bearer|token|password|https?://|\b\d+\s*(kg|cm|tuổi)\b',query,re.I):
        raise ValueError('A public research topic without personal data is required')
    if re.search(r'(?:\+?\d[ .-]*){8,}',query):
        raise ValueError('Possible phone/account identifier in query')
    if any(v and len(v)>2 and v.casefold() in query.casefold() for v in private_values):
        raise ValueError('Private query')
    return query.strip()

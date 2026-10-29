"""Existing public-query privacy and clinical-topic guards."""
import re
from models.foods import normalize_food_text

class ClinicalQuestion(ValueError):
    pass


def clinical_topic(query):
    return bool(re.search(r'chan thuong|dau nguc|dau goi|dau lung|dau khop|phuc hoi chuc nang|'
        r'phau thuat|gay xuong|benh tim|tieu duong|mang thai|ke don|lieu thuoc|'
        r'rehab|injur|diagnos|chest pain|knee pain|back pain|surgery|fracture|pregnan|diabet|prescri',
        normalize_food_text(query)))


def safe_query(query,private_values=()):
    if not query or len(query)>180 or re.search(r'@|bearer|token|password|https?://|\b\d+\s*(kg|cm|tuổi)\b',query,re.I):
        raise ValueError('A public research topic without personal data is required')
    if re.search(r'(?:\+?\d[ .-]*){8,}',query):
        raise ValueError('Possible phone/account identifier in query')
    if any(v and len(v)>2 and v.casefold() in query.casefold() for v in private_values):
        raise ValueError('Private query')
    return query.strip()

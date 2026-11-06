"""Các chốt bảo vệ quyền riêng tư của truy vấn công khai và chủ đề lâm sàng hiện có."""
import re
from domains.catalog.models.foods import normalize_food_text

class ClinicalQuestion(ValueError):
    pass


# Chẩn đoán, điều trị, phục hồi chức năng, cơn đau cụ thể, bệnh lý và chấn thương mà
# người dùng đang có cần đến chuyên gia. So khớp trên văn bản không dấu, nơi "đau" và "đâu"
# cùng thành "dau", nên chỉ liệt kê các cụm từ nhiều chữ về đau.
CLINICAL = re.compile(r'dau nguc|dau goi|dau lung|dau khop|phuc hoi chuc nang|phau thuat|benh tim|tieu duong|'
    r'mang thai|ke don|lieu thuoc|chan doan|dieu tri|chua tri|\b(?:dang|da|vua) bi\b|sau (?:khi )?(?:bi )?chan thuong|'
    r'rehab|diagnos|treat|chest pain|knee pain|back pain|surgery|pregnan|diabet|prescri|medication|'
    r"i'?m injured|i am injured|i (?:have|got) (?:an? )?injur|my injur")
INJURY = re.compile(r'chan thuong|gay xuong|injur|fracture')
# Phòng ngừa chấn thương (khối lượng tập, giày, kỹ thuật) là hướng dẫn tập luyện chung.
PREVENTION = re.compile(r'phong ngua|phong tranh|\btranh\b|giam nguy co|nguy co|prevent|avoid|risk|injury.free')


def clinical_topic(query):
    text = normalize_food_text(query)
    return bool(CLINICAL.search(text)) or (bool(INJURY.search(text)) and not PREVENTION.search(text))


def injury_prevention(query):
    """Một câu hỏi về chấn thương được phép; câu trả lời kèm lời khuyên gặp chuyên gia."""
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


def public_queries(primary,variants=(),private_values=()):
    """(truy vấn chính, các biến thể, số truy vấn bị bỏ). Mỗi truy vấn qua safe_query riêng: một biến thể
    lỗi (có số đo, quá dài, chứa dữ liệu riêng) chỉ bị bỏ, không làm hỏng cả lần tra cứu. Truy vấn chính
    lỗi thì biến thể hợp lệ đầu tiên thay chỗ; không còn truy vấn nào thì ValueError như safe_query."""
    def checked(query):
        try:
            return safe_query(query,private_values)
        except ValueError:
            return None
    main=checked(primary)
    given=[q for q in variants or [] if q]
    others=[q for q in map(checked,given) if q]
    dropped=(bool(primary) and not main)+len(given)-len(others)
    if not main and not others:
        raise ValueError('A public research topic without personal data is required')
    main=main or others[0]
    return main,(others or [main])[:3],dropped

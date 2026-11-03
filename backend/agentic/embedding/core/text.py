import unicodedata


def normalize_text(value):
    """Chữ thường, bỏ dấu tiếng Việt và gộp khoảng trắng, cho cả search_vector lúc nạp và câu truy vấn.

    Đây là hợp đồng với các tsvector đã lưu: đổi cách chuẩn hoá thì phải nạp lại mọi revision.
    """
    value = unicodedata.normalize('NFD', value.lower().replace('đ', 'd'))
    return ' '.join(''.join(char for char in value if not unicodedata.combining(char)).split())

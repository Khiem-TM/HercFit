"""Chốt ghi buổi tập gym: một câu chung chung "tập gym" được ghi chi tiết hoặc ghi nhanh, và người dùng chọn trước.

Ghi chi tiết (bài tập, sets x reps x mức tạ) nuôi khối lượng tập, e1RM và phân tích
tiến độ; ghi nhanh chỉ cần cường độ buổi tập để ước tính calo
(bản ghi catalog gym_general, RESISTANCE_MET trong backend). Hỏi trước mọi lần
tra catalog giúp người chỉ cần calo khỏi phải điền form bài tập dài.

Form, nhãn và giá trị của nó do code quản lý, nên câu trả lời cho form được code
định tuyến ở lượt sau mà không gọi model định tuyến.
"""
import re

from domains.catalog.models.foods import normalize_food_text

# Accents stripped: "tập tạ", "thể hình", "phòng tập"...
GYM = re.compile(r'\b(?:gym|tap ta|nang ta|cu ta|the hinh|phong tap|weight ?training|strength training|tap suc manh)\b')
# Thành tích đã được nêu ("4x8", "3 hiệp", "10 reps"): người dùng đang ghi chi tiết. "70kg" đứng riêng có thể là cân nặng cơ thể.
DETAILS = re.compile(r'\d+\s*[x×]\s*\d+|\b\d+\s*(?:hiep|set|sets|rep|reps)\b')
DURATION = re.compile(r'\b\d+(?:[.,]\d+)?\s*(?:tieng|gio|h|phut|p|min|mins|minutes?|hours?)\b|\bnua tieng\b')
LOG_DOMAINS = {'trainings', 'exercises'}

MODE_LABEL = 'Cách ghi buổi gym'
INTENSITY_LABEL = 'Cường độ buổi gym'
DURATION_LABEL = 'Thời lượng buổi gym'
# Giá trị được gửi lại như tin nhắn của người dùng, nên mỗi giá trị tự gọi tên lựa chọn của nó.
DETAILED_VALUE = 'Ghi chi tiết buổi gym: từng bài, số hiệp × reps × mức tạ'
QUICK_VALUE = 'Ghi nhanh buổi gym theo cường độ'
INTENSITIES = (
    ('gym-light', 'Nhẹ', 'LIGHT', 'Tạ nhẹ, nghỉ nhiều, kết thúc vẫn còn dư sức'),
    ('gym-moderate', 'Vừa', 'MODERATE', '8–15 reps, nghỉ 1–2 phút, hơi đuối cuối hiệp'),
    ('gym-vigorous', 'Mạnh', 'VIGOROUS', 'Tạ nặng hoặc gần thất bại, nghỉ ngắn'),
)
REPLY = ('Bạn muốn ghi buổi gym thế nào? **Nhập chi tiết từng bài** (số hiệp × reps × mức tạ) giúp HercFit theo dõi '
         'khối lượng, 1RM và tiến bộ sức mạnh. **Ghi nhanh theo cường độ** chỉ cần chọn mức nhẹ / vừa / mạnh để ước tính calories.')


def asks_mode(request: str, decision) -> bool:
    """Một yêu cầu mới ghi buổi tập gym mà không nêu set, số lần hay mức tạ."""
    text = normalize_food_text(request or '')
    return (decision.intent == 'LOG_EXERCISE' and decision.action in {'tool', 'clarify'} and decision.domain in LOG_DOMAINS
            and bool(GYM.search(text)) and not DETAILS.search(text))


def mode_form(request: str) -> dict:
    """Form lựa chọn; cường độ (và thời lượng, khi yêu cầu chưa có) chỉ hỏi sau "ghi nhanh"."""
    quick = {'question': 'q1', 'option_ids': ['gym-quick']}
    questions = [
        {'id': 'q1', 'label': MODE_LABEL, 'question': 'Bạn muốn ghi buổi gym thế nào?', 'mode': 'single',
         'options': [
             {'id': 'gym-detailed', 'label': 'Nhập chi tiết từng bài', 'value': DETAILED_VALUE,
              'description': 'Chọn bài, số hiệp × reps × mức tạ — theo dõi khối lượng, 1RM, tiến bộ'},
             {'id': 'gym-quick', 'label': 'Ghi nhanh theo cường độ', 'value': QUICK_VALUE,
              'description': 'Chỉ chọn nhẹ / vừa / mạnh để ước tính calories'}]},
        {'id': 'q2', 'label': INTENSITY_LABEL, 'question': 'Buổi gym của bạn ở mức nào?', 'mode': 'single',
         'show_if': quick, 'options': [{'id': key, 'label': label, 'value': label, 'description': hint} for key, label, _, hint in INTENSITIES]},
    ]
    if not DURATION.search(normalize_food_text(request or '')):
        # Được trả lời là "60 phút" trên thẻ (bộ tăng giảm hoặc giá trị có sẵn), parse_choice đọc ngược lại.
        questions.append({'id': 'q3', 'label': DURATION_LABEL, 'question': 'Buổi gym kéo dài khoảng bao lâu?', 'mode': 'number',
                          'show_if': quick, 'options': [],
                          'number': {'unit': 'phút', 'min': 10, 'max': 300, 'step': 5, 'default': 60, 'presets': [30, 45, 60, 90]}})
    return {'intro': 'Bạn muốn ghi buổi gym chi tiết hay chỉ ước tính nhanh calories?', 'questions': questions}


def _line(request: str, label: str) -> str | None:
    match = re.search(r'^\s*' + re.escape(label) + r'\s*:\s*(.+)$', request or '', re.MULTILINE)
    return match.group(1).strip() if match else None


def parse_choice(request: str) -> dict | None:
    """Câu trả lời cho mode_form: {'mode': 'detailed'} hoặc {'mode': 'quick', 'intensity', 'duration'}; ngược lại là None."""
    text = normalize_food_text(request or '')
    if normalize_food_text(DETAILED_VALUE) in text:
        return {'mode': 'detailed'}
    if normalize_food_text(QUICK_VALUE) not in text:
        return None
    level = normalize_food_text(_line(request, INTENSITY_LABEL) or '')
    intensity = next((code for _, label, code, _ in INTENSITIES if normalize_food_text(label) == level), None)
    return {'mode': 'quick', 'intensity': intensity, 'duration': _line(request, DURATION_LABEL)}


def instruction(choice: dict) -> str:
    rest = ' Các hoạt động khác trong yêu cầu gốc (môn thể thao, chạy...) ghi như bình thường, hỏi thêm nếu thiếu.'
    if choice['mode'] == 'detailed':
        return ('Người dùng chọn nhập chi tiết buổi gym trong yêu cầu gốc. Tra catalog (list_exercises) các bài theo nhóm cơ '
                'hoặc tên bài đã nêu, liệt kê các bài khớp rồi hỏi: bài nào đã tập (chọn trong danh sách) và số hiệp × reps × '
                'mức tạ (kg) của từng bài. Mỗi bài là một item STRENGTH, mỗi hiệp là một phần tử sets.' + rest)
    intensity = choice.get('intensity') or 'MODERATE'
    duration = choice.get('duration') or 'thời lượng buổi gym trong yêu cầu gốc'
    return ('Người dùng chọn ghi nhanh buổi gym, không nhập từng bài. Ghi buổi gym thành MỘT item của bài catalog '
            '"Tập gym (tổng quát)" (code gym_general; tra list_exercises search "gym"): performance kind SPORT, intensity '
            f'{intensity}, duration_seconds theo {duration}. Không hỏi bài, số hiệp, reps hay mức tạ; backend tự ước tính '
            'calories theo cường độ.' + rest)

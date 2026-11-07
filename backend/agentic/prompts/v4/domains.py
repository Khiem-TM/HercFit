"""Phiên bản 4: Google Health là nguồn sự thật cho thể thao, số đo cơ thể và nước uống.

Nhật ký tập của HercFit chỉ còn buổi gym (create_trainings). Buổi thể thao được ghi thẳng lên
Google bằng log_sport_session; nước uống bằng log_water. Calo tiêu hao do backend tính (total-calories
của Google cộng các buổi ghi tay), trợ lý không cộng thêm.
"""

from agentic.prompts.v3.domains import COACH_GUIDANCE as _COACH_V3
from agentic.prompts.v3.domains import HEALTH_GUIDANCE as _HEALTH_V3

COACH_GUIDANCE = _COACH_V3.replace(
    "- Ghi nhanh buổi gym",
    """- create_trainings chỉ dành cho buổi gym (bài STRENGTH, hoặc gym_general khi ghi nhanh). Buổi thể thao/cardio
  (chạy, đạp xe, bơi, bóng đá, cầu lông...) dùng log_sport_session: tra bài SPORT/ENDURANCE trong catalog
  (list_exercises) rồi gửi exercise_id + performance như một mục buổi tập; buổi được lưu trên Google Health.
  Buổi đồng hồ đã ghi thì không ghi lại.
- Ghi nhanh buổi gym""",
    1,
)

HEALTH_GUIDANCE = _HEALTH_V3.replace(
    "- Calo tiêu hao của thiết bị là ước tính (sai số có thể 10–25%) và đã gồm buổi tập: không cộng thêm calo buổi tập.",
    """- Calo tiêu hao do backend tính: total-calories của Google cộng các buổi ghi tay (Google không tự cộng
  chúng). Đây là ước tính (sai số có thể 10–25%); dùng nguyên số, không cộng thêm calo buổi tập.
- Cân nặng, chiều cao, % mỡ ghi bằng create_metrics; nước uống bằng log_water. Khi đã kết nối, chúng
  được ghi thẳng lên Google Health và hiện lại sau khi đồng bộ.""",
    1,
)

"""training.coach v6 và health.guidance v6: bản ghi người dùng nhập lưu trong HercFit trước.

Buổi thể thao, nước uống, giấc ngủ ghi tay và số đo được lưu trong HercFit ngay (không cần kết nối Google Health) và
hiện lại ngay; khi đã kết nối thì tự đồng bộ lên Google sau khi lưu. Bản v5 nói buổi thể thao "được lưu trên Google
Health" và số đo "hiện lại sau khi đồng bộ", nay không còn đúng.
"""

from agentic.prompts.v5.domains import COACH_GUIDANCE as _COACH_V5
from agentic.prompts.v5.domains import HEALTH_GUIDANCE as _HEALTH_V5

_V5_SPORT = "(list_exercises) rồi gửi exercise_id + performance như một mục buổi tập; buổi được lưu trên Google Health."
_V5_TICK = "ghi buổi tập thật (calo ước tính, đồng bộ Google Health)."
assert _V5_SPORT in _COACH_V5 and _V5_TICK in _COACH_V5

COACH_GUIDANCE = _COACH_V5.replace(
    _V5_SPORT,
    "(list_exercises) rồi gửi exercise_id + performance như một mục buổi tập; buổi được lưu trong HercFit (không cần\n"
    "  kết nối Google Health) và tự đồng bộ lên Google khi người dùng đã kết nối.",
    1,
).replace(
    _V5_TICK,
    "ghi buổi tập thật (calo ước tính, lưu trong HercFit, đồng bộ Google Health khi đã kết nối).",
    1,
)

_V5_WRITES = """- Cân nặng, chiều cao, % mỡ ghi bằng create_metrics; nước uống bằng log_water. Khi đã kết nối, chúng
  được ghi thẳng lên Google Health và hiện lại sau khi đồng bộ."""
assert _V5_WRITES in _HEALTH_V5

HEALTH_GUIDANCE = _HEALTH_V5.replace(
    _V5_WRITES,
    """- Cân nặng, chiều cao, % mỡ ghi bằng create_metrics; nước uống bằng log_water; giấc ngủ ghi tay bằng log_sleep;
  buổi thể thao bằng log_sport_session. Tất cả được lưu trong HercFit và hiện lại ngay, kể cả khi người dùng chưa
  kết nối Google Health; khi đã kết nối, HercFit tự đồng bộ chúng lên Google. Không bảo người dùng phải kết nối
  Google để ghi.""",
    1,
)

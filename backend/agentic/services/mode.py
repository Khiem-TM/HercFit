"""Chế độ trò chuyện do người dùng chọn bằng nút trên ô nhập; code (không phải model) áp chính sách của nó.

* normal: ghi nhận dữ liệu (bữa ăn, buổi tập, số đo) và xem nhanh tiến độ. Không tra cứu tri thức, không thẻ ngữ
  cảnh cá nhân, tool bind theo đúng hành động; câu hỏi tư vấn được mời sang chế độ Plan thay vì trả lời từ trí nhớ.
* plan: tư vấn chuyên sâu, phân tích chất lượng sống, lập kế hoạch tập. Luôn đọc dữ liệu của người dùng và tra cứu
  nguồn đã kiểm chứng theo từng câu hỏi con, effort cao hơn, thời gian và ngân sách tra cứu rộng hơn; vẫn ghi
  dữ liệu được như chế độ thường.
* full: hành vi trước khi có chế độ, cho state không mang trường 'mode' (checkpoint cũ đang chờ xác nhận, script
  đánh giá, test). API luôn gửi một chế độ nên lượt chat mới không bao giờ rơi vào đây.

Logic graph đọc chế độ từ state đã checkpoint; client model, ngân sách tra cứu và timeout đọc biến ngữ cảnh
`current` mà runtime đặt cho đúng lượt chạy đó.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field

NORMAL, PLAN, FULL = "normal", "plan", "full"
MODES = (NORMAL, PLAN)

RESEARCH_LIMITS = {"web": 8, "search": 3, "llm": 3, "rounds": 2}


@dataclass(frozen=True)
class ModePolicy:
    name: str
    # Miền được định tuyến tới; None là mọi miền.
    domains: frozenset | None = None
    # Câu hỏi tư vấn/tri thức được trả lời bằng tra cứu (RAG + web chính thống); False: mời sang chế độ Plan.
    knowledge: bool = True
    # Thẻ ngữ cảnh cá nhân được nạp cho router và câu trả lời.
    personal_card: bool = True
    # Mọi câu hỏi không phải ghi nhật ký đều cá nhân hoá và tra cứu, không chờ model đoán.
    deep: bool = False
    # Lối tắt đọc nhanh bằng mẫu và cổng định tuyến đọc của Jev.
    shortcuts: bool = True
    # Tool của miền ghi nhận được bind theo hành động (sửa/xoá chỉ khi yêu cầu nói tới).
    lean_tools: bool = False
    # Hướng dẫn huấn luyện/sức khoẻ dài trong prompt của tool và câu trả lời.
    guidance: bool = True
    # Effort suy luận theo vai trò model (None: theo cấu hình); chỉ áp cho nhà cung cấp FPT.
    efforts: dict = field(default_factory=dict)
    # Timeout client model theo vai trò (giây), ghi đè cấu hình khi lớn hơn.
    timeouts: dict = field(default_factory=dict)
    research_seconds: float = 60
    research_limits: dict = field(default_factory=lambda: dict(RESEARCH_LIMITS))
    # Số đoạn trích cơ sở tri thức và số nguồn web tối đa mỗi lượt (tính riêng từng loại).
    documents: int = 6

    def allows(self, domain):
        return self.domains is None or domain in self.domains


POLICIES = {
    FULL: ModePolicy(FULL),
    NORMAL: ModePolicy(
        NORMAL,
        domains=frozenset({"meals", "foods", "trainings", "exercises", "metrics", "progress"}),
        knowledge=False,
        personal_card=False,
        lean_tools=True,
        guidance=False,
        # Tool giữ 'medium': ở 'low' model từng viết bản xem trước bằng chữ thay vì gọi create_meals (02/11).
        efforts={"response": "low"},
    ),
    PLAN: ModePolicy(
        PLAN,
        deep=True,
        shortcuts=False,
        efforts={"research": "medium", "response": "high"},
        # Router ở chế độ Plan nhận prompt dài hơn (cá nhân hoá + lập kế hoạch) và suy luận lâu hơn: đo trên Langfuse
        # 13/11 là 9–21 s với 2–3,5k token đầu ra, vượt ROUTING_TIMEOUT_SECONDS = 12 s; ba lần thử đều hết giờ thì
        # lượt chạy thất bại sau ~38 s (OpenAITimeoutError ở node orchestrator).
        timeouts={"decision": 30, "research": 60, "response": 90},
        research_seconds=120,
        research_limits={"web": 10, "search": 4, "llm": 4, "rounds": 3},
        documents=8,
    ),
}

current: ContextVar[str] = ContextVar("chat_mode", default=FULL)


def policy(state=None) -> ModePolicy:
    """Chính sách của state (trường 'mode'), hoặc của lượt chạy hiện tại khi không truyền state."""
    name = current.get() if state is None else state.get("mode")
    return POLICIES.get(name or FULL, POLICIES[FULL])


def run_timeout(settings, name) -> float:
    return settings.PLAN_RUN_TIMEOUT_SECONDS if name == PLAN else settings.RUN_TIMEOUT_SECONDS

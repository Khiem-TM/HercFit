import logging
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)


class ClarifyOption(BaseModel):
    id: str
    label: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=200)
    # Chỉ chép từ các bản ghi catalog mà tool trả về trong lượt này, không bao giờ do model sinh.
    image_url: str | None = None
    ref: dict[str, str] | None = None
    # Văn bản gửi lại như tin nhắn tiếp theo của người dùng khi lựa chọn được chọn.
    value: str = Field(max_length=300)


class ShowIf(BaseModel):
    """The question is asked only when an earlier question was answered with one of these options."""

    question: str
    option_ids: list[str] = Field(min_length=1)


# Các đơn vị mà khung nhập số có thể hỏi, cùng khoảng rộng nhất (thấp nhất, cao nhất) và bước mặc định thẻ đưa ra.
# Khoảng riêng của một khung phải nằm trong đó: không thể chọn một số gõ nhầm như 700 kg.
NUMBER_UNITS: dict[str, tuple[float, float, float]] = {
    "kg": (0, 500, 0.5),
    "g": (0, 5000, 5),
    "ml": (0, 5000, 50),
    "kcal": (0, 10000, 10),
    "phút": (1, 1440, 5),
    "giờ": (0.25, 24, 0.25),
    "km": (0.1, 500, 0.1),
    "cm": (30, 250, 1),
    "%": (0, 100, 0.5),
    "bpm": (30, 230, 1),
    "tuổi": (10, 100, 1),
    "RPE": (1, 10, 0.5),
    "bước": (0, 100000, 500),
    "buổi": (1, 14, 1),
    "ngày": (1, 365, 1),
    "tuần": (1, 52, 1),
    "hiệp": (1, 20, 1),
    "reps": (1, 100, 1),
    "lần": (1, 50, 1),
    "suất": (0.25, 20, 0.25),
    "phần": (0.25, 20, 0.25),
    "quả": (1, 30, 1),
    "ly": (0.5, 10, 0.5),
    "cốc": (0.5, 10, 0.5),
    "chai": (0.5, 10, 0.5),
    "lon": (0.5, 10, 0.5),
    "hộp": (0.5, 10, 0.5),
    "bát": (0.5, 10, 0.5),
    "tô": (0.5, 10, 0.5),
    "đĩa": (0.5, 10, 0.5),
    "lát": (1, 20, 1),
    "miếng": (1, 20, 1),
    "cái": (1, 20, 1),
}
Unit = Literal[
    "kg",
    "g",
    "ml",
    "kcal",
    "phút",
    "giờ",
    "km",
    "cm",
    "%",
    "bpm",
    "tuổi",
    "RPE",
    "bước",
    "buổi",
    "ngày",
    "tuần",
    "hiệp",
    "reps",
    "lần",
    "suất",
    "phần",
    "quả",
    "ly",
    "cốc",
    "chai",
    "lon",
    "hộp",
    "bát",
    "tô",
    "đĩa",
    "lát",
    "miếng",
    "cái",
]


class NumberFrame(BaseModel):
    """One value picked with a stepper or a preset, never typed as free text."""

    unit: Unit
    min: float
    max: float
    step: float = Field(gt=0)
    # Hiển thị sẵn đã chọn; None nghĩa là để người dùng tự chọn.
    default: float | None = None
    # Các giá trị thường dùng chọn bằng một chạm ("30 phút", "45 phút").
    presets: list[float] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _within_unit(self):
        low, high, _ = NUMBER_UNITS[self.unit]
        if not low <= self.min < self.max <= high:
            raise ValueError(f"number range must lie within {low}..{high} {self.unit}")
        if self.default is not None and not self.min <= self.default <= self.max:
            raise ValueError("default outside the range")
        if any(not self.min <= value <= self.max for value in self.presets) or len(
            set(self.presets)
        ) != len(self.presets):
            raise ValueError("presets must be distinct values inside the range")
        return self


class DatePreset(BaseModel):
    label: str = Field(max_length=40)
    value: date


class DateFrame(BaseModel):
    """One calendar day picked from a date picker or a preset ("3 tháng nữa"), never typed as free text."""

    min: date
    max: date
    # Hiển thị sẵn đã chọn; None nghĩa là để người dùng tự chọn.
    default: date | None = None
    presets: list[DatePreset] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _within(self):
        if not self.min <= self.max:
            raise ValueError("date range is empty")
        if (self.max - self.min).days > 366 * 5:
            raise ValueError("date range longer than five years")
        if self.default is not None and not self.min <= self.default <= self.max:
            raise ValueError("default outside the range")
        values = [preset.value for preset in self.presets]
        if any(not self.min <= value <= self.max for value in values) or len(set(values)) != len(
            values
        ):
            raise ValueError("presets must be distinct days inside the range")
        return self


class ClarifyQuestion(BaseModel):
    """One missing piece of information as a standard card frame; the client asks these one step at a time.

    Every frame is answered on the card itself (no typed free text):
    'single'/'quick_reply' pick one option, 'multiple' picks min_select..max_select options, 'number' picks a
    value of `number` (stepper and presets), 'date' picks a day of `date_frame` (calendar and presets), 'sets' edits
    sets × reps × kg per exercise: the exercises picked in for_questions, or its own options as rows.
    """

    id: str
    # Chủ đề ngắn ("Mục tiêu chính") dùng làm nhãn cho câu trả lời trong tin nhắn được soạn.
    label: str = Field(max_length=60)
    question: str = Field(max_length=300)
    mode: Literal["single", "multiple", "quick_reply", "number", "date", "sets"] = "single"
    # Catalog picks list every record the reply showed ("những bài nào trong danh sách?").
    options: list[ClarifyOption] = Field(default_factory=list, max_length=12)
    # Câu hỏi tuỳ chọn có thể bỏ qua trong trình hướng dẫn.
    required: bool = True
    min_select: int = Field(default=1, ge=0, le=12)
    max_select: int = Field(default=1, ge=1, le=12)
    for_questions: list[str] = Field(default_factory=list)
    show_if: ShowIf | None = None
    number: NumberFrame | None = None
    date_frame: DateFrame | None = None

    @model_validator(mode="after")
    def _frame(self):
        ids = [option.id for option in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("option ids must be unique")
        if (self.mode == "number") != (self.number is not None):
            raise ValueError("a number frame, and only it, carries a number range")
        if (self.mode == "date") != (self.date_frame is not None):
            raise ValueError("a date frame, and only it, carries a date range")
        if self.mode in {"number", "date"} and self.options:
            raise ValueError("a number or date frame has presets, not options")
        if self.mode in {"single", "quick_reply"} and (not self.options or self.max_select != 1):
            raise ValueError("a single choice needs options and picks one")
        if self.mode == "multiple" and not (
            len(self.options) >= 2 and 1 <= self.min_select <= self.max_select <= len(self.options)
        ):
            raise ValueError(
                "a multiple choice needs two or more options and a valid selection range"
            )
        if self.mode == "sets" and not (self.for_questions or self.options):
            raise ValueError("a sets editor needs exercise picks or its own rows")
        return self


class Clarification(BaseModel):
    """Human-in-the-loop form: standard card frames answered as a single next message."""

    intro: str | None = Field(default=None, max_length=300)
    questions: list[ClarifyQuestion] = Field(min_length=1, max_length=8)

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data):
        # Checkpoint và phản hồi xác nhận đã lưu từ trước khi form chỉ chứa một câu hỏi cấp cao nhất.
        if isinstance(data, dict) and "questions" not in data and "question" in data:
            question = {key: value for key, value in data.items() if key != "intro"}
            return {
                "intro": data.get("intro"),
                "questions": [{"id": "q1", "label": "Trả lời", **question}],
            }
        return data

    @model_validator(mode="after")
    def _references(self):
        seen: dict[str, ClarifyQuestion] = {}
        for question in self.questions:
            if question.id in seen:
                raise ValueError("question ids must be unique")
            if any(source not in seen for source in question.for_questions):
                raise ValueError("a sets editor takes rows from earlier questions only")
            rule = question.show_if
            if rule and (
                rule.question not in seen
                or not set(rule.option_ids) <= {o.id for o in seen[rule.question].options}
            ):
                raise ValueError("show_if must name options of an earlier question")
            seen[question.id] = question
        return self

    @classmethod
    def sanitize(cls, data) -> dict | None:
        """Phần hợp lệ của một form, hoặc None: các khung không qua kiểm tra (kể cả câu hỏi văn bản
        tự do của checkpoint cũ) bị bỏ cùng các câu hỏi phụ thuộc vào chúng."""
        if not data:
            return None
        if isinstance(data, BaseModel):
            data = data.model_dump(mode="json")
        data = cls._legacy(data)
        if not isinstance(data, dict):
            return None
        kept: dict[str, dict] = {}
        for raw in data.get("questions") or []:
            if not isinstance(raw, dict):
                continue
            question = {
                **raw,
                "for_questions": [i for i in raw.get("for_questions") or [] if i in kept],
            }
            rule = raw.get("show_if")
            if rule and (
                rule.get("question") not in kept
                or not set(rule.get("option_ids") or [])
                <= {o.get("id") for o in kept[rule["question"]].get("options") or []}
            ):
                continue
            if (
                raw.get("for_questions")
                and not question["for_questions"]
                and not raw.get("options")
            ):
                continue
            try:
                kept.setdefault(
                    question.get("id"),
                    ClarifyQuestion.model_validate(question).model_dump(mode="json"),
                )
            except ValidationError:
                continue
        if len(kept) < len(data.get("questions") or []):
            logger.info(
                "clarification_frames_dropped count=%s",
                len(data.get("questions") or []) - len(kept),
            )
        if not kept:
            return None
        try:
            return cls.model_validate(
                {"intro": data.get("intro"), "questions": list(kept.values())[:8]}
            ).model_dump(mode="json")
        except ValidationError:
            return None


class Illustration(BaseModel):
    """Third-party picture found by research; shown for context, stored only via Cloudinary import."""

    url: str
    description: str | None = None


class FoodGapItem(BaseModel):
    """One food the user named that matches no catalog name: the card resolves it by search or a custom food."""

    key: str = Field(max_length=16)
    query: str = Field(max_length=80)
    # Lượng trong bản nháp của router (để điền sẵn trên thẻ); None khi người dùng chưa nói.
    quantity: float | None = None
    unit: Literal["SERVING", "G", "ML"] | None = None


class FoodGapMeal(BaseModel):
    name: str | None = None
    consumed_at: str | None = None


class FoodGap(BaseModel):
    """Card asking the user to pick a catalog food or create a custom one for each missing food."""

    items: list[FoodGapItem] = Field(min_length=1, max_length=5)
    meal: FoodGapMeal | None = None


class FoodNutrition(BaseModel):
    """AI suggestion for a custom food: exactly four values per 100 g."""

    energy_kcal: float
    carbohydrate_g: float
    fat_g: float
    protein_g: float
    # True: model estimate (no source stated all four values); False: copied verbatim from one web source.
    estimated: bool = False


class PendingAction(BaseModel):
    action_id: str
    revision: int
    tool: str
    preview: str
    payload: dict[str, Any]
    payload_hash: str
    expires_at: datetime
    # Kết quả chạy thử lệnh ghi trên server (tên, ảnh, tổng, chỉ số) cho thẻ xác nhận.
    display: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    session_id: str
    run_id: str
    reply: str
    status: Literal["completed", "needs_input", "pending_confirmation", "failed"]
    intent: str | None = None
    agent_used: str = "orchestration_agent"
    pending_action: PendingAction | None = None
    clarification: Clarification | None = None
    food_gap: FoodGap | None = None
    illustrations: list[Illustration] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    # Chế độ của lượt chạy; suggested_mode='plan' khi chế độ ghi nhanh mời người dùng hỏi lại ở chế độ Plan.
    mode: Literal["normal", "plan"] | None = None
    suggested_mode: Literal["plan"] | None = None

    @field_validator("clarification", mode="before")
    @classmethod
    def _valid_frames(cls, value):
        # Phản hồi xác nhận đã lưu có thể chứa form văn bản tự do từ trước khi bắt buộc dùng khung.
        return Clarification.sanitize(value)

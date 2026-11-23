"""Schema Pydantic của miền dùng chung."""

import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    StrictFloat,
    StrictInt,
    StringConstraints,
    model_validator,
)

# --------------------------------------------------------------------------------------------------
# Hợp đồng đầu vào dùng chung. Không import ORM, settings ứng dụng hay database.
# --------------------------------------------------------------------------------------------------

def finite_json(value: Any) -> Any:
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Expected JSON with finite numbers") from exc
    return value


JsonObject = Annotated[dict[str, JsonValue], AfterValidator(finite_json)]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Name = Annotated[NonBlank, Field(max_length=255)]
PositiveMeasurement = Annotated[Decimal, Field(gt=0, lt=10000000, max_digits=10, decimal_places=3, allow_inf_nan=False)]
Percentage = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2, allow_inf_nan=False)]
# Khoảng hợp lý của con người cho số đo mới; lệnh đọc vẫn dễ dãi với các dòng cũ.
WeightKg = Annotated[Decimal, Field(ge=20, le=400, max_digits=10, decimal_places=3, allow_inf_nan=False)]
HeightCm = Annotated[Decimal, Field(ge=50, le=260, max_digits=10, decimal_places=3, allow_inf_nan=False)]
MuscleMassKg = Annotated[Decimal, Field(gt=0, le=200, max_digits=10, decimal_places=3, allow_inf_nan=False)]
BodyFatPercentage = Annotated[Decimal, Field(ge=2, le=75, max_digits=5, decimal_places=2, allow_inf_nan=False)]
FiniteNumber = StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)]
Version = Annotated[int, Field(strict=True, ge=1)]
# Ảnh catalog: URL https hoặc đường dẫn cùng origin (ví dụ /static/foods/pho.webp); không bao giờ là data: URI.
ImageUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048, pattern=r"^(https://[^\s]+|/[A-Za-z0-9._~/-]+)$")]


class InputSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    def to_payload(self) -> dict[str, Any]:
        """Giữ trường bị bỏ trống là bỏ trống; giữ null tường minh cho cột cho phép null."""
        return self.model_dump(mode="python", exclude_unset=True)


class PartialSchema(InputSchema):
    """PATCH may omit a required column, but may not explicitly clear it."""
    non_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def reject_null_columns(self) -> Self:
        for field in self.model_fields_set & self.non_nullable:
            if getattr(self, field) is None:
                raise ValueError(f"{field} may be omitted but cannot be null")
        return self


class ReadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EntityRead(ReadSchema):
    id: UUID
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version_id: int
    is_active: bool


class UserScope(InputSchema):
    user_id: UUID


class Pagination(InputSchema):
    offset: Annotated[int, Field(strict=True, ge=0)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=200)] = 50
    include_inactive: bool = False


class VersionCheck(InputSchema):
    expected_version_id: Version


class JsonObjectInput(RootModel[JsonObject]):
    """Đối tượng mở cho thao tác gộp cấp cao nhất của personal_info."""


SortDirection = Annotated[
    Literal["asc", "desc"], BeforeValidator(lambda value: value.lower() if isinstance(value, str) else value),
]


class OrderBy(RootModel[dict[str, SortDirection]]):
    pass


# --------------------------------------------------------------------------------------------------
# Kiểu giá trị dùng chung cho schema và model SQLAlchemy, không import ORM.
# --------------------------------------------------------------------------------------------------

class FoodSourceType(StrEnum):
    SYSTEM = "SYSTEM"
    CUSTOM = "CUSTOM"


class FoodItemType(StrEnum):
    FOOD = "FOOD"
    DISH = "DISH"


class FoodServingUnit(StrEnum):
    """Basis of the stored nutrient values: per serving_size grams or millilitres."""
    G = "G"
    ML = "ML"


class GoalStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------------------------------
# Nhật ký ăn uống/tập luyện thực tế; bên gọi không được truyền tổng hay cờ cũ.
#
# Tách ra từ schemas.journals trong đợt tổ chức lại theo miền.
# --------------------------------------------------------------------------------------------------

class JournalRead(EntityRead):
    image_url: str | None = None
    user_id: UUID
    name: str
    timezone: str
    note: str | None
    replaces_id: UUID | None
    source: Literal["USER", "LEGACY_IMPORT"]
    detail_status: Literal["DETAILED", "AGGREGATE_ONLY"]


# --------------------------------------------------------------------------------------------------
# Hợp đồng thời gian và số dùng chung cho kế hoạch và lịch sử hoạt động.
# --------------------------------------------------------------------------------------------------

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"


class VersionedRequest(InputSchema):
    expected_version_id: Version

    def to_payload(self):
        return self.model_dump(mode="python", exclude_unset=True, exclude={"expected_version_id"})


class ProgressRangeQuery(InputSchema):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("end_date must not precede start_date")
        if self.end_date == date.max:
            raise ValueError("Date is out of range")
        return self


class ScheduleEntryQuery(Pagination, ProgressRangeQuery):
    on_date: date | None = None

    @model_validator(mode="after")
    def date_selection(self):
        if self.on_date and (self.start_date or self.end_date):
            raise ValueError("Use on_date or date bounds, not both")
        return self


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Expected an IANA timezone") from exc
    return value


TimeZoneName = Annotated[str, AfterValidator(validate_timezone)]


def day_bounds(start: date, end: date, zone: str) -> tuple[datetime, datetime]:
    """Các ngày địa phương (tính cả hai đầu) trở thành khoảng UTC nửa mở, kể cả ngày đổi giờ mùa hè."""
    tz = ZoneInfo(validate_timezone(zone))
    return (
        datetime.combine(start, time.min, tz).astimezone(timezone.utc),
        datetime.combine(end + timedelta(days=1), time.min, tz).astimezone(timezone.utc),
    )


class DateRangeQuery(Pagination):
    start_date: date
    end_date: date
    timezone: TimeZoneName = DEFAULT_TIMEZONE

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end_date < self.start_date or self.end_date == date.max:
            raise ValueError("Invalid date range")
        return self

    def utc_bounds(self) -> tuple[datetime, datetime]:
        return day_bounds(self.start_date, self.end_date, self.timezone)


class JournalQuery(Pagination):
    on_date: date | None = None
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    recorded_from: AwareDatetime | None = None
    recorded_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.on_date is not None and (self.recorded_from is not None or self.recorded_to is not None):
            raise ValueError("Use on_date or timestamp bounds, not both")
        if self.on_date == date.max:
            raise ValueError("Date is out of range")
        if self.recorded_from and self.recorded_to and self.recorded_to <= self.recorded_from:
            raise ValueError("recorded_to must be after recorded_from")
        return self

    def utc_bounds(self) -> tuple[datetime | None, datetime | None]:
        if self.on_date is not None:
            return day_bounds(self.on_date, self.on_date, self.timezone)
        return self.recorded_from, self.recorded_to

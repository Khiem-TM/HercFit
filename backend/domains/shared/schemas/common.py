"""Hợp đồng đầu vào dùng chung. Không import ORM, settings ứng dụng hay database."""

import json
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, JsonValue,
    RootModel, StrictFloat, StrictInt, StringConstraints, model_validator,
)


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


class BulkWrite(InputSchema):
    data: Annotated[list[dict[str, Any]], Field(min_length=1)]

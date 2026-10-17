"""Shared input contracts. No ORM, application settings or database imports."""

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
FiniteNumber = StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)]
Version = Annotated[int, Field(strict=True, ge=1)]


class InputSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    def to_payload(self) -> dict[str, Any]:
        """Keep omitted fields omitted; retain explicit null for nullable columns."""
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
    """An open object for personal_info's top-level merge operation."""


SortDirection = Annotated[
    Literal["asc", "desc"], BeforeValidator(lambda value: value.lower() if isinstance(value, str) else value),
]


class OrderBy(RootModel[dict[str, SortDirection]]):
    pass


class BulkWrite(InputSchema):
    data: Annotated[list[dict[str, Any]], Field(min_length=1)]

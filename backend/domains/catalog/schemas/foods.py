from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_serializer, model_validator

from domains.shared.schemas.common import (
    EntityRead,
    ImageUrl,
    InputSchema,
    JsonObject,
    NonBlank,
    Pagination,
    PartialSchema,
    Version,
)
from domains.shared.schemas.enums import FoodItemType, FoodServingUnit, FoodSourceType

FoodCode = Annotated[NonBlank, Field(max_length=128)]
FoodName = Annotated[NonBlank, Field(max_length=512)]
Category = Annotated[str, Field(max_length=255)]
Nutrient = Annotated[Decimal, Field(ge=0, lt=1000000000000, max_digits=18, decimal_places=6, allow_inf_nan=False)]
ServingSize = Annotated[Decimal, Field(gt=0, lt=100000000, max_digits=12, decimal_places=4, allow_inf_nan=False)]


class HouseholdPortion(InputSchema):
    """A household measure of this food in its serving unit, e.g. "1 tô" = 500 G or "1 cốc" = 300 ML."""
    label: Annotated[NonBlank, Field(max_length=100)]
    quantity: ServingSize
    unit: Literal["G", "ML"]
    source: Annotated[str, Field(max_length=200)] | None = None


class FoodCreate(PartialSchema):
    name_vi: FoodName
    code: FoodCode | None = None
    name_en: Annotated[str, Field(max_length=512)] | None = None
    category_vi: Category | None = None
    category_en: Category | None = None
    item_type: FoodItemType = FoodItemType.FOOD
    serving_size: ServingSize | None = None
    serving_unit: FoodServingUnit = FoodServingUnit.G
    energy_kcal: Nutrient | None = None
    protein_g: Nutrient | None = None
    carbohydrate_g: Nutrient | None = None
    fat_g: Nutrient | None = None
    fiber_g: Nutrient | None = None
    nutrition_information: JsonObject = Field(default_factory=dict)
    data_quality: JsonObject | None = None
    image_url: ImageUrl | None = None
    portions: list[HouseholdPortion] = Field(default_factory=list, max_length=20)

    @field_serializer("portions")
    def _portions_as_json(self, portions: list[HouseholdPortion]) -> list[dict]:
        # Lưu trong cột JSONB: giữ số lượng ở dạng JSON gốc trong mọi chế độ dump.
        return [portion.model_dump(mode="json", exclude_none=True) for portion in portions]

    @model_validator(mode="after")
    def portion_units(self):
        # Khẩu phần hộ gia đình đo bằng đúng đơn vị căn cứ của món, để quy "1 tô" ra lượng ghi được.
        # Bản cập nhật một phần không mang serving_unit thì không biết đơn vị của món ở đây.
        partial = isinstance(self, FoodUpdate) and "serving_unit" not in self.model_fields_set
        if not partial and any(portion.unit != self.serving_unit for portion in self.portions):
            raise ValueError("portions must use the food serving_unit")
        return self


class SystemFoodCreate(FoodCreate):
    code: FoodCode


class FoodUpdate(FoodCreate):
    non_nullable = frozenset({"name_vi", "code"})
    name_vi: FoodName | None = None


class FoodRead(FoodCreate, EntityRead):
    code: FoodCode
    source_type: FoodSourceType
    owner_user_id: UUID | None


class FoodUpdateRequest(FoodUpdate):
    expected_version_id: Version

    def to_payload(self):
        return self.model_dump(exclude_unset=True, exclude={"expected_version_id"})


class FoodQuery(Pagination):
    search: str | None = None
    source_type: FoodSourceType | None = None
    item_type: FoodItemType | None = None
    sort: Literal["relevance", "protein_density"] = Field(
        default="relevance",
        description="protein_density: most protein per 100 kcal first (independent of the serving basis); "
                    "skips condiments, fats and physically implausible records. Use it to suggest high-protein foods.",
    )
    names: Annotated[list[Annotated[str, Field(min_length=1, max_length=80)]], Field(max_length=5)] | None = Field(
        default=None,
        description="Look up several food names in one call (max 5), e.g. for meal suggestions; returns the best "
                    "limit/len(names) matches of each name, ordered by sort. Overrides search.",
    )

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_serializer, model_validator

from schemas.common import EntityRead, ImageUrl, InputSchema, JsonObject, NonBlank, Pagination, PartialSchema, Version
from schemas.enums import FoodItemType, FoodServingUnit, FoodSourceType

FoodCode = Annotated[NonBlank, Field(max_length=128)]
FoodName = Annotated[NonBlank, Field(max_length=512)]
Category = Annotated[str, Field(max_length=255)]
Nutrient = Annotated[Decimal, Field(ge=0, lt=1000000000000, max_digits=18, decimal_places=6, allow_inf_nan=False)]
ServingSize = Annotated[Decimal, Field(gt=0, lt=100000000, max_digits=12, decimal_places=4, allow_inf_nan=False)]
PortionWeight = Annotated[Decimal, Field(gt=0, lt=100000, max_digits=12, decimal_places=4, allow_inf_nan=False)]


class HouseholdPortion(InputSchema):
    """A household measure of this food, e.g. "1 tô lớn" = 650 G or "1 suất" = 1 SERVING."""
    label: Annotated[NonBlank, Field(max_length=100)]
    quantity: ServingSize
    unit: Literal["G", "ML", "SERVING"]
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
    portion_weight_g: PortionWeight | None = None

    @field_serializer("portions")
    def _portions_as_json(self, portions: list[HouseholdPortion]) -> list[dict]:
        # Stored in a JSONB column: keep quantities JSON-native in every dump mode.
        return [portion.model_dump(mode="json", exclude_none=True) for portion in portions]

    @model_validator(mode="after")
    def portion_basis(self):
        # Validate only what this (possibly partial) payload supplies.
        if "serving_unit" in self.model_fields_set and self.serving_unit == FoodServingUnit.PORTION:
            if self.serving_size is not None and self.serving_size != 1:
                raise ValueError("PORTION foods describe exactly one serving; serving_size must be 1 or omitted")
        if self.serving_unit != FoodServingUnit.PORTION and self.portion_weight_g is not None and "serving_unit" in self.model_fields_set:
            raise ValueError("portion_weight_g applies only to PORTION foods")
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
        description="protein_density: most protein per 100 kcal first (independent of per-100 g or per-portion basis); "
                    "skips condiments, fats and physically implausible records. Use it to suggest high-protein foods.",
    )
    names: Annotated[list[Annotated[str, Field(min_length=1, max_length=80)]], Field(max_length=5)] | None = Field(
        default=None,
        description="Look up several food names in one call (max 5), e.g. for meal suggestions; returns the best "
                    "limit/len(names) matches of each name, ordered by sort. Overrides search.",
    )

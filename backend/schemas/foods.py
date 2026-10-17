from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import Field

from schemas.common import EntityRead, JsonObject, NonBlank, Pagination, PartialSchema
from schemas.enums import FoodItemType, FoodServingUnit, FoodSourceType

FoodCode = Annotated[NonBlank, Field(max_length=128)]
FoodName = Annotated[NonBlank, Field(max_length=512)]
Category = Annotated[str, Field(max_length=255)]
Nutrient = Annotated[Decimal, Field(ge=0, lt=1000000000000, max_digits=18, decimal_places=6, allow_inf_nan=False)]
ServingSize = Annotated[Decimal, Field(gt=0, lt=100000000, max_digits=12, decimal_places=4, allow_inf_nan=False)]


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


class SystemFoodCreate(FoodCreate):
    code: FoodCode


class FoodUpdate(FoodCreate):
    non_nullable = frozenset({"name_vi", "code"})
    name_vi: FoodName | None = None


class FoodRead(FoodCreate, EntityRead):
    code: FoodCode
    source_type: FoodSourceType
    owner_user_id: UUID | None


class FoodQuery(Pagination):
    search: str | None = None
    source_type: FoodSourceType | None = None
    item_type: FoodItemType | None = None

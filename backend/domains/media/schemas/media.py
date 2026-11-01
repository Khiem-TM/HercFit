from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

ImageEntity = Literal["foods", "meals", "exercises", "trainings"]


class ImageImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_url: Annotated[str, Field(max_length=2048, pattern=r"^https://\S+$")]
    expected_version_id: Annotated[int, Field(strict=True, ge=1)]


class ImageRead(BaseModel):
    entity_id: UUID
    image_url: str | None
    version_id: int

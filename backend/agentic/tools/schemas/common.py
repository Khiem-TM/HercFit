"""Tool-only request wrappers around the backend's canonical schemas."""
from datetime import date
from typing import Any
from uuid import UUID
from pydantic import Field
from schemas.common import InputSchema
from schemas.tracking import DEFAULT_TIMEZONE, TimeZoneName

class Empty(InputSchema):
    pass


class Resource(InputSchema):
    resource_id: UUID


class VersionedResource(Resource):
    expected_version_id: int = Field(ge=1, strict=True)


class PersonalInfo(InputSchema):
    personal_info: dict[str, Any]


class TimezoneQuery(InputSchema):
    timezone: TimeZoneName = DEFAULT_TIMEZONE


class TemplatePreview(InputSchema):
    resource_id: str = Field(description='Program template code from list_training_templates')
    start_date: date
    weeks: int | None = Field(default=None, ge=1, le=16)
    name: str | None = None

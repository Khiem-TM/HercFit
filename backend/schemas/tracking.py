"""Shared time and numeric contracts for plans and activity history."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, AwareDatetime, model_validator

from schemas.common import InputSchema, Pagination, Version

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
    """Inclusive local dates become a half-open UTC interval, including DST days."""
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

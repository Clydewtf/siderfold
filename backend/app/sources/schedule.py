"""UTC five-field cron matching for the explicit local scheduler command."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from collections.abc import Callable


class CronExpressionError(ValueError):
    """Raised when a source schedule is not a supported five-field cron expression."""


@dataclass(frozen=True)
class _CronField:
    values: frozenset[int]
    wildcard: bool

    def matches(self, value: int) -> bool:
        return value in self.values


def _parse_positive_int(value: str, *, field: str) -> int:
    if not value.isdigit():
        raise CronExpressionError(f"{field} must be a positive integer")
    parsed = int(value)
    if parsed <= 0:
        raise CronExpressionError(f"{field} must be greater than zero")
    return parsed


def _parse_value(
    value: str,
    *,
    minimum: int,
    maximum: int,
    field: str,
    normalise: Callable[[int], int] | None = None,
) -> int:
    if not value.isdigit():
        raise CronExpressionError(f"{field} value '{value}' must be numeric")
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise CronExpressionError(
            f"{field} value '{value}' must be between {minimum} and {maximum}"
        )
    return normalise(parsed) if normalise is not None else parsed


def _parse_field(
    expression: str,
    *,
    minimum: int,
    maximum: int,
    field: str,
    normalise: Callable[[int], int] | None = None,
) -> _CronField:
    if not expression:
        raise CronExpressionError(f"{field} must not be empty")

    values: set[int] = set()
    raw_values = set(range(minimum, maximum + 1))
    normalised_values = {
        normalise(value) if normalise is not None else value for value in raw_values
    }

    for item in expression.split(","):
        if not item:
            raise CronExpressionError(f"{field} contains an empty list item")
        parts = item.split("/")
        if len(parts) > 2:
            raise CronExpressionError(f"{field} item '{item}' has too many step separators")
        base = parts[0]
        step = _parse_positive_int(parts[1], field=field) if len(parts) == 2 else 1

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            bounds = base.split("-")
            if len(bounds) != 2 or not bounds[0] or not bounds[1]:
                raise CronExpressionError(f"{field} range '{base}' is invalid")
            start = _parse_value(
                bounds[0],
                minimum=minimum,
                maximum=maximum,
                field=field,
            )
            end = _parse_value(
                bounds[1],
                minimum=minimum,
                maximum=maximum,
                field=field,
            )
            if start > end:
                raise CronExpressionError(f"{field} range '{base}' is reversed")
        else:
            start = end = _parse_value(
                base,
                minimum=minimum,
                maximum=maximum,
                field=field,
            )

        for value in range(start, end + 1, step):
            values.add(normalise(value) if normalise is not None else value)

    return _CronField(
        values=frozenset(values),
        wildcard=values == normalised_values,
    )


@dataclass(frozen=True)
class CronSchedule:
    minute: _CronField
    hour: _CronField
    day_of_month: _CronField
    month: _CronField
    day_of_week: _CronField

    def matches(self, moment: datetime) -> bool:
        if moment.tzinfo is None:
            raise ValueError("cron matching requires a timezone-aware datetime")
        utc_moment = moment.astimezone(timezone.utc)
        if not self.minute.matches(utc_moment.minute):
            return False
        if not self.hour.matches(utc_moment.hour):
            return False
        if not self.month.matches(utc_moment.month):
            return False

        day_of_month_matches = self.day_of_month.matches(utc_moment.day)
        cron_day_of_week = (utc_moment.weekday() + 1) % 7
        day_of_week_matches = self.day_of_week.matches(cron_day_of_week)
        if self.day_of_month.wildcard or self.day_of_week.wildcard:
            return day_of_month_matches and day_of_week_matches
        return day_of_month_matches or day_of_week_matches


@lru_cache(maxsize=256)
def parse_cron_expression(expression: str) -> CronSchedule:
    fields = expression.split()
    if len(fields) != 5:
        raise CronExpressionError("schedule must contain exactly five cron fields")
    minute, hour, day_of_month, month, day_of_week = fields
    return CronSchedule(
        minute=_parse_field(minute, minimum=0, maximum=59, field="minute"),
        hour=_parse_field(hour, minimum=0, maximum=23, field="hour"),
        day_of_month=_parse_field(
            day_of_month,
            minimum=1,
            maximum=31,
            field="day-of-month",
        ),
        month=_parse_field(month, minimum=1, maximum=12, field="month"),
        day_of_week=_parse_field(
            day_of_week,
            minimum=0,
            maximum=7,
            field="day-of-week",
            normalise=lambda value: 0 if value == 7 else value,
        ),
    )


def validate_cron_expression(expression: str) -> None:
    parse_cron_expression(expression)


def is_schedule_due(schedule: str, moment: datetime) -> bool:
    if schedule == "manual":
        return False
    return parse_cron_expression(schedule).matches(moment)

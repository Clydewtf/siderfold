from datetime import datetime, timezone

import pytest

from app.sources.registry import SourceAccessMethod, SourceDefinition, SourceRegistryStatus
from app.sources.schedule import CronExpressionError, is_schedule_due, parse_cron_expression


def _definition(*, schedule: str) -> SourceDefinition:
    return SourceDefinition(
        source_key="scheduled-fixture",
        name="Scheduled fixture",
        canonical_url="https://fixture.siderfold.test/catalog",
        allowed_url_prefixes=("https://fixture.siderfold.test/catalog",),
        access_method=SourceAccessMethod.FIXTURE,
        schedule=schedule,
        status=SourceRegistryStatus.ACTIVE,
        responsible="tests",
        adapter_name="fixture-catalog",
        adapter_version="1.0.0",
        fixture_path="tests/fixtures/adapters/catalog_v1.json",
    )


def test_schedule_matches_utc_minute_and_manual_sources_are_never_due() -> None:
    moment = datetime(2026, 9, 1, 4, 15, 59, tzinfo=timezone.utc)

    assert is_schedule_due("15 4 * * *", moment)
    assert not is_schedule_due("16 4 * * *", moment)
    assert not is_schedule_due("manual", moment)


def test_schedule_supports_ranges_steps_lists_and_standard_day_or_semantics() -> None:
    monday = datetime(2026, 9, 7, 4, 10, tzinfo=timezone.utc)
    tuesday = datetime(2026, 9, 8, 4, 10, tzinfo=timezone.utc)
    fifteenth = datetime(2026, 9, 15, 4, 10, tzinfo=timezone.utc)

    assert is_schedule_due("*/5 4-5 1,15 * 1", monday)
    assert not is_schedule_due("*/5 4-5 1,15 * 1", tuesday)
    assert is_schedule_due("*/5 4-5 1,15 * 1", fifteenth)


def test_schedule_rejects_invalid_cron_fields_in_the_registry() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron_expression("60 * * * *")

    with pytest.raises(ValueError):
        _definition(schedule="* * * * 9")

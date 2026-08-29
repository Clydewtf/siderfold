from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DataError, IntegrityError

from app.domain.models import (
    FundingValueKind,
    Program,
    ProgramDeadline,
    ProgramFunding,
    ProgramGeography,
    ProgramTheme,
    PublicationStatus,
    Source,
)
from tests.fixtures.canonical import (
    FUNDING_VALUES,
    PUBLISHED_AT,
    insert_program_with_source,
    insert_source,
    seed_funding_states,
    seed_program_classifications,
)


pytestmark = pytest.mark.postgres


def test_program_requires_a_primary_source_link_at_commit(migrated_engine: Engine) -> None:
    source_id = uuid4()

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                insert(Source).values(
                    id=source_id,
                    name="Unlinked source",
                    canonical_url="https://source.example.test/unlinked",
                )
            )
            connection.execute(
                insert(Program).values(
                    id=uuid4(),
                    title="Program without a ProgramSource row",
                    publication_status=PublicationStatus.DRAFT,
                    primary_source_id=source_id,
                )
            )


def test_publication_status_values_and_timestamp_rule_are_enforced(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        program_id = insert_program_with_source(
            connection,
            source_id=source_id,
            publication_status=PublicationStatus.PUBLISHED,
            published_at=PUBLISHED_AT,
        )

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(Program.publication_status).where(Program.id == program_id)
        ) == PublicationStatus.PUBLISHED

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                insert(Program).values(
                    id=uuid4(),
                    title="Published without a publication timestamp",
                    publication_status=PublicationStatus.PUBLISHED,
                    primary_source_id=source_id,
                )
            )

    with pytest.raises((DataError, IntegrityError)):
        with migrated_engine.begin() as connection:
            connection.execute(
                insert(Program).values(
                    id=uuid4(),
                    title="Program with an invalid status",
                    publication_status="not-a-status",
                    primary_source_id=source_id,
                )
            )


@pytest.mark.parametrize(
    ("status", "published_at"),
    [
        (PublicationStatus.DRAFT, None),
        (PublicationStatus.PUBLISHED, PUBLISHED_AT),
        (PublicationStatus.ARCHIVED, PUBLISHED_AT),
    ],
)
def test_all_allowed_publication_statuses_are_persisted(
    migrated_engine: Engine,
    status: PublicationStatus,
    published_at: datetime | None,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        program_id = insert_program_with_source(
            connection,
            source_id=source_id,
            title=f"Program in {status.value}",
            publication_status=status,
            published_at=published_at,
        )

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(Program.publication_status).where(Program.id == program_id)
        ) == status


def test_deadline_is_optional_but_each_program_has_at_most_one(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        program_id = insert_program_with_source(connection, source_id=source_id)
        program_without_deadline = insert_program_with_source(
            connection,
            source_id=source_id,
            title="Program without a fixed deadline",
        )
        connection.execute(
            insert(ProgramDeadline).values(program_id=program_id, deadline_on=date(2026, 9, 15))
        )

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(ProgramDeadline.deadline_on).where(ProgramDeadline.program_id == program_id)
        ) == date(2026, 9, 15)
        assert connection.scalar(
            select(ProgramDeadline.deadline_on).where(
                ProgramDeadline.program_id == program_without_deadline
            )
        ) is None

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                insert(ProgramDeadline).values(program_id=program_id, deadline_on=date(2026, 10, 1))
            )


def test_funding_states_preserve_their_original_uncertainty(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        program_ids = seed_funding_states(connection)

    with migrated_engine.connect() as connection:
        records = {
            row.value_kind: row
            for row in connection.execute(
                select(
                    ProgramFunding.value_kind,
                    ProgramFunding.currency_code,
                    ProgramFunding.exact_amount,
                    ProgramFunding.min_amount,
                    ProgramFunding.max_amount,
                )
            ).mappings()
        }

    assert set(records) == set(FUNDING_VALUES)
    assert records[FundingValueKind.EXACT]["exact_amount"] == Decimal("500000.00")
    assert records[FundingValueKind.MINIMUM]["min_amount"] == Decimal("100000.00")
    assert records[FundingValueKind.MAXIMUM]["max_amount"] == Decimal("1000000.00")
    assert records[FundingValueKind.RANGE]["min_amount"] == Decimal("100000.00")
    assert records[FundingValueKind.RANGE]["max_amount"] == Decimal("500000.00")
    for kind in (FundingValueKind.UNKNOWN, FundingValueKind.NOT_STATED):
        assert records[kind]["currency_code"] is None
        assert records[kind]["exact_amount"] is None
        assert records[kind]["min_amount"] is None
        assert records[kind]["max_amount"] is None
        assert program_ids[kind]


def test_funding_rejects_an_invalid_range(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        program_id = insert_program_with_source(connection, source_id=source_id)

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                insert(ProgramFunding).values(
                    program_id=program_id,
                    value_kind=FundingValueKind.RANGE,
                    currency_code="RUB",
                    min_amount=Decimal("500000.00"),
                    max_amount=Decimal("100000.00"),
                )
            )


def test_geography_theme_and_deadline_fixture_are_normalized(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        program_id, geography_id, theme_id = seed_program_classifications(connection)

    with migrated_engine.connect() as connection:
        deadline = connection.scalar(
            select(ProgramDeadline.deadline_on).where(ProgramDeadline.program_id == program_id)
        )
        program_geography = connection.scalar(
            select(ProgramGeography.geography_id).where(ProgramGeography.program_id == program_id)
        )
        program_theme = connection.scalar(
            select(ProgramTheme.theme_id).where(ProgramTheme.program_id == program_id)
        )

    assert deadline == date(2026, 9, 15)
    assert program_geography == geography_id
    assert program_theme == theme_id

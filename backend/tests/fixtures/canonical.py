from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import insert, update
from sqlalchemy.engine import Connection

from app.domain.models import (
    FundingValueKind,
    Geography,
    Program,
    ProgramDeadline,
    ProgramFunding,
    ProgramGeography,
    ProgramSource,
    ProgramTheme,
    PublicationStatus,
    Source,
    Theme,
)
from tests.fixtures.provenance import create_published_provenance


OBSERVED_AT = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)
PUBLISHED_AT = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)


FUNDING_VALUES: dict[FundingValueKind, dict[str, Decimal | str | None]] = {
    FundingValueKind.EXACT: {
        "currency_code": "RUB",
        "exact_amount": Decimal("500000.00"),
        "min_amount": None,
        "max_amount": None,
    },
    FundingValueKind.MINIMUM: {
        "currency_code": "RUB",
        "exact_amount": None,
        "min_amount": Decimal("100000.00"),
        "max_amount": None,
    },
    FundingValueKind.MAXIMUM: {
        "currency_code": "RUB",
        "exact_amount": None,
        "min_amount": None,
        "max_amount": Decimal("1000000.00"),
    },
    FundingValueKind.RANGE: {
        "currency_code": "RUB",
        "exact_amount": None,
        "min_amount": Decimal("100000.00"),
        "max_amount": Decimal("500000.00"),
    },
    FundingValueKind.UNKNOWN: {
        "currency_code": None,
        "exact_amount": None,
        "min_amount": None,
        "max_amount": None,
    },
    FundingValueKind.NOT_STATED: {
        "currency_code": None,
        "exact_amount": None,
        "min_amount": None,
        "max_amount": None,
    },
}


def insert_source(connection: Connection) -> UUID:
    source_id = uuid4()
    connection.execute(
        insert(Source).values(
            id=source_id,
            name="Fixture source",
            canonical_url=f"https://source.example.test/{source_id}",
        )
    )
    return source_id


def insert_program_with_source(
    connection: Connection,
    *,
    source_id: UUID,
    program_id: UUID | None = None,
    title: str = "Fixture program",
    publication_status: PublicationStatus = PublicationStatus.DRAFT,
    published_at: datetime | None = None,
) -> UUID:
    identifier = program_id or uuid4()
    connection.execute(
        insert(Program).values(
            id=identifier,
            title=title,
            publication_status=PublicationStatus.DRAFT,
            published_at=None,
            primary_source_id=source_id,
        )
    )
    connection.execute(
        insert(ProgramSource).values(
            program_id=identifier,
            source_id=source_id,
            source_url=f"https://source.example.test/programs/{identifier}",
            observed_at=OBSERVED_AT,
        )
    )
    if publication_status != PublicationStatus.DRAFT:
        provenance = create_published_provenance(connection, source_id=source_id)
        connection.execute(
            update(Program)
            .where(Program.id == identifier)
            .values(
                publication_status=publication_status,
                published_at=published_at,
                publication_review_decision_id=provenance.review_decision_id,
                updated_at=published_at,
            )
        )
    return identifier


def seed_funding_states(connection: Connection) -> dict[FundingValueKind, UUID]:
    source_id = insert_source(connection)
    program_ids: dict[FundingValueKind, UUID] = {}
    for kind, values in FUNDING_VALUES.items():
        program_id = insert_program_with_source(
            connection,
            source_id=source_id,
            title=f"Funding fixture: {kind.value}",
        )
        connection.execute(
            insert(ProgramFunding).values(program_id=program_id, value_kind=kind, **values)
        )
        program_ids[kind] = program_id
    return program_ids


def seed_program_classifications(connection: Connection) -> tuple[UUID, UUID, UUID]:
    source_id = insert_source(connection)
    program_id = insert_program_with_source(
        connection,
        source_id=source_id,
        publication_status=PublicationStatus.PUBLISHED,
        published_at=PUBLISHED_AT,
    )
    geography_id = uuid4()
    theme_id = uuid4()
    connection.execute(insert(Geography).values(id=geography_id, slug="russia", name="Россия"))
    connection.execute(insert(Theme).values(id=theme_id, slug="education", name="Образование"))
    connection.execute(
        insert(ProgramDeadline).values(program_id=program_id, deadline_on=date(2026, 9, 15))
    )
    connection.execute(insert(ProgramGeography).values(program_id=program_id, geography_id=geography_id))
    connection.execute(insert(ProgramTheme).values(program_id=program_id, theme_id=theme_id))
    return program_id, geography_id, theme_id

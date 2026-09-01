from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.engine import Connection, Engine

from app.domain.models import (
    FundingValueKind,
    Geography,
    ProgramDeadline,
    ProgramFunding,
    ProgramGeography,
    ProgramTheme,
    PublicationStatus,
    Source,
    Theme,
)
from app.main import create_app
from tests.fixtures.canonical import PUBLISHED_AT, insert_program_with_source


pytestmark = pytest.mark.postgres


def _source(connection: Connection, name: str) -> UUID:
    source_id = uuid4()
    connection.execute(
        insert(Source).values(
            id=source_id,
            name=name,
            canonical_url=f"https://{name.lower().replace(' ', '-')}.example.test",
        )
    )
    return source_id


def _seed_public_catalog(connection: Connection, *, size: int = 72) -> dict[str, object]:
    source_ids = (
        _source(connection, "Regional Grants"),
        _source(connection, "Innovation Foundation"),
        _source(connection, "Social Initiatives"),
    )
    geography_id = uuid4()
    theme_id = uuid4()
    connection.execute(
        insert(Geography).values(id=geography_id, slug="russia", name="Russia")
    )
    connection.execute(
        insert(Theme).values(id=theme_id, slug="innovation", name="Innovation")
    )

    program_ids: list[UUID] = []
    deadline_rows: list[dict[str, object]] = []
    funding_rows: list[dict[str, object]] = []
    geography_rows: list[dict[str, object]] = []
    theme_rows: list[dict[str, object]] = []
    for index in range(size):
        is_innovation = index % 3 == 0
        program_id = insert_program_with_source(
            connection,
            source_id=source_ids[index % len(source_ids)],
            title=(
                f"Инновационный грант для команды {index:03d}"
                if is_innovation
                else f"Социальная программа поддержки {index:03d}"
            ),
            publication_status=PublicationStatus.PUBLISHED,
            published_at=PUBLISHED_AT + timedelta(minutes=index),
        )
        program_ids.append(program_id)
        deadline_rows.append(
            {
                "program_id": program_id,
                "deadline_on": date(2026, 9, 1) + timedelta(days=index),
            }
        )
        funding_rows.append(
            {
                "program_id": program_id,
                "value_kind": (
                    FundingValueKind.MAXIMUM
                    if is_innovation
                    else FundingValueKind.EXACT
                ),
                "currency_code": "RUB",
                "exact_amount": None if is_innovation else Decimal("250000.00"),
                "min_amount": None,
                "max_amount": Decimal("1000000.00") if is_innovation else None,
            }
        )
        geography_rows.append({"program_id": program_id, "geography_id": geography_id})
        if is_innovation:
            theme_rows.append({"program_id": program_id, "theme_id": theme_id})

    connection.execute(insert(ProgramDeadline), deadline_rows)
    connection.execute(insert(ProgramFunding), funding_rows)
    connection.execute(insert(ProgramGeography), geography_rows)
    connection.execute(insert(ProgramTheme), theme_rows)
    insert_program_with_source(
        connection,
        source_id=source_ids[0],
        title="Hidden draft program",
    )
    insert_program_with_source(
        connection,
        source_id=source_ids[1],
        title="Hidden archived program",
        publication_status=PublicationStatus.ARCHIVED,
        published_at=PUBLISHED_AT,
    )
    return {
        "program_ids": program_ids,
        "source_ids": source_ids,
        "published_count": size,
        "innovation_count": size // 3,
    }


def test_public_catalog_load_smoke_uses_realistic_published_fixture(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        fixture = _seed_public_catalog(connection)

    client = TestClient(create_app(engine=migrated_engine))
    started_at = perf_counter()
    responses = [
        client.get("/api/v1/programs", params={"page_size": 12, "sort": "updated_at"}),
        client.get("/api/v1/programs", params={"q": "инновационный", "page_size": 50}),
        client.get(
            "/api/v1/programs",
            params={"source_id": str(fixture["source_ids"][0]), "page_size": 50},
        ),
        client.get("/api/v1/programs", params={"theme": "innovation", "page_size": 50}),
        client.get("/api/v1/programs", params={"geography": "russia", "page_size": 100}),
        client.get("/api/v1/programs", params={"funding_kind": "maximum", "page_size": 50}),
        client.get(
            "/api/v1/programs",
            params={"deadline_from": "2026-09-10", "deadline_to": "2026-09-20"},
        ),
        client.get(f"/api/v1/programs/{fixture['program_ids'][0]}"),
        client.get("/api/v1/sources", params={"sort": "program_count", "order": "desc"}),
        client.get("/api/v1/filters"),
    ]
    elapsed_seconds = perf_counter() - started_at

    assert [response.status_code for response in responses] == [200] * len(responses)
    assert responses[0].json()["total"] == fixture["published_count"]
    assert len(responses[0].json()["items"]) == 12
    assert responses[1].json()["total"] == fixture["innovation_count"]
    assert responses[3].json()["total"] == fixture["innovation_count"]
    assert responses[4].json()["total"] == fixture["published_count"]
    assert responses[5].json()["total"] == fixture["innovation_count"]
    assert responses[6].json()["total"] == 11
    assert responses[7].json()["publication_status"] == "published"
    assert responses[8].json()["total"] == 3
    assert responses[9].json()["themes"] == [{"slug": "innovation", "name": "Innovation"}]
    assert elapsed_seconds < 3.0, f"catalog smoke took {elapsed_seconds:.3f}s"

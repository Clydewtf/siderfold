from __future__ import annotations

from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, inspect, text


CANONICAL_TABLES = {
    "geographies",
    "program_deadlines",
    "program_funding",
    "program_geographies",
    "program_sources",
    "program_themes",
    "programs",
    "sources",
    "themes",
}

PROVENANCE_TABLES = {
    "data_quality_issues",
    "ingestion_runs",
    "raw_captures",
    "review_decisions",
    "staged_records",
}


@pytest.mark.postgres
def test_b3_migration_applies_to_a_clean_database_and_rolls_back(
    alembic_config: object,
    test_database_url: str,
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    engine = create_engine(test_database_url)
    try:
        assert (CANONICAL_TABLES | PROVENANCE_TABLES).issubset(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0003_b3_provenance"
            )

        command.downgrade(alembic_config, "0002_b2_canonical_schema")

        assert CANONICAL_TABLES.issubset(inspect(engine).get_table_names())
        assert PROVENANCE_TABLES.isdisjoint(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0002_b2_canonical_schema"
            )
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")


@pytest.mark.postgres
def test_b3_upgrade_rejects_published_b2_program_without_provenance(
    alembic_config: object,
    test_database_url: str,
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "0002_b2_canonical_schema")

    source_id = uuid4()
    program_id = uuid4()
    engine = create_engine(test_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO sources (id, name, canonical_url) "
                    "VALUES (:id, :name, :canonical_url)"
                ),
                {
                    "id": source_id,
                    "name": "Legacy source",
                    "canonical_url": "https://source.example.test/legacy",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO programs "
                    "(id, title, publication_status, published_at, primary_source_id) "
                    "VALUES (:id, :title, 'published'::publication_status, now(), :source_id)"
                ),
                {
                    "id": program_id,
                    "title": "Legacy published program",
                    "source_id": source_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO program_sources (program_id, source_id, source_url, observed_at) "
                    "VALUES (:program_id, :source_id, :source_url, now())"
                ),
                {
                    "program_id": program_id,
                    "source_id": source_id,
                    "source_url": "https://source.example.test/legacy/program",
                },
            )

        engine.dispose()
        with pytest.raises(RuntimeError, match="requires provenance"):
            command.upgrade(alembic_config, "head")

        engine = create_engine(test_database_url)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0002_b2_canonical_schema"
            )
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")

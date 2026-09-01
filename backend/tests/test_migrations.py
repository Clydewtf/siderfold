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

TELEGRAM_DISCOVERY_BASE_TABLES = {
    "telegram_discovery_cursors",
    "telegram_discovery_message_urls",
    "telegram_discovery_messages",
    "telegram_discovery_urls",
}

TELEGRAM_DISCOVERY_TABLES = (
    TELEGRAM_DISCOVERY_BASE_TABLES
    | {"telegram_discovery_message_observations"}
)

REVIEW_QUEUE_TABLES = {
    "deduplication_matches",
    "review_actions",
    "review_cases",
}

DISCOVERY_REVIEW_TABLES = {
    "discovery_review_actions",
    "discovery_review_cases",
}

OPERATIONAL_TABLES = {
    "source_execution_attempts",
    "source_execution_runs",
}

PUBLIC_CATALOG_INDEXES = {
    "programs": {
        "ix_programs_publication_status_updated_at_id",
        "ix_programs_title_search",
    },
    "program_sources": {"ix_program_sources_source_id_program_id"},
    "program_deadlines": {"ix_program_deadlines_deadline_on_program_id"},
    "program_geographies": {"ix_program_geographies_geography_id_program_id"},
    "program_themes": {"ix_program_themes_theme_id_program_id"},
    "program_funding": {"ix_program_funding_value_kind_program_id"},
}


def _index_names(engine: object, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes(table_name)}


@pytest.mark.postgres
def test_provenance_migration_applies_to_a_clean_database_and_rolls_back(
    alembic_config: object,
    test_database_url: str,
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    engine = create_engine(test_database_url)
    try:
        assert (
            CANONICAL_TABLES
            | PROVENANCE_TABLES
            | TELEGRAM_DISCOVERY_TABLES
            | REVIEW_QUEUE_TABLES
            | DISCOVERY_REVIEW_TABLES
            | OPERATIONAL_TABLES
        ).issubset(inspect(engine).get_table_names())
        for table_name, expected_indexes in PUBLIC_CATALOG_INDEXES.items():
            assert expected_indexes.issubset(_index_names(engine, table_name))
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0009_public_catalog_indexes"
            )

        command.downgrade(alembic_config, "0008_c5_operations")

        for table_name, expected_indexes in PUBLIC_CATALOG_INDEXES.items():
            assert expected_indexes.isdisjoint(_index_names(engine, table_name))
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0008_c5_operations"
            )

        command.downgrade(alembic_config, "0007_discovery_review")

        assert (
            CANONICAL_TABLES
            | PROVENANCE_TABLES
            | TELEGRAM_DISCOVERY_TABLES
            | REVIEW_QUEUE_TABLES
            | DISCOVERY_REVIEW_TABLES
        ).issubset(inspect(engine).get_table_names())
        assert OPERATIONAL_TABLES.isdisjoint(inspect(engine).get_table_names())

        command.downgrade(alembic_config, "0006_c4_review_deduplication")

        assert (
            CANONICAL_TABLES
            | PROVENANCE_TABLES
            | TELEGRAM_DISCOVERY_BASE_TABLES
            | REVIEW_QUEUE_TABLES
        ).issubset(inspect(engine).get_table_names())
        assert (
            {"telegram_discovery_message_observations"} | DISCOVERY_REVIEW_TABLES
        ).isdisjoint(inspect(engine).get_table_names())

        command.downgrade(alembic_config, "0005_telegram_discovery")

        assert (
            CANONICAL_TABLES | PROVENANCE_TABLES | TELEGRAM_DISCOVERY_BASE_TABLES
        ).issubset(inspect(engine).get_table_names())
        assert (
            REVIEW_QUEUE_TABLES
            | {"telegram_discovery_message_observations"}
            | DISCOVERY_REVIEW_TABLES
        ).isdisjoint(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0005_telegram_discovery"
            )

        command.downgrade(alembic_config, "0004_adapter_run_statistics")

        assert (CANONICAL_TABLES | PROVENANCE_TABLES).issubset(inspect(engine).get_table_names())
        assert TELEGRAM_DISCOVERY_TABLES.isdisjoint(inspect(engine).get_table_names())

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
def test_provenance_upgrade_rejects_published_legacy_program_without_provenance(
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

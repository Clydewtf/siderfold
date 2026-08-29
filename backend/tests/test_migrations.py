from __future__ import annotations

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


@pytest.mark.postgres
def test_b2_migration_applies_to_a_clean_database_and_rolls_back(
    alembic_config: object,
    test_database_url: str,
) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    engine = create_engine(test_database_url)
    try:
        assert CANONICAL_TABLES.issubset(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0002_b2_canonical_schema"
            )

        command.downgrade(alembic_config, "0001_b1_baseline")

        assert CANONICAL_TABLES.isdisjoint(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0001_b1_baseline"
            )
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")

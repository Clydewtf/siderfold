from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url

from app.core.config import get_settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("prepend_sys_path", str(BACKEND_ROOT))
    return config


@pytest.fixture
def test_database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL schema tests")

    database_name = make_url(value).database
    if database_name is None or not database_name.endswith("_test"):
        raise pytest.UsageError(
            "TEST_DATABASE_URL must point to a database whose name ends in '_test'"
        )

    return value


@pytest.fixture
def alembic_config(monkeypatch: pytest.MonkeyPatch, test_database_url: str) -> Config:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    try:
        yield _alembic_config()
    finally:
        get_settings.cache_clear()


@pytest.fixture
def migrated_engine(alembic_config: Config, test_database_url: str) -> Engine:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    engine = create_engine(test_database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(alembic_config, "base")

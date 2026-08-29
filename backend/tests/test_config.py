import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_NAME", "test-backend")
    monkeypatch.setenv("PORT", "8100")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://tester:secret@db.example.test:5432/test_db",
    )

    settings = Settings()

    assert settings.app_env == "test"
    assert settings.app_name == "test-backend"
    assert settings.port == 8100
    assert settings.database_url.endswith("/test_db")


def test_settings_reject_invalid_port() -> None:
    with pytest.raises(ValidationError):
        Settings(port=0)


def test_settings_reject_non_psycopg_database_url() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///./siderfold.db")

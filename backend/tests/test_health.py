from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.main import create_app


class AvailableConnection:
    def __enter__(self) -> "AvailableConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        assert str(statement) == str(text("SELECT 1"))


class AvailableEngine:
    @contextmanager
    def connect(self) -> Iterator[AvailableConnection]:
        yield AvailableConnection()


class UnavailableEngine:
    def connect(self) -> None:
        raise OperationalError("SELECT 1", {}, ConnectionError("database is down"))


def test_health_is_live_without_database() -> None:
    client = TestClient(create_app(engine=UnavailableEngine()))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "siderfold-backend"}


def test_readiness_is_ready_when_database_check_succeeds() -> None:
    client = TestClient(create_app(engine=AvailableEngine()))

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_readiness_returns_503_when_database_is_unavailable() -> None:
    settings = Settings(database_connect_timeout_seconds=1)
    client = TestClient(create_app(settings=settings, engine=UnavailableEngine()))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}

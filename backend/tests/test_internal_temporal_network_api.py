from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine

from app.api.internal import moderation
from app.analytics.network import NETWORK_METRICS_VERSION
from app.analytics.regional import REGIONAL_INDICATORS_VERSION
from app.analytics.temporal import TEMPORAL_ANALYTICS_VERSION
from app.analytics.snapshots import INPUT_MANIFEST_VERSION, SNAPSHOT_SCOPE
from app.core.config import Settings
from app.main import create_app


AUTHORIZATION = {"Authorization": "Bearer internal-test-token"}


def _snapshot(*, version: str = INPUT_MANIFEST_VERSION) -> SimpleNamespace:
    snapshot_id = uuid4()
    manifest = {
        "version": version,
        "data_class": "synthetic",
        "as_of": "2026-09-08T12:00:00+00:00",
        "freshness_window_days": 30,
        "programs": [
            {
                "program_id": "p1",
                "source_key": "potanin-competitions",
                "published_at": "2026-08-20T10:00:00+00:00",
                "updated_at": "2026-08-29T10:00:00+00:00",
                "observed_at": "2026-09-07T10:00:00+00:00",
            }
        ],
        "taxonomy": {"themes": [], "geographies": []},
    }
    return SimpleNamespace(
        id=snapshot_id,
        scope=SNAPSHOT_SCOPE,
        calculation_version="catalog-quality/v3" if version == INPUT_MANIFEST_VERSION else "catalog-quality/v2",
        as_of=datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
        freshness_window_days=30,
        registry_fingerprint="a" * 64,
        input_fingerprint="b" * 64,
        source_scope={"program_sources": [{"source_key": "potanin-competitions"}]},
        input_manifest=manifest,
        metrics={
            "regional_indicators": {
                "version": REGIONAL_INDICATORS_VERSION,
                "snapshot_id": str(snapshot_id),
                "dimensions": {},
            }
        },
    )


def test_time_series_endpoint_is_authenticated_and_returns_parameter_metadata(monkeypatch) -> None:
    snapshot = _snapshot()
    engine = create_engine("sqlite://")
    settings = Settings(
        app_env="test",
        internal_api_token=SecretStr("internal-test-token"),
        internal_operator_id="reviewer@example.test",
    )
    monkeypatch.setattr(moderation, "list_analytics_snapshots", lambda *_args, **_kwargs: (snapshot,))

    def calculate(_snapshots, *, from_date, to_date, data_class, frequency):
        return {
            "version": TEMPORAL_ANALYTICS_VERSION,
            "frequency": frequency,
            "data_class": data_class,
            "window": {"from": from_date.isoformat(), "to": to_date.isoformat(), "timezone": "UTC"},
            "selection": "latest compatible snapshot by as_of in each UTC ISO week; no interpolation",
            "cohorts": [],
            "excluded_snapshots": {},
            "status": "no_compatible_snapshots",
            "limitations": [],
        }

    monkeypatch.setattr(moderation, "calculate_temporal_series", calculate)
    client = TestClient(create_app(settings=settings, engine=engine))
    path = "/api/internal/v1/analytics/time-series?from=2026-09-01&to=2026-09-30&data_class=synthetic"

    assert client.get(path).status_code == 401
    response = client.get(path, headers=AUTHORIZATION)
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == TEMPORAL_ANALYTICS_VERSION
    assert body["window"] == {"from": "2026-09-01", "to": "2026-09-30", "timezone": "UTC"}
    assert body["data_class"] == "synthetic"
    assert client.get(
        "/api/internal/v1/analytics/time-series?from=2026-10-01&to=2026-09-01",
        headers=AUTHORIZATION,
    ).status_code == 400
    engine.dispose()


def test_network_endpoint_returns_requested_dimension_and_rejects_legacy_snapshot(monkeypatch) -> None:
    snapshot = _snapshot()
    legacy = _snapshot(version="catalog-quality-input/v2")
    monkeypatch.setattr(
        moderation,
        "get_analytics_snapshot",
        lambda _connection, requested_id: {
            snapshot.id: snapshot,
            legacy.id: legacy,
        }.get(requested_id),
    )
    engine = create_engine("sqlite://")
    settings = Settings(
        app_env="test",
        internal_api_token=SecretStr("internal-test-token"),
        internal_operator_id="reviewer@example.test",
    )
    client = TestClient(create_app(settings=settings, engine=engine))

    path = f"/api/internal/v1/analytics/snapshots/{snapshot.id}/network?dimension=region"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=AUTHORIZATION)
    assert response.status_code == 200
    body = response.json()
    assert body["network"]["dimensions"].keys() == {"geography"}
    assert body["network"]["dimensions"]["geography"]["version"] == NETWORK_METRICS_VERSION
    assert body["network"]["limitations"]

    legacy_response = client.get(
        f"/api/internal/v1/analytics/snapshots/{legacy.id}/network",
        headers=AUTHORIZATION,
    )
    assert legacy_response.status_code == 409
    engine.dispose()

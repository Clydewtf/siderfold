from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine

from app.api.internal import moderation
from app.analytics.baseline import BASELINE_METRICS_VERSION
from app.analytics.regional import REGIONAL_INDICATORS_VERSION
from app.analytics.snapshots import INPUT_MANIFEST_V2_VERSION, INPUT_MANIFEST_VERSION
from app.core.config import Settings
from app.main import create_app


AUTHORIZATION = {"Authorization": "Bearer internal-test-token"}


def quality_metrics(snapshot_id: str, data_class: str) -> dict[str, dict[str, object]]:
    return {
        name: {
            "value": 0.5,
            "formula": "numerator / denominator; null when denominator = 0",
            "unit": "share",
            "period": {"kind": "point_in_time", "as_of": "2026-09-25T12:00:00Z"},
            "filter": "eligible records in the frozen snapshot",
            "missing": "null when the denominator is zero",
            "numerator": 1,
            "denominator": 2,
            "sample_size": 2,
            "snapshot_id": snapshot_id,
            "data_class": data_class,
            "limitation": "Connected sources only.",
        }
        for name in ("freshness", "completeness", "conflicts", "source_coverage", "review_status")
    }


def test_internal_baseline_endpoint_reads_snapshot_and_requires_auth(monkeypatch) -> None:
    snapshot_id = uuid4()
    snapshot = SimpleNamespace(
        id=snapshot_id,
        scope="published_catalog_quality",
        calculation_version="catalog-quality/v2",
        as_of=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
        input_fingerprint="a" * 64,
        source_scope={"program_sources": []},
        created_at=datetime(2026, 9, 25, 12, 1, tzinfo=timezone.utc),
        freshness_window_days=30,
        registry_fingerprint="d" * 64,
        limitations=["Connected sources only."],
        input_manifest={
            "version": INPUT_MANIFEST_VERSION,
            "data_class": "test",
        },
        metrics={
            **quality_metrics(str(snapshot_id), "test"),
            "baseline": {
                "version": BASELINE_METRICS_VERSION,
                "snapshot_id": str(snapshot_id),
                "metrics": {"opportunities.count": {"value": 0}},
            },
            "regional_indicators": {
                "version": REGIONAL_INDICATORS_VERSION,
                "snapshot_id": str(snapshot_id),
                "dimensions": {"geography": {}, "theme": {}},
            },
        },
    )
    legacy_id = uuid4()
    legacy_snapshot = SimpleNamespace(
        id=legacy_id,
        scope="published_catalog_quality",
        calculation_version="catalog-quality/v1",
        as_of=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
        input_fingerprint="b" * 64,
        input_manifest={"version": "catalog-quality-input/v1", "data_class": "test"},
        metrics={"freshness": {"value": 1.0}},
    )
    v2_id = uuid4()
    v2_snapshot = SimpleNamespace(
        id=v2_id,
        scope="published_catalog_quality",
        calculation_version="catalog-quality/v2",
        as_of=datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),
        input_fingerprint="c" * 64,
        input_manifest={"version": INPUT_MANIFEST_V2_VERSION, "data_class": "real"},
        metrics={
            "baseline": {
                "version": BASELINE_METRICS_VERSION,
                "snapshot_id": str(v2_id),
                "metrics": {"opportunities.count": {"value": 3}},
            }
        },
    )
    snapshots = {snapshot_id: snapshot, legacy_id: legacy_snapshot, v2_id: v2_snapshot}
    monkeypatch.setattr(
        moderation,
        "get_analytics_snapshot",
        lambda _connection, requested_id: snapshots.get(requested_id),
    )
    monkeypatch.setattr(moderation, "list_analytics_snapshots", lambda _connection: [snapshot])
    engine = create_engine("sqlite://")
    settings = Settings(
        app_env="test",
        internal_api_token=SecretStr("internal-test-token"),
        internal_operator_id="reviewer@example.test",
    )
    client = TestClient(create_app(settings=settings, engine=engine))
    path = f"/api/internal/v1/analytics/snapshots/{snapshot_id}/baseline"

    response = client.get(path, headers=AUTHORIZATION)
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_id"] == str(snapshot_id)
    assert body["data_class"] == "test"
    assert body["baseline"]["snapshot_id"] == str(snapshot_id)
    assert body["baseline"]["metrics"]["opportunities.count"]["value"] == 0
    regional_path = f"/api/internal/v1/analytics/snapshots/{snapshot_id}/regional-indicators"
    regional_response = client.get(regional_path, headers=AUTHORIZATION)
    assert regional_response.status_code == 200
    assert regional_response.json()["regional_indicators"]["version"] == REGIONAL_INDICATORS_VERSION
    assert regional_response.json()["data_class"] == "test"
    quality_path = f"/api/internal/v1/analytics/snapshots/{snapshot_id}/quality"
    quality_response = client.get(quality_path, headers=AUTHORIZATION)
    assert quality_response.status_code == 200
    quality_body = quality_response.json()
    assert quality_body["data_class"] == "test"
    assert quality_body["quality"]["version"] == "catalog-quality-metrics/v1"
    assert set(quality_body["quality"]["metrics"]) == {
        "freshness", "completeness", "conflicts", "source_coverage", "review_status"
    }
    assert quality_body["quality"]["metrics"]["completeness"]["snapshot_id"] == str(snapshot_id)
    listed = client.get("/api/internal/v1/analytics/snapshots", headers=AUTHORIZATION)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["capabilities"]["quality"] is True
    assert client.get(path).status_code == 401
    assert client.get(regional_path).status_code == 401
    assert client.get(quality_path).status_code == 401
    assert client.get(
        f"{path}?compare_to={uuid4()}",
        headers=AUTHORIZATION,
    ).status_code == 404
    assert client.get(
        f"/api/internal/v1/analytics/snapshots/{legacy_id}/baseline",
        headers=AUTHORIZATION,
    ).status_code == 409
    assert client.get(
        f"/api/internal/v1/analytics/snapshots/{legacy_id}/regional-indicators",
        headers=AUTHORIZATION,
    ).status_code == 409
    assert client.get(
        f"/api/internal/v1/analytics/snapshots/{legacy_id}/quality",
        headers=AUTHORIZATION,
    ).status_code == 409
    assert client.get(
        f"/api/internal/v1/analytics/snapshots/{v2_id}/baseline",
        headers=AUTHORIZATION,
    ).status_code == 200
    assert client.get(
        f"/api/internal/v1/analytics/snapshots/{v2_id}/regional-indicators",
        headers=AUTHORIZATION,
    ).status_code == 409
    assert client.get(
        f"/api/internal/v1/analytics/snapshots/{v2_id}/quality",
        headers=AUTHORIZATION,
    ).status_code == 409
    engine.dispose()

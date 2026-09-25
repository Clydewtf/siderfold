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
from app.analytics.snapshots import INPUT_MANIFEST_VERSION, INPUT_MANIFEST_V2_VERSION, SNAPSHOT_SCOPE
from app.core.config import Settings
from app.main import create_app


AUTHORIZATION = {"Authorization": "Bearer internal-test-token"}


def _snapshot(
    *,
    data_class: str = "real",
    manifest_version: str = INPUT_MANIFEST_VERSION,
    source_key: str = "potanin-competitions",
):
    snapshot_id = uuid4()
    baseline = {
        "version": BASELINE_METRICS_VERSION,
        "snapshot_id": str(snapshot_id),
        "metrics": {"opportunities.count": {"value": 4}},
    }
    metrics = {"baseline": baseline}
    if manifest_version == INPUT_MANIFEST_VERSION:
        metrics["regional_indicators"] = {
            "version": REGIONAL_INDICATORS_VERSION,
            "snapshot_id": str(snapshot_id),
        }
    return SimpleNamespace(
        id=snapshot_id,
        scope=SNAPSHOT_SCOPE,
        calculation_version="catalog-quality/v3",
        as_of=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 9, 25, 12, 1, tzinfo=timezone.utc),
        freshness_window_days=30,
        registry_fingerprint="a" * 64,
        input_fingerprint="b" * 64,
        source_scope={"program_sources": [{"source_key": source_key}]},
        input_manifest={
            "version": manifest_version,
            "data_class": data_class,
            "programs": [{"source_key": source_key}],
        },
        metrics=metrics,
        limitations=["Connected sources only."],
    )


def _client(monkeypatch, snapshots):
    monkeypatch.setattr(moderation, "list_analytics_snapshots", lambda *_args, **_kwargs: snapshots)
    engine = create_engine("sqlite://")
    settings = Settings(
        app_env="test",
        internal_api_token=SecretStr("internal-test-token"),
        internal_operator_id="researcher@example.test",
    )
    client = TestClient(create_app(settings=settings, engine=engine))
    return client, engine


def test_snapshot_list_requires_auth_and_returns_safe_capability_metadata(monkeypatch) -> None:
    old_snapshot = _snapshot(manifest_version=INPUT_MANIFEST_V2_VERSION)
    current_snapshot = _snapshot()
    synthetic_snapshot = _snapshot(data_class="synthetic")
    client, engine = _client(monkeypatch, (old_snapshot, current_snapshot, synthetic_snapshot))

    path = "/api/internal/v1/analytics/snapshots"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=AUTHORIZATION)
    assert response.status_code == 200
    body = response.json()
    items = {item["snapshot_id"]: item for item in body["items"]}
    current = items[str(current_snapshot.id)]
    assert current["data_class"] == "real"
    assert current["program_count"] == 4
    assert current["capabilities"] == {
        "baseline": True,
        "regional_indicators": True,
        "network": True,
        "temporal_series": True,
    }
    assert items[str(synthetic_snapshot.id)]["data_class"] == "synthetic"
    assert body["class_counts"] == {"real": 2, "test": 0, "synthetic": 1, "unknown": 0}
    assert not {"input_manifest", "source_scope", "review_cases", "raw_captures"}.intersection(current)
    engine.dispose()


def test_snapshot_list_marks_unsupported_source_scope_and_legacy_capabilities(monkeypatch) -> None:
    unsupported_source = _snapshot(source_key="unapproved-source")
    legacy = _snapshot(manifest_version=INPUT_MANIFEST_V2_VERSION)
    client, engine = _client(monkeypatch, (unsupported_source, legacy))

    response = client.get("/api/internal/v1/analytics/snapshots", headers=AUTHORIZATION)
    assert response.status_code == 200
    items = {item["snapshot_id"]: item for item in response.json()["items"]}
    unsupported = items[str(unsupported_source.id)]
    assert unsupported["compatible"] is False
    assert unsupported["program_source_keys"] == []
    assert "source_scope_missing_or_unapproved" in unsupported["exclusion_reasons"]

    old = items[str(legacy.id)]
    assert old["compatible"] is True
    assert old["capabilities"] == {
        "baseline": True,
        "regional_indicators": False,
        "network": False,
        "temporal_series": False,
    }
    engine.dispose()


def test_snapshot_list_folds_unknown_data_class_into_unknown_count(monkeypatch) -> None:
    unknown_snapshot = _snapshot(data_class="unrecognized")
    client, engine = _client(monkeypatch, (unknown_snapshot,))

    response = client.get("/api/internal/v1/analytics/snapshots", headers=AUTHORIZATION)
    assert response.status_code == 200
    body = response.json()
    assert body["class_counts"]["unknown"] == 1
    assert body["items"][0]["compatible"] is False
    assert "unknown_data_class" in body["items"][0]["exclusion_reasons"]
    engine.dispose()

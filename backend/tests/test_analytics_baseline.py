from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.analytics.baseline import BASELINE_METRICS_VERSION, calculate_baseline_metrics, compare_snapshot_counts
from app.analytics.snapshots import (
    CALCULATION_VERSION,
    INPUT_MANIFEST_VERSION,
    _registry_scope,
    calculate_quality_metrics,
    calculate_snapshot_metrics,
)
from app.sources.registry import DEFAULT_REGISTRY_PATH, SourceRegistry, load_registry


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "analytics" / "baseline_control_cases.json"
INPUT_FINGERPRINT = "a" * 64
SNAPSHOT_ID = "00000000-0000-5000-8000-000000000001"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _scope() -> dict[str, object]:
    return {
        "active_real_sources": [
            {"source_key": "potanin-competitions"},
            {"source_key": "timchenko-competitions"},
            {"source_key": "telegram-cptgrantov-discovery"},
        ],
        "program_sources": [
            {"source_key": "potanin-competitions"},
            {"source_key": "timchenko-competitions"},
        ],
        "excluded_sources": [{"source_key": "fixture-catalog", "reason": "fixture_access"}],
    }


def _manifest(fixture: dict[str, object]) -> dict[str, object]:
    return {
        "version": INPUT_MANIFEST_VERSION,
        "data_class": fixture["data_class"],
        "as_of": fixture["as_of"],
        "freshness_window_days": fixture["freshness_window_days"],
        "programs": fixture["programs"],
        "taxonomy": {"geographies": [], "themes": []},
        "review_cases": fixture["review_cases"],
        "source_executions": fixture["source_executions"],
        "exclusions": {
            "programs": {},
            "canonical_review_cases": {},
            "discovery_review_cases": {},
            "source_executions": {},
        },
    }


def test_control_dataset_matches_quality_and_baseline_expectations() -> None:
    fixture = _fixture()
    scope = _scope()
    manifest = _manifest(fixture)
    quality = calculate_quality_metrics(source_scope=scope, input_manifest=manifest)
    snapshot_metrics = calculate_snapshot_metrics(
        snapshot_id=SNAPSHOT_ID,
        source_scope=scope,
        input_manifest=manifest,
        input_fingerprint=INPUT_FINGERPRINT,
    )
    assert snapshot_metrics == calculate_snapshot_metrics(
        snapshot_id=SNAPSHOT_ID,
        source_scope=scope,
        input_manifest=manifest,
        input_fingerprint=INPUT_FINGERPRINT,
    )
    assert snapshot_metrics["baseline"]["version"] == BASELINE_METRICS_VERSION
    for name in ("freshness", "completeness", "conflicts", "source_coverage", "review_status"):
        metric = snapshot_metrics[name]
        assert metric["formula"]
        assert metric["unit"]
        assert metric["period"]
        assert metric["filter"]
        assert "missing" in metric
        assert "sample_size" in metric
        assert metric["snapshot_id"] == SNAPSHOT_ID
        assert metric["limitation"]
    baseline = calculate_baseline_metrics(
        source_scope=scope,
        input_manifest=manifest,
        input_fingerprint=INPUT_FINGERPRINT,
        snapshot_id=SNAPSHOT_ID,
    )
    expected = fixture["expected"]
    assert isinstance(expected, dict)

    assert baseline["version"] == BASELINE_METRICS_VERSION
    assert baseline["data_class"] == "synthetic"
    metrics = baseline["metrics"]
    assert metrics["opportunities.count"]["value"] == expected["opportunities_count"]
    for source_key, count in expected["source_counts"].items():
        assert metrics[f"opportunities.source.{source_key}.count"]["value"] == count
    assert metrics["funding.record_share"]["numerator"] == 6
    assert metrics["funding.record_share"]["denominator"] == 7
    assert metrics["funding.numeric_share"]["numerator"] == 4
    assert metrics["funding.numeric_share"]["denominator"] == 7
    assert metrics["funding.record_share"]["missing"] == {
        "missing_record": 1,
        "unknown": 1,
        "not_stated": 1,
        "numeric_kinds": {"exact": 1, "maximum": 1, "minimum": 1, "range": 1},
    }
    assert metrics["deadlines.presence_share"]["numerator"] == 5
    assert metrics["deadlines.upcoming_share"]["numerator"] == 4
    assert metrics["deadlines.overdue_count"]["value"] == 1
    for name, value in expected["upcoming_deadline_days"].items():
        assert metrics[f"deadlines.days.{name}"]["value"] == value
        assert metrics[f"deadlines.days.{name}"]["sample_size"] == 4
        assert metrics[f"deadlines.days.{name}"]["uncertainty"]["status"] == "not_computed_small_sample"
    for name, values in expected["quality"].items():
        assert quality[name]["numerator"] == values["numerator"]
        assert quality[name]["denominator"] == values["denominator"]

    for metric in metrics.values():
        assert metric["formula"]
        assert metric["unit"]
        assert metric["period"]
        assert metric["filter"]
        assert "missing" in metric
        assert "sample_size" in metric
        assert metric["snapshot_id"] == SNAPSHOT_ID
        assert metric["limitation"]


def test_twelve_amount_control_uses_r7_quantiles_and_repeatable_bootstrap() -> None:
    programs = [
        {
            "program_id": f"amount-{amount}",
            "source_key": "potanin-competitions",
            "funding_present": True,
            "funding_value_kind": "exact",
            "funding_currency_code": "RUB",
            "funding_exact_amount": f"{amount}.00",
            "funding_min_amount": None,
            "funding_max_amount": None,
            "deadline_present": False,
            "deadline_on": None,
        }
        for amount in range(100, 1300, 100)
    ]
    manifest = {
        "version": INPUT_MANIFEST_VERSION,
        "data_class": "synthetic",
        "as_of": "2026-09-01T12:00:00+00:00",
        "freshness_window_days": 30,
        "programs": programs,
        "review_cases": [],
        "source_executions": [],
    }
    args = {
        "source_scope": _scope(),
        "input_manifest": manifest,
        "input_fingerprint": INPUT_FINGERPRINT,
        "snapshot_id": SNAPSHOT_ID,
    }
    first = calculate_baseline_metrics(**args)
    second = calculate_baseline_metrics(**args)
    assert first == second
    metrics = first["metrics"]
    assert metrics["funding.quantile.RUB.exact.exact_amount.Q25"]["value"] == "375.00"
    assert metrics["funding.quantile.RUB.exact.exact_amount.median"]["value"] == "650.00"
    assert metrics["funding.quantile.RUB.exact.exact_amount.Q75"]["value"] == "925.00"
    for quantile in ("Q25", "median", "Q75"):
        uncertainty = metrics[f"funding.quantile.RUB.exact.exact_amount.{quantile}"]["uncertainty"]
        assert uncertainty["status"] == "computed"
        assert uncertainty["resamples"] == 2_000
        assert len(uncertainty["seed"]) == 64
        assert Decimal(uncertainty["lower"]) <= Decimal(uncertainty["upper"])


def test_empty_and_malformed_finance_are_explicit() -> None:
    empty_manifest = {
        "version": INPUT_MANIFEST_VERSION,
        "data_class": "synthetic",
        "as_of": "2026-09-01T12:00:00+00:00",
        "freshness_window_days": 30,
        "programs": [],
        "review_cases": [],
        "source_executions": [],
    }
    empty = calculate_baseline_metrics(
        source_scope=_scope(),
        input_manifest=empty_manifest,
        input_fingerprint=INPUT_FINGERPRINT,
        snapshot_id=SNAPSHOT_ID,
    )
    assert empty["metrics"]["opportunities.count"]["value"] == 0
    assert empty["metrics"]["funding.record_share"]["value"] is None
    assert empty["metrics"]["funding.numeric_share"]["value"] is None
    assert empty["metrics"]["funding.quantiles_status"]["value"] == "not_computed_empty_sample"
    assert empty["metrics"]["deadlines.days.median"]["value"] is None
    assert empty["metrics"]["deadlines.days.median"]["uncertainty"]["status"] == "not_computed_empty_sample"

    bad_manifest = {**empty_manifest, "programs": [{
        "program_id": "bad",
        "source_key": "potanin-competitions",
        "funding_present": True,
        "funding_value_kind": "exact",
        "funding_currency_code": "RUB",
        "funding_exact_amount": None,
        "funding_min_amount": None,
        "funding_max_amount": None,
    }]}
    with pytest.raises(ValueError, match="missing funding_exact_amount"):
        calculate_baseline_metrics(
            source_scope=_scope(),
            input_manifest=bad_manifest,
            input_fingerprint=INPUT_FINGERPRINT,
            snapshot_id=SNAPSHOT_ID,
        )


def test_research_registry_excludes_fasie_and_keeps_telegram_operational_only() -> None:
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    original = registry.get("potanin-competitions")
    assert original is not None
    extra = original.model_copy(
        update={
            "source_key": "future-active-source",
            "name": "Future active source",
            "canonical_url": "https://future.example.test/catalog",
            "allowed_url_prefixes": ("https://future.example.test/catalog",),
        }
    )
    registry = SourceRegistry(
        version=registry.version,
        sources={**registry.sources, "future-active-source": extra},
    )
    source_scope, _all_sources, active_sources = _registry_scope(registry)
    active_keys = {entry["source_key"] for entry in source_scope["active_real_sources"]}
    program_keys = {entry["source_key"] for entry in source_scope["program_sources"]}
    excluded = {
        entry["source_key"]: entry["reason"]
        for entry in source_scope["excluded_sources"]
    }
    assert "fasie-competitions" not in active_keys
    assert excluded["fasie-competitions"] == "research_protocol_exclusion"
    assert "telegram-cptgrantov-discovery" in active_keys
    assert "telegram-cptgrantov-discovery" not in program_keys
    assert "fasie-competitions" not in {
        definition.source_key for definition in active_sources.values()
    }
    assert excluded["future-active-source"] == "research_protocol_exclusion"


def test_snapshot_count_comparison_requires_same_frozen_scope() -> None:
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    baseline = {"metrics": {"opportunities.count": {"value": 9}}}
    previous = SimpleNamespace(
        id=uuid4(),
        scope="published_catalog_quality",
        calculation_version=CALCULATION_VERSION,
        registry_fingerprint="r" * 64,
        freshness_window_days=30,
        input_manifest={"data_class": "real"},
        as_of=now - timedelta(days=7),
        metrics={"baseline": {"metrics": {"opportunities.count": {"value": 7}}}},
    )
    current = SimpleNamespace(
        id=uuid4(),
        scope="published_catalog_quality",
        calculation_version=CALCULATION_VERSION,
        registry_fingerprint="r" * 64,
        freshness_window_days=30,
        input_manifest={"data_class": "real"},
        as_of=now,
        metrics={"baseline": baseline},
    )
    result = compare_snapshot_counts(current, previous)
    assert result["comparable"] is True
    assert result["opportunities_count_change"]["value"] == 2
    assert result["opportunities_count_change"]["percent_change"] == pytest.approx(2 / 7)

    current.registry_fingerprint = "x" * 64
    assert compare_snapshot_counts(current, previous)["reasons"] == [
        "different_registry_fingerprint"
    ]

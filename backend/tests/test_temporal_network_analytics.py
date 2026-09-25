from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from app.analytics.baseline import BASELINE_METRICS_VERSION
from app.analytics.network import NETWORK_METRICS_VERSION, NetworkAnalyticsError, calculate_network_metrics
from app.analytics.regional import calculate_regional_indicators
from app.analytics.temporal import (
    TEMPORAL_ANALYTICS_VERSION,
    TemporalAnalyticsError,
    calculate_temporal_series,
)
from app.analytics.snapshots import CALCULATION_VERSION, INPUT_MANIFEST_VERSION, SNAPSHOT_SCOPE


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "analytics" / "temporal_network_control_cases.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _metric(value: object, *, snapshot_id: str, sample_size: int = 1) -> dict[str, object]:
    return {
        "value": value,
        "formula": "synthetic control value",
        "unit": "RUB per program",
        "period": {"kind": "point_in_time"},
        "filter": "synthetic control fixture",
        "missing": {},
        "sample_size": sample_size,
        "snapshot_id": snapshot_id,
        "limitation": "Synthetic control only.",
    }


def _baseline(snapshot_id: str, programs: list[dict[str, object]]) -> dict[str, object]:
    missing = Counter({"missing_record": 0, "unknown": 0, "not_stated": 0})
    values: dict[tuple[str, str, str], list[Decimal]] = {}
    numeric_kinds = {"exact", "minimum", "maximum", "range"}
    for program in programs:
        if not program["funding_present"]:
            missing["missing_record"] += 1
            continue
        kind = str(program["funding_value_kind"])
        if kind in {"unknown", "not_stated"}:
            missing[kind] += 1
            continue
        currency = str(program["funding_currency_code"])
        fields = {
            "exact": (("exact_amount", "funding_exact_amount"),),
            "minimum": (("min_amount", "funding_min_amount"),),
            "maximum": (("max_amount", "funding_max_amount"),),
            "range": (("min_amount", "funding_min_amount"), ("max_amount", "funding_max_amount")),
        }[kind]
        for measure, field in fields:
            key = (currency, kind, measure)
            values.setdefault(key, []).append(Decimal(str(program[field])))
    all_count = len(programs)
    numeric_count = sum(len(rows) for (currency, kind, measure), rows in values.items() if kind != "range")
    numeric_program_count = sum(
        1 for program in programs if program["funding_value_kind"] in numeric_kinds
    )
    metrics: dict[str, object] = {
        "funding.record_share": {
            **_metric((all_count - missing["missing_record"]) / all_count if all_count else None, snapshot_id=snapshot_id, sample_size=all_count),
            "numerator": all_count - missing["missing_record"],
            "denominator": all_count,
            "missing": dict(missing),
        },
        "funding.numeric_share": {
            **_metric(numeric_program_count / all_count if all_count else None, snapshot_id=snapshot_id, sample_size=all_count),
            "numerator": numeric_program_count,
            "denominator": all_count,
            "missing": dict(missing),
        },
        "funding.quantiles_status": {
            **_metric("computed" if values else "not_computed_empty_sample", snapshot_id=snapshot_id, sample_size=numeric_count),
        },
    }
    for (currency, kind, measure), numbers in sorted(values.items()):
        ordered = sorted(numbers)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        key = f"funding.quantile.{currency}.{kind}.{measure}.median"
        metrics[key] = {
            **_metric(format(median.quantize(Decimal("0.01")), "f"), snapshot_id=snapshot_id, sample_size=len(numbers)),
            "interval": {"status": "not_computed_small_sample"},
        }
    return {
        "version": BASELINE_METRICS_VERSION,
        "snapshot_id": snapshot_id,
        "metrics": metrics,
    }


def _snapshots() -> list[SimpleNamespace]:
    fixture = _fixture()
    source_scope = fixture["source_scope"]
    snapshots: list[SimpleNamespace] = []
    for index, item in enumerate(fixture["snapshots"]):
        programs = []
        for source_program in item["programs"]:
            program = dict(source_program)
            program["deadline_present"] = program["deadline_on"] is not None
            programs.append(program)
        as_of = item["as_of"]
        manifest = {
            "version": INPUT_MANIFEST_VERSION,
            "data_class": fixture["data_class"],
            "as_of": as_of,
            "freshness_window_days": 30,
            "programs": programs,
            "taxonomy": item["taxonomy"],
            "review_cases": [],
            "source_executions": [],
            "exclusions": {},
        }
        snapshot_id = item["id"]
        regional = calculate_regional_indicators(
            source_scope=source_scope,
            input_manifest=manifest,
            snapshot_id=snapshot_id,
        )
        snapshots.append(
            SimpleNamespace(
                id=snapshot_id,
                scope=SNAPSHOT_SCOPE,
                calculation_version=CALCULATION_VERSION,
                as_of=datetime.fromisoformat(as_of),
                freshness_window_days=30,
                registry_fingerprint="a" * 64,
                input_fingerprint=f"{index + 1:064x}",
                source_scope=source_scope,
                input_manifest=manifest,
                metrics={
                    "baseline": _baseline(snapshot_id, programs),
                    "regional_indicators": regional,
                },
            )
        )
    return snapshots


def test_synthetic_weekly_series_is_reproducible_and_matches_control_values() -> None:
    fixture = _fixture()
    expected = fixture["expected"]
    snapshots = _snapshots()
    arguments = {
        "from_date": date(2026, 8, 31),
        "to_date": date(2026, 9, 30),
        "data_class": "synthetic",
    }
    first = calculate_temporal_series(snapshots, **arguments)
    second = calculate_temporal_series(snapshots, **arguments)
    assert first == second
    assert first["version"] == TEMPORAL_ANALYTICS_VERSION
    assert first["status"] == "computed"

    points = first["cohorts"][0]["points"]
    assert [point["period"]["start"] for point in points] == expected["week_starts"]
    assert [point["status"] for point in points] == expected["point_statuses"]
    assert [
        point["metrics"].get("programs.stock", {}).get("value")
        for point in points
    ] == expected["program_stock"]
    assert [
        point["metrics"].get("programs.newly_observed", {}).get("value")
        for point in points
    ] == expected["newly_observed"]
    assert [
        point["metrics"].get("programs.removed_from_published_scope", {}).get("value")
        for point in points
    ] == expected["removed_from_scope"]
    assert [
        point["metrics"].get("programs.published_since_previous", {}).get("value")
        for point in points
    ] == expected["published_since_previous"]

    week_2 = points[1]["metrics"]
    week_4 = points[4]["metrics"]
    assert week_2["deadlines"]["upcoming_or_today"]["value"] == expected["week_2_deadline_upcoming"]
    assert week_4["deadlines"]["overdue"]["value"] == expected["week_4_deadline_overdue"]
    assert week_4["deadlines"]["upcoming_or_today"]["value"] == expected["week_4_deadline_upcoming"]
    assert week_4["deadlines"]["changed_values_since_previous"]["value"] == expected["week_4_deadline_changed_values"]
    assert week_4["deadlines"]["status_transitions_since_previous"]["value"] == expected["week_4_deadline_status_transitions"]
    assert week_4["funding"]["changed_programs_since_previous"]["value"] == expected["week_4_funding_changed_programs"]
    assert week_4["taxonomy"]["theme"]["membership_changes_since_previous"]["value"] == expected["week_4_theme_membership_changed_programs"]
    assert week_4["updates"]["any_tracked_update"]["value"] == expected["week_4_any_tracked_updates"]
    assert points[4]["change_interval"]["gap_weeks"] == expected["week_4_interval_gap_weeks"]
    assert points[4]["warnings"] == ["snapshot_gap_no_interpolation"]
    assert points[2]["metrics"] == {}
    assert points[0]["metrics"]["programs.newly_observed"]["value"] is None
    assert points[0]["metrics"]["programs.newly_observed"]["status"] == "no_prior_snapshot"

    funding_metric = week_4["funding"]["snapshot_metrics"][
        "funding.quantile.RUB.exact.exact_amount.median"
    ]
    assert funding_metric["value"] == "150000.00"
    assert funding_metric["series_period"]["week_start"] == "2026-09-28"
    assert funding_metric["interval"]["status"] == "not_computed_small_sample"
    funding_record = week_4["funding"]["snapshot_metrics"]["funding.record_share"]
    assert funding_record["missing"]["missing_record"] == 1
    assert funding_record["missing"]["unknown"] == 0


def test_network_control_graphs_match_edge_weights_density_and_components() -> None:
    fixture = _fixture()
    expected = fixture["expected"]
    week_2, week_4 = _snapshots()[1:]

    week_2_network = calculate_network_metrics(week_2)
    assert week_2_network["version"] == NETWORK_METRICS_VERSION
    theme_week_2 = week_2_network["dimensions"]["theme"]
    assert theme_week_2["metrics"]["edge_count"]["value"] == expected["week_2_theme_graph"]["edge_count"]
    assert theme_week_2["metrics"]["density"]["value"] == expected["week_2_theme_graph"]["density"]
    assert theme_week_2["metrics"]["connected_components"]["value"] == expected["week_2_theme_graph"]["connected_components"]
    climate = next(node for node in theme_week_2["nodes"] if node["node_id"] == "theme:t1")
    assert climate["degree"] == 2
    assert climate["strength"] == 2

    week_4_network = calculate_network_metrics(week_4)
    for dimension in ("program", "theme", "geography"):
        expected_graph = expected[
            {
                "program": "week_4_program_graph",
                "theme": "week_4_theme_graph",
                "geography": "week_4_geography_graph",
            }[dimension]
        ]
        graph = week_4_network["dimensions"][dimension]
        assert graph["metrics"]["edge_count"]["value"] == expected_graph["edge_count"]
        assert graph["metrics"]["density"]["value"] == expected_graph["density"]
        assert graph["metrics"]["connected_components"]["value"] == expected_graph["connected_components"]
        assert graph["warnings"] == ["small_graph_no_ranking"]
        assert graph["metrics"]["degree_centrality"]["ranking"] == "not produced"


def test_empty_graph_and_invalid_or_incomparable_series_are_explicit() -> None:
    snapshot = _snapshots()[0]
    empty_manifest = {**snapshot.input_manifest, "programs": [], "taxonomy": {"themes": [], "geographies": []}}
    empty_snapshot = SimpleNamespace(
        **{
            **snapshot.__dict__,
            "input_manifest": empty_manifest,
            "metrics": {
                "baseline": _baseline(snapshot.id, []),
                "regional_indicators": calculate_regional_indicators(
                    source_scope=snapshot.source_scope,
                    input_manifest=empty_manifest,
                    snapshot_id=snapshot.id,
                ),
            },
        }
    )
    empty_network = calculate_network_metrics(empty_snapshot)
    program_graph = empty_network["dimensions"]["program"]
    assert program_graph["metrics"]["density"]["value"] is None
    assert program_graph["metrics"]["density"]["status"] == "not_defined_empty_partition"
    assert program_graph["metrics"]["connected_components"]["value"] == 2
    assert all(node["degree_centrality"] is None for node in program_graph["nodes"])

    with pytest.raises(TemporalAnalyticsError, match="from_date"):
        calculate_temporal_series(
            _snapshots(),
            from_date=date(2026, 10, 1),
            to_date=date(2026, 9, 1),
            data_class="synthetic",
        )
    result = calculate_temporal_series(
        [],
        from_date=date(2026, 9, 1),
        to_date=date(2026, 9, 7),
        data_class="synthetic",
    )
    assert result["status"] == "no_compatible_snapshots"
    assert result["cohorts"] == []

    legacy = SimpleNamespace(
        **{
            **snapshot.__dict__,
            "calculation_version": "catalog-quality/v2",
            "input_manifest": {"version": "catalog-quality-input/v2", "data_class": "synthetic"},
        }
    )
    legacy_result = calculate_temporal_series(
        [legacy],
        from_date=date(2026, 8, 31),
        to_date=date(2026, 9, 6),
        data_class="synthetic",
    )
    assert legacy_result["status"] == "no_compatible_snapshots"
    with pytest.raises(NetworkAnalyticsError, match="v3"):
        calculate_network_metrics(legacy)


def test_frequency_and_window_are_bounded() -> None:
    with pytest.raises(TemporalAnalyticsError, match="weekly"):
        calculate_temporal_series(
            _snapshots(),
            from_date=date(2026, 8, 31),
            to_date=date(2026, 9, 6),
            data_class="synthetic",
            frequency="daily",
        )
    with pytest.raises(TemporalAnalyticsError, match="cannot exceed"):
        calculate_temporal_series(
            _snapshots(),
            from_date=date(2010, 1, 1),
            to_date=date(2026, 9, 30),
            data_class="synthetic",
        )

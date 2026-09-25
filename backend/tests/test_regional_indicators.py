from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analytics.regional import (
    REGIONAL_INDICATORS_VERSION,
    RegionalIndicatorsError,
    calculate_regional_indicators,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "analytics" / "regional_indicators_control_cases.json"
SNAPSHOT_ID = "00000000-0000-5000-8000-000000000009"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _calculate(fixture: dict[str, object]) -> dict[str, object]:
    return calculate_regional_indicators(
        source_scope=fixture["source_scope"],
        input_manifest={
            "data_class": fixture["data_class"],
            "as_of": fixture["as_of"],
            "programs": fixture["programs"],
            "taxonomy": fixture["taxonomy"],
        },
        snapshot_id=SNAPSHOT_ID,
    )


def test_synthetic_control_matches_counts_shares_and_sensitivity() -> None:
    fixture = _fixture()
    expected = fixture["expected"]
    assert isinstance(expected, dict)
    first = _calculate(fixture)
    second = _calculate(fixture)

    assert first == second
    assert first["version"] == REGIONAL_INDICATORS_VERSION
    assert first["data_class"] == "synthetic"
    assert first["snapshot_id"] == SNAPSHOT_ID
    assert first["composite_index"]["status"] == "deferred"
    assert first["weight_sensitivity"]["status"] == "not_applicable_no_composite"
    assert first["taxonomy_conflicts"]["status"] == "not_recorded_by_schema"

    geography = first["dimensions"]["geography"]
    theme = first["dimensions"]["theme"]
    assert geography["coverage"]["denominator"] == expected["program_count"]
    assert geography["coverage"]["numerator"] == expected["geography_labelled"]
    assert theme["coverage"]["numerator"] == expected["theme_labelled"]
    assert {
        slug: item["numerator"] for slug, item in geography["categories"].items()
    } == expected["geography_counts"]
    assert {
        slug: item["numerator"] for slug, item in theme["categories"].items()
    } == expected["theme_counts"]

    siberia = geography["categories"]["siberia"]
    assert siberia["value"] == expected["siberia_catalog_share"]
    assert (
        siberia["sensitivity"]["labelled_only_denominator"]["value"]
        == expected["siberia_labelled_share"]
    )
    climate = theme["categories"]["climate"]
    assert (
        climate["sensitivity"]["leave_one_source_out"]["potanin-competitions"]["value"]
        == expected["climate_without_potanin_share"]
    )
    assert geography["categories"]["wide"]["warning"] is None
    assert siberia["warning"] == "small_sample"
    assert siberia["rank"] is None
    assert siberia["uncertainty"]["status"] == "not_applicable_frozen_catalog_frame"

    for dimension, expected_labelled in (
        (geography, expected["geography_labelled"]),
        (theme, expected["theme_labelled"]),
    ):
        for metric in dimension["categories"].values():
            assert metric["formula"]
            assert metric["unit"]
            assert metric["period"]
            assert metric["filter"]
            assert "missing" in metric
            assert metric["sample_size"] == metric["numerator"]
            assert metric["snapshot_id"] == SNAPSHOT_ID
            assert metric["limitation"]
            assert metric["denominator"] == expected["program_count"]
            assert metric["sensitivity"]["labelled_only_denominator"]["denominator"] == (
                expected_labelled
            )
            for scenario in metric["sensitivity"]["leave_one_source_out"].values():
                assert scenario["denominator"] is not None
                assert "value" in scenario


def test_empty_snapshot_has_null_shares_and_known_unlabelled_counts() -> None:
    result = calculate_regional_indicators(
        source_scope={"program_sources": []},
        input_manifest={
            "data_class": "synthetic",
            "as_of": "2026-09-01T12:00:00+00:00",
            "programs": [],
            "taxonomy": {"geographies": [], "themes": []},
        },
        snapshot_id=SNAPSHOT_ID,
    )

    for dimension in ("geography", "theme"):
        coverage = result["dimensions"][dimension]["coverage"]
        assert coverage["numerator"] == 0
        assert coverage["denominator"] == 0
        assert coverage["value"] is None
        assert coverage["unlabelled_programs"] == 0
        assert result["dimensions"][dimension]["categories"] == {}


def test_conflicting_taxonomy_name_for_same_slug_fails_explicitly() -> None:
    fixture = _fixture()
    manifest = {
        "data_class": fixture["data_class"],
        "as_of": fixture["as_of"],
        "programs": fixture["programs"],
        "taxonomy": {
            "geographies": [
                {"program_id": "p1", "slug": "same", "name": "Первое имя"},
                {"program_id": "p2", "slug": "same", "name": "Другое имя"},
            ],
            "themes": [],
        },
    }
    with pytest.raises(RegionalIndicatorsError, match="conflicting names"):
        calculate_regional_indicators(
            source_scope=fixture["source_scope"],
            input_manifest=manifest,
            snapshot_id=SNAPSHOT_ID,
        )


def test_unknown_taxonomy_association_is_not_inferred_or_counted_as_labelled() -> None:
    fixture = _fixture()
    manifest = {
        "data_class": fixture["data_class"],
        "as_of": fixture["as_of"],
        "programs": fixture["programs"],
        "taxonomy": {
            "geographies": [
                {"program_id": "p1", "slug": "explicit", "name": "Явная метка"},
            ],
            "themes": [],
        },
    }
    result = calculate_regional_indicators(
        source_scope=fixture["source_scope"],
        input_manifest=manifest,
        snapshot_id=SNAPSHOT_ID,
    )

    coverage = result["dimensions"]["geography"]["coverage"]
    assert coverage["numerator"] == 1
    assert coverage["unlabelled_programs"] == 7
    assert result["dimensions"]["geography"]["categories"]["explicit"]["denominator"] == 8
    assert result["dimensions"]["geography"]["categories"]["explicit"]["value"] == 0.125


def test_association_outside_frozen_program_roster_is_rejected() -> None:
    fixture = _fixture()
    manifest = {
        "data_class": fixture["data_class"],
        "as_of": fixture["as_of"],
        "programs": fixture["programs"],
        "taxonomy": {
            "geographies": [
                {"program_id": "not-in-snapshot", "slug": "wrong", "name": "Не в срезе"},
            ],
            "themes": [],
        },
    }
    with pytest.raises(RegionalIndicatorsError, match="outside the frozen roster"):
        calculate_regional_indicators(
            source_scope=fixture["source_scope"],
            input_manifest=manifest,
            snapshot_id=SNAPSHOT_ID,
        )

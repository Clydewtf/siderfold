from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


REGIONAL_INDICATORS_VERSION = "catalog-regional-indicators/v1"
MIN_CATEGORY_SAMPLE_SIZE = 5


class RegionalIndicatorsError(ValueError):
    """Raised when a frozen taxonomy manifest cannot support the indicators."""


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RegionalIndicatorsError(f"{field} must be an object")
    return value


def _rows(value: object, *, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise RegionalIndicatorsError(f"{field} must be an array")
    return [_mapping(row, field=field) for row in value]


def _share(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 12) if denominator else None


def _source_keys(source_scope: Mapping[str, Any], programs: Sequence[Mapping[str, Any]]) -> list[str]:
    keys = {
        str(program["source_key"])
        for program in programs
        if isinstance(program.get("source_key"), str) and program["source_key"]
    }
    configured = source_scope.get("program_sources", [])
    if isinstance(configured, list):
        for item in configured:
            if isinstance(item, Mapping) and isinstance(item.get("source_key"), str):
                keys.add(str(item["source_key"]))
    return sorted(keys)


def _dimension_coverage(
    *,
    dimension: str,
    assignments: Sequence[Mapping[str, Any]],
    program_sources: Mapping[str, str],
    total_programs: int,
    as_of: str,
    snapshot_id: str,
) -> tuple[dict[str, Any], dict[str, set[str]], dict[str, dict[str, str]]]:
    by_slug: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, dict[str, str]] = {}
    by_program: dict[str, set[str]] = defaultdict(set)

    for row in assignments:
        program_id = row.get("program_id")
        taxonomy_id = row.get("taxonomy_id")
        slug = row.get("slug")
        name = row.get("name")
        if not all(isinstance(value, str) and value for value in (program_id, slug, name)):
            raise RegionalIndicatorsError(
                f"{dimension} assignments require program_id, slug, and name"
            )
        if program_id not in program_sources:
            raise RegionalIndicatorsError(
                f"{dimension} assignment references a program outside the frozen roster"
            )
        current = labels.get(slug)
        normalized_label = {"slug": slug, "name": name}
        if current is not None and current != normalized_label:
            raise RegionalIndicatorsError(f"conflicting names for {dimension} slug: {slug}")
        labels[slug] = normalized_label
        # Database primary keys prevent duplicate links; set semantics make frozen
        # recalculation robust to a repeated association in a synthetic control.
        by_slug[slug].add(program_id)
        by_program[program_id].add(slug)
        if taxonomy_id is not None and not isinstance(taxonomy_id, str):
            raise RegionalIndicatorsError(f"{dimension} taxonomy_id must be a string or null")

    labelled_programs = {program_id for program_id, slugs in by_program.items() if slugs}
    coverage = {
        "formula": "count(distinct program_id with at least one explicit stored association) / count(distinct eligible program_id)",
        "unit": "share of eligible catalog programs",
        "period": f"point-in-time at {as_of}",
        "filter": "published programs in the frozen eligible source scope; explicit stored taxonomy links only",
        "missing": {
            "unlabelled_programs": total_programs - len(labelled_programs),
            "rule": "No association is unknown/unlabelled, not an inferred category or a negative fact.",
        },
        "sample_size": total_programs,
        "snapshot_id": snapshot_id,
        "limitation": "Coverage is of taxonomy links in this platform snapshot, not all eligible programs in the ecosystem.",
        "numerator": len(labelled_programs),
        "denominator": total_programs,
        "value": _share(len(labelled_programs), total_programs),
        "labelled_programs": len(labelled_programs),
        "unlabelled_programs": total_programs - len(labelled_programs),
        "assignment_rows": sum(len(program_slugs) for program_slugs in by_program.values()),
        "category_count": len(by_slug),
        "dimension": dimension,
    }
    return coverage, by_slug, labels


def _category_metric(
    *,
    dimension: str,
    slug: str,
    label: Mapping[str, str],
    program_ids: set[str],
    program_sources: Mapping[str, str],
    source_keys: Sequence[str],
    total_programs: int,
    labelled_programs: int,
    as_of: str,
    snapshot_id: str,
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    source_totals = {
        source_key: sum(source == source_key for source in program_sources.values())
        for source_key in source_keys
    }
    source_category_counts = {
        source_key: sum(program_sources[program_id] == source_key for program_id in program_ids)
        for source_key in source_keys
    }
    count = len(program_ids)
    all_share = _share(count, total_programs)
    labelled_share = _share(count, labelled_programs)
    leave_one_source_out: dict[str, dict[str, Any]] = {}
    for source_key in source_keys:
        denominator = total_programs - source_totals[source_key]
        numerator = count - source_category_counts[source_key]
        leave_one_source_out[source_key] = {
            "numerator": numerator,
            "denominator": denominator,
            "value": _share(numerator, denominator),
            "excluded_programs": source_totals[source_key],
            "status": "computed" if denominator else "not_computed_empty_denominator",
        }

    small_sample = count < MIN_CATEGORY_SAMPLE_SIZE
    warnings = ["small_sample_no_rank"] if small_sample else []
    return {
        "slug": slug,
        "label": label["name"],
        "value": all_share,
        "numerator": count,
        "denominator": total_programs,
        "formula": f"count(distinct program_id with explicit {dimension} slug = {slug!r}) / count(distinct eligible program_id)",
        "unit": "share of eligible catalog programs",
        "period": f"point-in-time at {as_of}",
        "filter": f"published programs in the frozen eligible source scope; exact stored {dimension} association; no inferred or expanded labels",
        "missing": {
            "unlabelled_programs": coverage["unlabelled_programs"],
            "rule": "Unlabelled programs stay in the catalog denominator and do not enter this category numerator; a separate labelled-only sensitivity is supplied.",
        },
        "sample_size": count,
        "snapshot_id": snapshot_id,
        "limitation": "Observed platform-catalog incidence only; not prevalence, regional demand, accessibility, quality, or whole-market coverage. Multi-label categories overlap and their shares may sum above 100%.",
        "coverage": {
            "platform_programs": total_programs,
            "taxonomy_labelled_programs": labelled_programs,
            "platform_share": coverage["value"],
            "scope": "connected eligible platform sources only",
        },
        "source_counts": source_category_counts,
        "uncertainty": {
            "status": "not_applicable_frozen_catalog_frame",
            "reason": "The value exactly describes the frozen catalog roster; there is no probability sample model for inference to the broader ecosystem.",
        },
        "warning": "small_sample" if small_sample else None,
        "warnings": warnings,
        "rank": None,
        "ranking_status": "not_produced",
        "sensitivity": {
            "labelled_only_denominator": {
                "numerator": count,
                "denominator": labelled_programs,
                "value": labelled_share,
                "status": "computed" if labelled_programs else "not_computed_empty_denominator",
            },
            "leave_one_source_out": leave_one_source_out,
            "interpretation": "Descriptive denominator/source scenarios; not confidence intervals or probability claims.",
        },
    }


def calculate_regional_indicators(
    *,
    source_scope: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    snapshot_id: str,
) -> dict[str, Any]:
    """Calculate catalog-normalized indicators from explicitly frozen taxonomy links."""

    manifest_taxonomy = input_manifest.get("taxonomy")
    if not isinstance(manifest_taxonomy, Mapping):
        raise RegionalIndicatorsError("taxonomy associations are missing from the frozen manifest")
    try:
        as_of_value = datetime.fromisoformat(str(input_manifest["as_of"]))
    except (KeyError, ValueError) as error:
        raise RegionalIndicatorsError("as_of must be an ISO-8601 timestamp") from error
    if as_of_value.tzinfo is None or as_of_value.utcoffset() is None:
        raise RegionalIndicatorsError("as_of must include a timezone")
    as_of = as_of_value.isoformat()

    programs = _rows(input_manifest.get("programs"), field="programs")
    program_sources: dict[str, str] = {}
    for row in programs:
        program_id = row.get("program_id")
        source_key = row.get("source_key")
        if not isinstance(program_id, str) or not program_id:
            raise RegionalIndicatorsError("programs require a non-empty program_id")
        if program_id in program_sources:
            raise RegionalIndicatorsError(f"duplicate program_id in frozen roster: {program_id}")
        if not isinstance(source_key, str) or not source_key:
            raise RegionalIndicatorsError("programs require a non-empty source_key")
        program_sources[program_id] = source_key

    source_keys = _source_keys(source_scope, programs)
    total_programs = len(program_sources)
    dimensions: dict[str, Any] = {}
    for dimension, manifest_key in (("geography", "geographies"), ("theme", "themes")):
        assignments = _rows(manifest_taxonomy.get(manifest_key), field=f"taxonomy.{manifest_key}")
        coverage, by_slug, labels = _dimension_coverage(
            dimension=dimension,
            assignments=assignments,
            program_sources=program_sources,
            total_programs=total_programs,
            as_of=as_of,
            snapshot_id=snapshot_id,
        )
        category_metrics = {
            slug: _category_metric(
                dimension=dimension,
                slug=slug,
                label=labels[slug],
                program_ids=program_ids,
                program_sources=program_sources,
                source_keys=source_keys,
                total_programs=total_programs,
                labelled_programs=int(coverage["labelled_programs"]),
                as_of=as_of,
                snapshot_id=snapshot_id,
                coverage=coverage,
            )
            for slug, program_ids in sorted(by_slug.items())
        }
        dimensions[dimension] = {
            "coverage": coverage,
            "categories": category_metrics,
            "multi_label": True,
            "taxonomy_hierarchy": "unavailable; labels are kept exactly as stored and are not merged across geographic levels",
        }

    return {
        "version": REGIONAL_INDICATORS_VERSION,
        "snapshot_id": snapshot_id,
        "data_class": input_manifest.get("data_class", "unknown"),
        "as_of": as_of,
        "period": f"point-in-time at {as_of}",
        "unit_of_observation": "one unique eligible Program/program_id in the immutable snapshot",
        "denominator_scope": "all eligible published programs in this platform snapshot; no external population or organization denominator is available",
        "dimensions": dimensions,
        "taxonomy_conflicts": {
            "value": None,
            "status": "not_recorded_by_schema",
            "limitation": "Taxonomy associations have no source-level provenance or conflict/review flag; coexisting labels are not automatically treated as conflicts.",
        },
        "composite_index": {
            "status": "deferred",
            "value": None,
            "weights": None,
            "reason": "The flat overlapping labels, missing external denominators, small category counts, and lack of a defined construct do not justify a single score or ranking.",
        },
        "weight_sensitivity": {
            "status": "not_applicable_no_composite",
            "reason": "No composite components or weights are defined, so weight perturbations would be arbitrary.",
        },
        "normalization": {
            "method": "within-snapshot incidence share",
            "z_scores": "not computed because categories are overlapping and not guaranteed to be at the same geographic level; reference-group comparisons would be unstable and ambiguous",
            "external_denominators": "not available",
        },
        "limitations": [
            "The indicators describe only the frozen set from eligible connected sources; they do not estimate the complete Russian opportunity ecosystem.",
            "Geography and theme are multi-label associations. Category shares are non-exclusive and may sum above 100%.",
            "No taxonomy hierarchy, assignment provenance, or taxonomy conflict state is stored in the current schema.",
            f"Groups with fewer than {MIN_CATEGORY_SAMPLE_SIZE} tagged programs are explicitly marked small_sample; no regional/theme ranks are produced.",
            "No confidence intervals are calculated for this complete frozen catalog frame; source-removal and labelled-denominator scenarios are descriptive sensitivity checks only.",
        ],
    }

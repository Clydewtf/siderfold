from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.analytics.baseline import BASELINE_METRICS_VERSION
from app.analytics.network import calculate_network_metrics
from app.analytics.regional import REGIONAL_INDICATORS_VERSION
from app.analytics.snapshots import (
    CALCULATION_VERSION,
    INPUT_MANIFEST_VERSION,
    PROGRAM_SOURCE_KEYS,
    SNAPSHOT_SCOPE,
)


TEMPORAL_ANALYTICS_VERSION = "catalog-temporal/v1"
SUPPORTED_FREQUENCY = "weekly"
MAX_SERIES_WEEKS = 520


class TemporalAnalyticsError(ValueError):
    """Raised when a frozen snapshot series cannot be compared safely."""


def _attr(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _rows(value: object, *, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise TemporalAnalyticsError(f"{field} must be an array of objects")
    return list(value)


def _timestamp(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise TemporalAnalyticsError(f"{field} must be an ISO-8601 timestamp") from error
    else:
        raise TemporalAnalyticsError(f"{field} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TemporalAnalyticsError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _snapshot_id(snapshot: object) -> str:
    value = _attr(snapshot, "id")
    if value is None:
        raise TemporalAnalyticsError("snapshot requires an id")
    normalized = str(value)
    if not normalized:
        raise TemporalAnalyticsError("snapshot requires an id")
    return normalized


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _week_range(start: date, end: date) -> list[date]:
    first = _week_start(start)
    last = _week_start(end)
    result: list[date] = []
    cursor = first
    while cursor <= last:
        result.append(cursor)
        cursor += timedelta(days=7)
    if len(result) > MAX_SERIES_WEEKS:
        raise TemporalAnalyticsError(f"time-series range cannot exceed {MAX_SERIES_WEEKS} weeks")
    return result


def _cohort_key(snapshot: object) -> tuple[str, str, int, str, str]:
    input_manifest = _attr(snapshot, "input_manifest")
    if not isinstance(input_manifest, Mapping):
        raise TemporalAnalyticsError("snapshot input_manifest must be an object")
    return (
        str(_attr(snapshot, "scope")),
        str(_attr(snapshot, "calculation_version")),
        int(_attr(snapshot, "freshness_window_days", 0)),
        str(_attr(snapshot, "registry_fingerprint", "")),
        str(input_manifest.get("data_class", "unknown")),
    )


def _validate_supported_snapshot(snapshot: object) -> tuple[str, datetime, tuple[str, str, int, str, str]]:
    snapshot_id = _snapshot_id(snapshot)
    as_of = _timestamp(_attr(snapshot, "as_of"), field="snapshot.as_of")
    cohort = _cohort_key(snapshot)
    input_manifest = _attr(snapshot, "input_manifest")
    metrics = _attr(snapshot, "metrics")
    if cohort[0] != SNAPSHOT_SCOPE or cohort[1] != CALCULATION_VERSION:
        raise TemporalAnalyticsError("time-series analytics requires catalog-quality/v3 snapshots")
    if cohort[2] < 1 or not cohort[3]:
        raise TemporalAnalyticsError("snapshot requires freshness window and registry fingerprint")
    if input_manifest.get("version") != INPUT_MANIFEST_VERSION:
        raise TemporalAnalyticsError("time-series analytics requires catalog-quality-input/v3")
    if input_manifest.get("freshness_window_days") != cohort[2]:
        raise TemporalAnalyticsError("snapshot freshness window conflicts with the frozen manifest")
    manifest_as_of = _timestamp(input_manifest.get("as_of"), field="manifest.as_of")
    if manifest_as_of != as_of:
        raise TemporalAnalyticsError("snapshot as_of conflicts with the frozen manifest")
    if not isinstance(metrics, Mapping):
        raise TemporalAnalyticsError("snapshot metrics must be an object")
    baseline = metrics.get("baseline")
    regional = metrics.get("regional_indicators")
    if (
        not isinstance(baseline, Mapping)
        or baseline.get("version") != BASELINE_METRICS_VERSION
        or baseline.get("snapshot_id") != snapshot_id
    ):
        raise TemporalAnalyticsError("snapshot has no matching reproducible E2 baseline")
    if (
        not isinstance(regional, Mapping)
        or regional.get("version") != REGIONAL_INDICATORS_VERSION
        or regional.get("snapshot_id") != snapshot_id
        or regional.get("data_class") != cohort[4]
    ):
        raise TemporalAnalyticsError("snapshot has no matching reproducible E3 indicators")
    if not isinstance(cohort[4], str) or not cohort[4]:
        raise TemporalAnalyticsError("snapshot data_class must be known")
    return snapshot_id, as_of, cohort


def _programs(snapshot: object) -> dict[str, Mapping[str, Any]]:
    manifest = _attr(snapshot, "input_manifest")
    source_scope = _attr(snapshot, "source_scope")
    if not isinstance(source_scope, Mapping):
        raise TemporalAnalyticsError("snapshot source_scope must be an object")
    source_entries = _rows(source_scope.get("program_sources"), field="source_scope.program_sources")
    allowed_source_keys = {
        row["source_key"]
        for row in source_entries
        if isinstance(row.get("source_key"), str) and row["source_key"] in PROGRAM_SOURCE_KEYS
    }
    result: dict[str, Mapping[str, Any]] = {}
    as_of = _timestamp(_attr(snapshot, "as_of"), field="snapshot.as_of")
    for program in _rows(manifest.get("programs"), field="programs"):
        program_id = program.get("program_id")
        if not isinstance(program_id, str) or not program_id:
            raise TemporalAnalyticsError("programs require a non-empty program_id")
        if program_id in result:
            raise TemporalAnalyticsError(f"duplicate program_id in snapshot manifest: {program_id}")
        if program.get("source_key") not in allowed_source_keys:
            raise TemporalAnalyticsError("program source is outside the frozen eligible source scope")
        for field in ("published_at", "updated_at", "observed_at"):
            parsed = _timestamp(program.get(field), field=f"programs[].{field}")
            if parsed > as_of:
                raise TemporalAnalyticsError(f"programs[].{field} is after snapshot.as_of")
        deadline = program.get("deadline_on")
        deadline_present = program.get("deadline_present")
        if not isinstance(deadline_present, bool) or deadline_present != (deadline is not None):
            raise TemporalAnalyticsError("deadline_present conflicts with deadline_on")
        if deadline is not None:
            if not isinstance(deadline, str):
                raise TemporalAnalyticsError("deadline_on must be an ISO date string")
            try:
                parsed_deadline = date.fromisoformat(deadline)
            except ValueError as error:
                raise TemporalAnalyticsError("deadline_on must be an ISO date string") from error
            if parsed_deadline.isoformat() != deadline:
                raise TemporalAnalyticsError("deadline_on must use canonical YYYY-MM-DD form")
        result[program_id] = program
    return result


def _funding_signature(program: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        program.get("funding_present"),
        program.get("funding_value_kind"),
        program.get("funding_currency_code"),
        program.get("funding_exact_amount"),
        program.get("funding_min_amount"),
        program.get("funding_max_amount"),
    )


def _taxonomy_by_program(
    snapshot: object,
    programs: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, set[str]]], dict[str, dict[str, dict[str, str]]]]:
    manifest = _attr(snapshot, "input_manifest")
    taxonomy = manifest.get("taxonomy")
    if not isinstance(taxonomy, Mapping):
        raise TemporalAnalyticsError("catalog-quality-input/v3 requires frozen taxonomy links")
    assignments: dict[str, dict[str, set[str]]] = {
        program_id: {"theme": set(), "geography": set()}
        for program_id in programs
    }
    labels: dict[str, dict[str, dict[str, str]]] = {"theme": {}, "geography": {}}
    for dimension, manifest_key in (("theme", "themes"), ("geography", "geographies")):
        for row in _rows(taxonomy.get(manifest_key), field=f"taxonomy.{manifest_key}"):
            program_id = row.get("program_id")
            taxonomy_id = row.get("taxonomy_id")
            slug = row.get("slug")
            name = row.get("name")
            if program_id not in programs:
                raise TemporalAnalyticsError("taxonomy association points outside the frozen program roster")
            if not all(isinstance(value, str) and value for value in (taxonomy_id, slug, name)):
                raise TemporalAnalyticsError("taxonomy links require taxonomy_id, slug, and name")
            taxonomy_key = str(taxonomy_id)
            label = {"taxonomy_id": taxonomy_key, "slug": str(slug), "name": str(name)}
            prior = labels[dimension].get(taxonomy_key)
            if prior is not None and prior != label:
                raise TemporalAnalyticsError(f"conflicting {dimension} labels for taxonomy_id {taxonomy_key}")
            labels[dimension][taxonomy_key] = label
            assignments[str(program_id)][dimension].add(taxonomy_key)

    _check_regional_metric_consistency(snapshot, programs, assignments, labels)
    return assignments, labels


def _check_regional_metric_consistency(
    snapshot: object,
    programs: Mapping[str, Mapping[str, Any]],
    assignments: Mapping[str, Mapping[str, set[str]]],
    labels: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> None:
    metrics = _attr(snapshot, "metrics")
    regional = metrics["regional_indicators"]
    dimensions = regional.get("dimensions")
    if not isinstance(dimensions, Mapping):
        raise TemporalAnalyticsError("stored E3 dimensions must be an object")
    for dimension in ("theme", "geography"):
        stored_dimension = dimensions.get(dimension)
        if not isinstance(stored_dimension, Mapping):
            raise TemporalAnalyticsError(f"stored E3 {dimension} metrics are missing")
        coverage = stored_dimension.get("coverage")
        categories = stored_dimension.get("categories")
        if not isinstance(coverage, Mapping) or not isinstance(categories, Mapping):
            raise TemporalAnalyticsError(f"stored E3 {dimension} coverage is invalid")
        labelled_ids = {
            program_id for program_id in programs if assignments[program_id][dimension]
        }
        if coverage.get("denominator") != len(programs):
            raise TemporalAnalyticsError("stored E3 program denominator differs from the frozen roster")
        if coverage.get("labelled_programs") != len(labelled_ids):
            raise TemporalAnalyticsError("stored E3 taxonomy coverage differs from the frozen manifest")
        counts_by_slug: Counter[str] = Counter()
        for program_id in programs:
            for taxonomy_id in assignments[program_id][dimension]:
                counts_by_slug[labels[dimension][taxonomy_id]["slug"]] += 1
        if set(categories) != set(counts_by_slug):
            raise TemporalAnalyticsError("stored E3 categories differ from the frozen manifest")
        for slug, count in counts_by_slug.items():
            metric = categories.get(slug)
            if not isinstance(metric, Mapping) or metric.get("numerator") != count:
                raise TemporalAnalyticsError("stored E3 category count differs from the frozen manifest")


def _metric(
    *,
    value: int | float | None,
    formula: str,
    unit: str,
    sample_size: int,
    snapshot_id: str,
    week_start: date,
    week_end: date,
    filter_description: str,
    limitation: str,
    missing: Mapping[str, Any] | str = "None for an observed snapshot; no missing values are converted to zero.",
    status: str = "computed",
    compared_snapshot_id: str | None = None,
    interval_start: datetime | None = None,
    interval_end: datetime | None = None,
    interval_gap_weeks: int | None = None,
) -> dict[str, Any]:
    period: dict[str, Any] = {
        "kind": "utc_iso_week_snapshot",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "snapshot_id": snapshot_id,
    }
    if interval_start is not None and interval_end is not None:
        period["change_interval_start"] = interval_start.isoformat()
        period["change_interval_end"] = interval_end.isoformat()
        period["change_interval_days"] = (interval_end - interval_start).total_seconds() / 86_400
        period["gap_weeks"] = interval_gap_weeks
    return {
        "value": value,
        "formula": formula,
        "unit": unit,
        "period": period,
        "filter": filter_description,
        "missing": missing,
        "sample_size": sample_size,
        "snapshot_id": snapshot_id,
        "compared_snapshot_id": compared_snapshot_id,
        "limitation": limitation,
        "status": status,
    }


def _assignments_per_category(
    programs: Mapping[str, Mapping[str, Any]],
    assignments: Mapping[str, Mapping[str, set[str]]],
    labels: Mapping[str, Mapping[str, Mapping[str, str]]],
    dimension: str,
) -> tuple[dict[str, int], int]:
    counts: Counter[str] = Counter()
    labelled: set[str] = set()
    for program_id in programs:
        category_ids = assignments[program_id][dimension]
        if category_ids:
            labelled.add(program_id)
        counts.update(category_ids)
    return dict(counts), len(labelled)


def _funding_metrics(snapshot: object, *, week_start: date, week_end: date) -> dict[str, Any]:
    snapshot_id = _snapshot_id(snapshot)
    metrics = _attr(snapshot, "metrics")
    baseline = metrics["baseline"]
    baseline_metrics = baseline.get("metrics")
    if not isinstance(baseline_metrics, Mapping):
        raise TemporalAnalyticsError("stored baseline metrics must be an object")
    result: dict[str, Any] = {}
    for key, raw_metric in sorted(baseline_metrics.items()):
        if not isinstance(key, str) or not key.startswith("funding."):
            continue
        if not isinstance(raw_metric, Mapping):
            raise TemporalAnalyticsError(f"stored baseline metric {key} must be an object")
        if raw_metric.get("snapshot_id") != snapshot_id:
            raise TemporalAnalyticsError(f"stored baseline metric {key} references another snapshot")
        result[key] = {
            **dict(raw_metric),
            "series_period": {
                "kind": "utc_iso_week_snapshot",
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "snapshot_id": snapshot_id,
            },
        }
    return result


def _snapshot_data(snapshot: object) -> dict[str, Any]:
    programs = _programs(snapshot)
    assignments, labels = _taxonomy_by_program(snapshot, programs)
    return {
        "programs": programs,
        "assignments": assignments,
        "labels": labels,
    }


def _series_point(
    *,
    snapshot: object,
    previous_snapshot: object | None,
    week_start: date,
    requested_from: date,
    requested_to: date,
    cohort_categories: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> dict[str, Any]:
    snapshot_id, as_of, _cohort = _validate_supported_snapshot(snapshot)
    week_end = week_start + timedelta(days=6)
    point_period = {
        "kind": "utc_iso_week",
        "start": week_start.isoformat(),
        "end": week_end.isoformat(),
        "partial": week_start < requested_from or week_end > requested_to,
    }
    current_data = _snapshot_data(snapshot)
    current_programs = current_data["programs"]
    previous_data = _snapshot_data(previous_snapshot) if previous_snapshot is not None else None
    previous_programs = previous_data["programs"] if previous_data is not None else {}
    previous_id = _snapshot_id(previous_snapshot) if previous_snapshot is not None else None
    previous_as_of = (
        _timestamp(_attr(previous_snapshot, "as_of"), field="previous_snapshot.as_of")
        if previous_snapshot is not None
        else None
    )
    gap_weeks = (
        max(0, (_week_start(as_of.date()) - _week_start(previous_as_of.date())).days // 7 - 1)
        if previous_as_of is not None
        else None
    )
    gap_warning = gap_weeks is not None and gap_weeks > 0
    interval_arguments = {
        "compared_snapshot_id": previous_id,
        "interval_start": previous_as_of,
        "interval_end": as_of if previous_as_of is not None else None,
        "interval_gap_weeks": gap_weeks,
    }
    eligible_programs = len(current_programs)
    filter_description = (
        "published catalog programs from the frozen program_sources scope; FASIE, "
        "Telegram discovery, and fixture sources excluded"
    )
    base_limitation = (
        "Describes the connected platform catalog snapshot only; it is not an estimate of the full ecosystem."
    )
    metrics: dict[str, Any] = {
        "programs.stock": _metric(
            value=eligible_programs,
            formula="count(distinct program_id in current snapshot manifest)",
            unit="published catalog programs",
            sample_size=eligible_programs,
            snapshot_id=snapshot_id,
            week_start=week_start,
            week_end=week_end,
            filter_description=filter_description,
            limitation=base_limitation,
        ),
        "programs.newly_observed": _metric(
            value=(len(set(current_programs) - set(previous_programs)) if previous_snapshot else None),
            formula="count(current program_id not present in previous comparable snapshot)",
            unit="programs per capture interval",
            sample_size=(len(set(current_programs) | set(previous_programs)) if previous_snapshot else eligible_programs),
            snapshot_id=snapshot_id,
            week_start=week_start,
            week_end=week_end,
            filter_description=filter_description,
            limitation="First detection is interval-censored; it does not establish when the opportunity first existed at its source.",
            missing=(
                "No previous comparable snapshot; value is undefined, not zero."
                if previous_snapshot is None
                else "Programs outside the frozen source scope are excluded."
            ),
            status="no_prior_snapshot" if previous_snapshot is None else "computed",
            **interval_arguments,
        ),
        "programs.removed_from_published_scope": _metric(
            value=(len(set(previous_programs) - set(current_programs)) if previous_snapshot else None),
            formula="count(previous program_id not present in current comparable snapshot)",
            unit="programs per capture interval",
            sample_size=(len(set(current_programs) | set(previous_programs)) if previous_snapshot else eligible_programs),
            snapshot_id=snapshot_id,
            week_start=week_start,
            week_end=week_end,
            filter_description=filter_description,
            limitation="Disappearance can reflect archive, correction, source-scope change, or missing capture; it is not proof that an opportunity closed.",
            missing="No previous comparable snapshot; value is undefined, not zero."
            if previous_snapshot is None
            else "Only IDs in both frozen frames can be used for field-level changes.",
            status="no_prior_snapshot" if previous_snapshot is None else "computed",
            **interval_arguments,
        ),
        "programs.published_since_previous": _metric(
            value=(
                sum(
                    previous_as_of
                    < _timestamp(program["published_at"], field="programs[].published_at")
                    <= as_of
                    for program in current_programs.values()
                )
                if previous_as_of is not None
                else None
            ),
            formula="count(current program with previous.as_of < Program.published_at <= current.as_of)",
            unit="programs published in Siderfold per capture interval",
            sample_size=eligible_programs,
            snapshot_id=snapshot_id,
            week_start=week_start,
            week_end=week_end,
            filter_description=filter_description,
            limitation="Program.published_at records publication in this application, not original publication at the external source.",
            missing="No previous comparable snapshot; value is undefined, not zero."
            if previous_snapshot is None
            else "Only programs present in the current published frame are counted.",
            status="no_prior_snapshot" if previous_snapshot is None else "computed",
            **interval_arguments,
        ),
    }

    deadline_counts = Counter({"with_date": 0, "upcoming_or_today": 0, "overdue": 0, "missing": 0})
    for program in current_programs.values():
        deadline = program.get("deadline_on")
        if deadline is None:
            deadline_counts["missing"] += 1
        else:
            deadline_counts["with_date"] += 1
            if date.fromisoformat(str(deadline)) < as_of.date():
                deadline_counts["overdue"] += 1
            else:
                deadline_counts["upcoming_or_today"] += 1
    deadlines: dict[str, Any] = {}
    for state, count in deadline_counts.items():
        deadlines[state] = _metric(
            value=count,
            formula=(
                "count(programs with deadline_on < as_of.date)"
                if state == "overdue"
                else "count(programs with deadline_on >= as_of.date)"
                if state == "upcoming_or_today"
                else "count(programs with deadline_on)"
                if state == "with_date"
                else "count(programs without deadline_on)"
            ),
            unit="programs",
            sample_size=eligible_programs,
            snapshot_id=snapshot_id,
            week_start=week_start,
            week_end=week_end,
            filter_description=filter_description,
            limitation="Only the one canonical ProgramDeadline.deadline_on frozen in the manifest is represented; expiration does not prove a source-announced closure.",
            missing={"no_deadline_on": deadline_counts["missing"]},
        )
    common_ids = set(current_programs) & set(previous_programs)
    deadline_changes = sum(
        current_programs[program_id].get("deadline_on")
        != previous_programs[program_id].get("deadline_on")
        for program_id in common_ids
    )
    deadline_status_changes = 0
    for program_id in common_ids:
        old_value = previous_programs[program_id].get("deadline_on")
        new_value = current_programs[program_id].get("deadline_on")
        old_status = (
            "missing"
            if old_value is None
            else "overdue"
            if date.fromisoformat(str(old_value)) < previous_as_of.date()
            else "upcoming_or_today"
        )
        new_status = (
            "missing"
            if new_value is None
            else "overdue"
            if date.fromisoformat(str(new_value)) < as_of.date()
            else "upcoming_or_today"
        )
        deadline_status_changes += old_status != new_status
    deadlines["changed_values_since_previous"] = _metric(
        value=deadline_changes if previous_snapshot else None,
        formula="count(common program_id with different deadline_on values)",
        unit="programs per capture interval",
        sample_size=len(common_ids),
        snapshot_id=snapshot_id,
        week_start=week_start,
        week_end=week_end,
        filter_description=filter_description,
        limitation="Measures changed recorded dates between samples; it does not record the source's reason for a change.",
        missing="No previous comparable snapshot; value is undefined, not zero."
        if previous_snapshot is None
        else "Programs entering or leaving the roster are counted in separate intake/removal metrics.",
        status="no_prior_snapshot" if previous_snapshot is None else "computed",
        **interval_arguments,
    )
    deadlines["status_transitions_since_previous"] = _metric(
        value=deadline_status_changes if previous_snapshot else None,
        formula="count(common program_id whose deadline state changed between snapshot as_of dates)",
        unit="programs per capture interval",
        sample_size=len(common_ids),
        snapshot_id=snapshot_id,
        week_start=week_start,
        week_end=week_end,
        filter_description=filter_description,
        limitation="A transition can occur because time passed even when deadline_on stayed unchanged; it is not an explicit source closure signal.",
        missing="No previous comparable snapshot; value is undefined, not zero."
        if previous_snapshot is None
        else "Only programs present in both snapshots are compared.",
        status="no_prior_snapshot" if previous_snapshot is None else "computed",
        **interval_arguments,
    )
    metrics["deadlines"] = deadlines

    funding_changes = sum(
        _funding_signature(current_programs[program_id])
        != _funding_signature(previous_programs[program_id])
        for program_id in common_ids
    )
    metrics["funding"] = {
        "snapshot_metrics": _funding_metrics(snapshot, week_start=week_start, week_end=week_end),
        "changed_programs_since_previous": _metric(
            value=funding_changes if previous_snapshot else None,
            formula="count(common program_id with changed funding presence, kind, currency, or amount bounds)",
            unit="programs per capture interval",
            sample_size=len(common_ids),
            snapshot_id=snapshot_id,
            week_start=week_start,
            week_end=week_end,
            filter_description=filter_description,
            limitation="Funding values remain separate by currency and exact/minimum/maximum/range-bound kind; no currency conversion or grant-scope inference is performed.",
            missing="unknown, not_stated, and missing funding rows remain distinct; no-prior-snapshot changes are undefined.",
            status="no_prior_snapshot" if previous_snapshot is None else "computed",
            **interval_arguments,
        ),
    }

    current_categories: dict[str, dict[str, int]] = {}
    current_labelled: dict[str, int] = {}
    taxonomy_output: dict[str, Any] = {}
    for dimension in ("theme", "geography"):
        counts, labelled_count = _assignments_per_category(
            current_programs,
            current_data["assignments"],
            current_data["labels"],
            dimension,
        )
        current_categories[dimension] = counts
        current_labelled[dimension] = labelled_count
        previous_assignments = previous_data["assignments"] if previous_data is not None else {}
        changed_membership = (
            sum(
                current_data["assignments"][program_id][dimension]
                != previous_assignments[program_id][dimension]
                for program_id in common_ids
            )
            if previous_data is not None
            else None
        )
        categories: dict[str, Any] = {}
        known_categories = cohort_categories.get(dimension, {})
        for taxonomy_id in sorted(known_categories):
            label = current_data["labels"][dimension].get(
                taxonomy_id,
                known_categories[taxonomy_id],
            )
            count = counts.get(taxonomy_id, 0)
            categories[taxonomy_id] = {
                "taxonomy_id": taxonomy_id,
                "slug": label["slug"],
                "label": label["name"],
                "category_present_in_snapshot": taxonomy_id in current_data["labels"][dimension],
                "count": _metric(
                    value=count,
                    formula=f"count(distinct program_id with explicit {dimension} taxonomy_id)",
                    unit="published catalog programs",
                    sample_size=eligible_programs,
                    snapshot_id=snapshot_id,
                    week_start=week_start,
                    week_end=week_end,
                    filter_description=filter_description,
                    limitation="Explicit platform taxonomy incidence only; category levels and whole-market coverage are unavailable.",
                    missing={"unlabelled_programs": eligible_programs - labelled_count},
                ),
                "share": _metric(
                    value=count / eligible_programs if eligible_programs else None,
                    formula="category program count / all eligible snapshot programs",
                    unit="share of eligible catalog programs",
                    sample_size=eligible_programs,
                    snapshot_id=snapshot_id,
                    week_start=week_start,
                    week_end=week_end,
                    filter_description=filter_description,
                    limitation="Multi-label categories overlap; shares are not exclusive and are not population prevalence.",
                    missing={"unlabelled_programs": eligible_programs - labelled_count},
                    status="computed" if eligible_programs else "not_computed_empty_denominator",
                ),
            }
        taxonomy_output[dimension] = {
            "coverage": {
                "labelled_programs": _metric(
                    value=labelled_count,
                    formula=f"count(programs with at least one explicit {dimension} association)",
                    unit="published catalog programs",
                    sample_size=eligible_programs,
                    snapshot_id=snapshot_id,
                    week_start=week_start,
                    week_end=week_end,
                    filter_description=filter_description,
                    limitation="Unlabelled programs remain in the platform denominator; taxonomy coverage is not source or market coverage.",
                    missing={"unlabelled_programs": eligible_programs - labelled_count},
                ),
                "unlabelled_programs": eligible_programs - labelled_count,
            },
            "categories": categories,
            "membership_changes_since_previous": _metric(
                value=changed_membership,
                formula=f"count(common program_id with changed explicit {dimension} taxonomy_id set)",
                unit="programs per capture interval",
                sample_size=len(common_ids),
                snapshot_id=snapshot_id,
                week_start=week_start,
                week_end=week_end,
                filter_description=filter_description,
                limitation="Only explicit frozen associations are compared; the schema does not record who assigned or reviewed a taxonomy link.",
                missing="No previous comparable snapshot; value is undefined, not zero."
                if previous_snapshot is None
                else "Unlabelled programs have an empty explicit-association set.",
                status="no_prior_snapshot" if previous_snapshot is None else "computed",
                **interval_arguments,
            ),
        }
    metrics["taxonomy"] = taxonomy_output

    changed_deadline_ids = {
        program_id for program_id in common_ids
        if current_programs[program_id].get("deadline_on")
        != previous_programs[program_id].get("deadline_on")
    } if previous_snapshot else set()
    changed_funding_ids = {
        program_id for program_id in common_ids
        if _funding_signature(current_programs[program_id])
        != _funding_signature(previous_programs[program_id])
    } if previous_snapshot else set()
    changed_taxonomy_ids = {
        program_id for program_id in common_ids
        if any(
            current_data["assignments"][program_id][dimension]
            != previous_data["assignments"][program_id][dimension]
            for dimension in ("theme", "geography")
        )
    } if previous_snapshot and previous_data is not None else set()
    updated_timestamp_ids = {
        program_id for program_id in common_ids
        if current_programs[program_id].get("updated_at")
        != previous_programs[program_id].get("updated_at")
    } if previous_snapshot else set()
    tracked_changed_ids = changed_deadline_ids | changed_funding_ids | changed_taxonomy_ids
    any_updated_ids = updated_timestamp_ids | tracked_changed_ids
    metrics["updates"] = {
        "updated_at_changed": _metric(
            value=len(updated_timestamp_ids) if previous_snapshot else None,
            formula="count(common program_id with changed Program.updated_at)",
            unit="programs per capture interval",
            sample_size=len(common_ids),
            snapshot_id=snapshot_id,
            week_start=week_start,
            week_end=week_end,
            filter_description=filter_description,
            limitation="Program.updated_at is the application row timestamp; it does not identify the upstream change time or changed field.",
            missing="No previous comparable snapshot; value is undefined, not zero."
            if previous_snapshot is None
            else "Only canonical fields frozen in both manifests are compared.",
            status="no_prior_snapshot" if previous_snapshot is None else "computed",
            **interval_arguments,
        ),
        "deadline_changed": deadlines["changed_values_since_previous"],
        "funding_changed": metrics["funding"]["changed_programs_since_previous"],
        "taxonomy_changed_programs": _metric(
            value=len(changed_taxonomy_ids) if previous_snapshot else None,
            formula="count(common program_id with any changed explicit theme or geography association set)",
            unit="programs per capture interval",
            sample_size=len(common_ids),
            snapshot_id=snapshot_id,
            week_start=week_start,
            week_end=week_end,
            filter_description=filter_description,
            limitation="Only explicit taxonomy links are frozen; missing provenance prevents attribution of who made a change.",
            missing="No previous comparable snapshot; value is undefined, not zero."
            if previous_snapshot is None
            else "Programs are counted once even if multiple taxonomy links changed.",
            status="no_prior_snapshot" if previous_snapshot is None else "computed",
            **interval_arguments,
        ),
        "any_tracked_update": _metric(
            value=len(any_updated_ids) if previous_snapshot else None,
            formula="count(unique common program_id with changed Program.updated_at or a frozen deadline/funding/taxonomy value)",
            unit="programs per capture interval",
            sample_size=len(common_ids),
            snapshot_id=snapshot_id,
            week_start=week_start,
            week_end=week_end,
            filter_description=filter_description,
            limitation="The manifest does not freeze title text, full URL, ProgramDetails, or ProgramTimelineEvent; this is a partial update measure.",
            missing="No previous comparable snapshot; value is undefined, not zero."
            if previous_snapshot is None
            else "Only shared Program IDs and explicitly frozen values can be compared.",
            status="no_prior_snapshot" if previous_snapshot is None else "computed",
            **interval_arguments,
        ),
    }

    network = calculate_network_metrics(snapshot)
    network_summary = {
        dimension: {
            "node_count": graph["metrics"]["node_count"],
            "edge_count": graph["metrics"]["edge_count"],
            "density": graph["metrics"]["density"],
            "connected_components": graph["metrics"]["connected_components"],
            "warning": graph["warnings"],
        }
        for dimension, graph in network["dimensions"].items()
    }
    return {
        "period": point_period,
        "status": "computed",
        "snapshot_id": snapshot_id,
        "as_of": as_of.isoformat(),
        "compared_snapshot_id": previous_id,
        "change_interval": (
            {
                "start": previous_as_of.isoformat(),
                "end": as_of.isoformat(),
                "days": (as_of - previous_as_of).total_seconds() / 86_400,
                "gap_weeks": gap_weeks,
                "warning": "snapshot_gap_no_interpolation" if gap_warning else None,
            }
            if previous_as_of is not None
            else None
        ),
        "unit_of_observation": "one unique eligible published Program in the frozen snapshot",
        "filter": filter_description,
        "metrics": metrics,
        "network_summary": network_summary,
        "warnings": ["snapshot_gap_no_interpolation"] if gap_warning else [],
        "limitations": [
            base_limitation,
            "Program changes are interval-censored between snapshots; short-lived changes between captures cannot be recovered.",
            "Published and archived status is application workflow state; disappearance does not establish source closure.",
        ],
    }


def _cohort_categories(snapshots: Sequence[object]) -> dict[str, dict[str, dict[str, str]]]:
    result: dict[str, dict[str, dict[str, str]]] = {"theme": {}, "geography": {}}
    for snapshot in snapshots:
        data = _snapshot_data(snapshot)
        for dimension, labels in data["labels"].items():
            for taxonomy_id, label in labels.items():
                result[dimension].setdefault(taxonomy_id, label)
    return result


def calculate_temporal_series(
    snapshots: Sequence[object],
    *,
    from_date: date,
    to_date: date,
    data_class: str = "real",
    frequency: str = SUPPORTED_FREQUENCY,
) -> dict[str, Any]:
    """Build UTC weekly catalog series from compatible immutable v3 snapshots."""

    if frequency != SUPPORTED_FREQUENCY:
        raise TemporalAnalyticsError("frequency must be 'weekly'")
    if from_date > to_date:
        raise TemporalAnalyticsError("from_date must not be after to_date")
    weeks = _week_range(from_date, to_date)
    excluded: Counter[str] = Counter()
    by_cohort: dict[tuple[str, str, int, str, str], list[object]] = defaultdict(list)
    for snapshot in snapshots:
        manifest = _attr(snapshot, "input_manifest")
        metrics = _attr(snapshot, "metrics")
        try:
            snapshot_id, as_of, cohort = _validate_supported_snapshot(snapshot)
        except (TemporalAnalyticsError, TypeError, ValueError):
            version = manifest.get("version") if isinstance(manifest, Mapping) else None
            excluded[str(version or "invalid_snapshot")] += 1
            continue
        if cohort[4] != data_class:
            excluded[f"other_data_class:{cohort[4]}"] += 1
            continue
        if as_of.date() > to_date:
            excluded["after_requested_window"] += 1
            continue
        by_cohort[cohort].append(snapshot)

    cohorts: list[dict[str, Any]] = []
    for cohort, cohort_snapshots in sorted(by_cohort.items(), key=lambda item: item[0][3]):
        ordered = sorted(
            cohort_snapshots,
            key=lambda item: (
                _timestamp(_attr(item, "as_of"), field="snapshot.as_of"),
                _snapshot_id(item),
            ),
        )
        latest_by_week: dict[date, object] = {}
        counts_by_week: Counter[date] = Counter()
        for snapshot in ordered:
            as_of = _timestamp(_attr(snapshot, "as_of"), field="snapshot.as_of")
            week = _week_start(as_of.date())
            latest_by_week[week] = snapshot
            counts_by_week[week] += 1
        in_requested_window = any(
            from_date <= _timestamp(_attr(snapshot, "as_of"), field="snapshot.as_of").date() <= to_date
            for snapshot in ordered
        )
        if not in_requested_window:
            excluded["no_snapshot_in_requested_window"] += len(ordered)
            continue
        categories = _cohort_categories(ordered)
        points: list[dict[str, Any]] = []
        for week in weeks:
            snapshot = latest_by_week.get(week)
            if snapshot is None:
                points.append(
                    {
                        "period": {
                            "kind": "utc_iso_week",
                            "start": week.isoformat(),
                            "end": (week + timedelta(days=6)).isoformat(),
                            "partial": week < from_date or week + timedelta(days=6) > to_date,
                        },
                        "status": "no_snapshot",
                        "snapshot_id": None,
                        "as_of": None,
                        "metrics": {},
                        "network_summary": {},
                        "warnings": ["no_snapshot_missing_not_zero"],
                    }
                )
                continue
            as_of = _timestamp(_attr(snapshot, "as_of"), field="snapshot.as_of")
            if not (from_date <= as_of.date() <= to_date):
                points.append(
                    {
                        "period": {
                            "kind": "utc_iso_week",
                            "start": week.isoformat(),
                            "end": (week + timedelta(days=6)).isoformat(),
                            "partial": week < from_date or week + timedelta(days=6) > to_date,
                        },
                        "status": "no_snapshot_in_requested_date_range",
                        "snapshot_id": None,
                        "as_of": None,
                        "metrics": {},
                        "network_summary": {},
                        "warnings": ["no_snapshot_missing_not_zero"],
                    }
                )
                continue
            prior_candidates = [
                candidate
                for prior_week, candidate in latest_by_week.items()
                if prior_week < week
            ]
            previous = prior_candidates[-1] if prior_candidates else None
            if prior_candidates:
                previous = max(
                    prior_candidates,
                    key=lambda item: _timestamp(_attr(item, "as_of"), field="snapshot.as_of"),
                )
            point = _series_point(
                snapshot=snapshot,
                previous_snapshot=previous,
                week_start=week,
                requested_from=from_date,
                requested_to=to_date,
                cohort_categories=categories,
            )
            if counts_by_week[week] > 1:
                point["warnings"].append("multiple_snapshots_week_latest_selected")
                point["omitted_snapshot_count_in_week"] = counts_by_week[week] - 1
            points.append(point)
        cohorts.append(
            {
                "scope": cohort[0],
                "calculation_version": cohort[1],
                "freshness_window_days": cohort[2],
                "registry_fingerprint": cohort[3],
                "data_class": cohort[4],
                "snapshot_ids": [
                    _snapshot_id(snapshot)
                    for snapshot in ordered
                    if from_date <= _timestamp(_attr(snapshot, "as_of"), field="snapshot.as_of").date() <= to_date
                ],
                "periods_without_snapshot_are_missing": True,
                "points": points,
                "limitations": [
                    "Only comparable snapshots in this cohort are combined; changes in source registry, method version, freshness window, or data class start another cohort.",
                    "Weekly states are point-in-time captures. Event changes are detected only between selected snapshots and are not prorated across missing weeks.",
                    "The series describes eligible connected catalog sources, not the complete opportunity ecosystem.",
                ],
            }
        )

    return {
        "version": TEMPORAL_ANALYTICS_VERSION,
        "frequency": frequency,
        "data_class": data_class,
        "window": {"from": from_date.isoformat(), "to": to_date.isoformat(), "timezone": "UTC"},
        "selection": "latest compatible snapshot by as_of in each UTC ISO week; no interpolation",
        "cohorts": cohorts,
        "excluded_snapshots": dict(sorted(excluded.items())),
        "status": "computed" if cohorts else "no_compatible_snapshots",
        "limitations": [
            "A first observed snapshot supplies a stock point; without a previous compatible snapshot, intake and change metrics are undefined rather than zero.",
            "Program.published_at is publication in Siderfold, not a source publication date. ProgramSource.observed_at is the last frozen source-observation timestamp and is not a first-seen event log.",
            "ProgramTimelineEvent, ProgramDetails, source-level publication history, and full field change history are not frozen in the current manifest.",
            "Snapshot differences cannot recover changes that appeared and disappeared between captures.",
            "This is descriptive measurement; changes do not imply causal effects or whole-market growth.",
        ],
    }

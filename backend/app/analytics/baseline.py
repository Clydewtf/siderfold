from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import random
from typing import Any


BASELINE_METRICS_VERSION = "catalog-baseline/v1"
BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_CONFIDENCE = 0.95
BOOTSTRAP_MIN_SAMPLE_SIZE = 10
QUANTILES = (("Q25", Decimal("0.25")), ("median", Decimal("0.5")), ("Q75", Decimal("0.75")))
NUMERIC_FUNDING_FIELDS = {
    "exact": ("funding_exact_amount",),
    "minimum": ("funding_min_amount",),
    "maximum": ("funding_max_amount",),
    "range": ("funding_min_amount", "funding_max_amount"),
}


class BaselineMetricsError(ValueError):
    """Raised when a frozen manifest cannot support a valid baseline calculation."""


def _as_objects(value: object, *, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise BaselineMetricsError(f"{field} must be an array of objects")
    return list(value)


def _as_decimal(value: object, *, field: str) -> Decimal:
    if not isinstance(value, str):
        raise BaselineMetricsError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise BaselineMetricsError(f"{field} must be a decimal string") from error
    if not result.is_finite() or result <= 0:
        raise BaselineMetricsError(f"{field} must be a positive finite amount")
    return result


def _date(value: object, *, field: str) -> date:
    if not isinstance(value, str):
        raise BaselineMetricsError(f"{field} must be an ISO date string")
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise BaselineMetricsError(f"{field} must be an ISO date string") from error
    if result.isoformat() != value:
        raise BaselineMetricsError(f"{field} must use canonical YYYY-MM-DD form")
    return result


def _quantile(values: Sequence[Decimal], probability: Decimal) -> Decimal:
    """Linear quantile using the R-7 definition."""

    if not values:
        raise BaselineMetricsError("quantiles require at least one value")
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * probability
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def _json_quantile(value: Decimal, *, amount: bool) -> str | float:
    if amount:
        return format(value.quantize(Decimal("0.01")), "f")
    return float(value)


def _bootstrap_interval(
    values: Sequence[Decimal],
    *,
    probability: Decimal,
    input_fingerprint: str,
    metric_key: str,
    amount: bool,
) -> dict[str, Any]:
    if len(values) < BOOTSTRAP_MIN_SAMPLE_SIZE:
        return {
            "status": "not_computed_small_sample",
            "reason": f"bootstrap requires n >= {BOOTSTRAP_MIN_SAMPLE_SIZE}",
            "confidence_level": BOOTSTRAP_CONFIDENCE,
            "resamples": BOOTSTRAP_RESAMPLES,
        }
    seed = sha256(
        f"{input_fingerprint}|{BASELINE_METRICS_VERSION}|{metric_key}".encode("utf-8")
    ).hexdigest()
    rng = random.Random(int(seed, 16))
    estimates: list[Decimal] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        estimates.append(_quantile(sample, probability))
    estimates.sort()
    low = _quantile(estimates, Decimal("0.025"))
    high = _quantile(estimates, Decimal("0.975"))
    return {
        "status": "computed",
        "method": "percentile bootstrap with replacement; R-7 quantile",
        "confidence_level": BOOTSTRAP_CONFIDENCE,
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": seed,
        "lower": _json_quantile(low, amount=amount),
        "upper": _json_quantile(high, amount=amount),
    }


def _metric(
    *,
    value: Any,
    formula: str,
    unit: str,
    period: Mapping[str, Any],
    filter_description: str,
    missing: str | Mapping[str, Any],
    sample_size: int,
    snapshot_id: str,
    limitation: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "value": value,
        "formula": formula,
        "unit": unit,
        "period": dict(period),
        "filter": filter_description,
        "missing": missing,
        "sample_size": sample_size,
        "snapshot_id": snapshot_id,
        "limitation": limitation,
        **extra,
    }


def _funding_state(program: Mapping[str, Any]) -> tuple[str, str | None, dict[str, Decimal]]:
    present_raw = program.get("funding_present")
    if not isinstance(present_raw, bool):
        raise BaselineMetricsError("funding_present must be boolean")
    present = present_raw
    kind = program.get("funding_value_kind")
    currency = program.get("funding_currency_code")
    amount_values = {
        "funding_exact_amount": program.get("funding_exact_amount"),
        "funding_min_amount": program.get("funding_min_amount"),
        "funding_max_amount": program.get("funding_max_amount"),
    }
    if not present:
        if kind is not None or currency is not None or any(v is not None for v in amount_values.values()):
            raise BaselineMetricsError("funding values exist without a funding row")
        return "missing_record", None, {}
    if kind not in {"exact", "minimum", "maximum", "range", "unknown", "not_stated"}:
        raise BaselineMetricsError("funding row has an unknown value_kind")
    if kind in {"unknown", "not_stated"}:
        if currency is not None or any(v is not None for v in amount_values.values()):
            raise BaselineMetricsError(f"{kind} funding must not contain currency or amounts")
        return str(kind), None, {}
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or currency.upper() != currency
    ):
        raise BaselineMetricsError("numeric funding must have a three-letter uppercase currency")
    expected = set(NUMERIC_FUNDING_FIELDS[str(kind)])
    numeric: dict[str, Decimal] = {}
    for field, value in amount_values.items():
        if field in expected:
            if value is None:
                raise BaselineMetricsError(f"{kind} funding is missing {field}")
            numeric[field] = _as_decimal(value, field=field)
        elif value is not None:
            raise BaselineMetricsError(f"{kind} funding must not contain {field}")
    if kind == "range" and numeric["funding_min_amount"] > numeric["funding_max_amount"]:
        raise BaselineMetricsError("range funding minimum exceeds maximum")
    return str(kind), currency, numeric


def calculate_baseline_metrics(
    *,
    source_scope: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    input_fingerprint: str,
    snapshot_id: str,
) -> dict[str, Any]:
    """Calculate descriptive metrics exclusively from the v2 frozen manifest."""

    if input_manifest.get("version") != "catalog-quality-input/v2":
        raise BaselineMetricsError("baseline metrics require catalog-quality-input/v2")
    raw_as_of = input_manifest.get("as_of")
    if not isinstance(raw_as_of, str):
        raise BaselineMetricsError("as_of must be an ISO timestamp")
    try:
        as_of = datetime.fromisoformat(raw_as_of)
    except ValueError as error:
        raise BaselineMetricsError("as_of must be an ISO timestamp") from error
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise BaselineMetricsError("as_of must include a timezone")
    as_of = as_of.astimezone(timezone.utc)
    programs = _as_objects(input_manifest.get("programs"), field="programs")
    if any(
        not isinstance(program.get("program_id"), str)
        or not isinstance(program.get("source_key"), str)
        for program in programs
    ):
        raise BaselineMetricsError("each program must have string program_id and source_key")
    program_ids = [str(program["program_id"]) for program in programs]
    if len(program_ids) != len(set(program_ids)):
        raise BaselineMetricsError("manifest contains duplicate program_id values")

    source_entries = _as_objects(
        source_scope.get("active_real_sources"),
        field="source_scope.active_real_sources",
    )
    program_source_entries = _as_objects(
        source_scope.get("program_sources", []),
        field="source_scope.program_sources",
    )
    allowed_program_source_keys = {
        str(entry["source_key"])
        for entry in program_source_entries
        if isinstance(entry.get("source_key"), str)
    }
    if any(str(program["source_key"]) not in allowed_program_source_keys for program in programs):
        raise BaselineMetricsError("program manifest contains a source outside program_sources")
    all_program_count = len(programs)
    point_period = {"kind": "point_in_time", "as_of": as_of.isoformat()}
    rolling_days = int(input_manifest["freshness_window_days"])
    rolling_period = {
        "kind": "rolling_window",
        "days": rolling_days,
        "started_at": (as_of - timedelta(days=rolling_days)).isoformat(),
        "ended_at": as_of.isoformat(),
    }
    # Source coverage uses the same inclusive rolling period as freshness.
    snapshot = snapshot_id
    data_class = input_manifest.get("data_class", "unknown")
    if not isinstance(data_class, str) or data_class not in {
        "real",
        "test",
        "synthetic",
        "unknown",
    }:
        data_class = "unknown"
    metrics: dict[str, dict[str, Any]] = {}
    common_limit = "Описывает только фактически включённые записи подключённых источников; не является оценкой всей экосистемы."
    included_filter = (
        "unique Program rows in manifest v2; published by as_of; primary_source in eligible non-Telegram active sources; "
        "FASIE excluded by research protocol"
    )

    metrics["opportunities.count"] = _metric(
        value=all_program_count,
        formula="count(distinct program_id)",
        unit="program",
        period=point_period,
        filter_description=included_filter,
        missing="programs without required source fields are excluded upstream and listed in manifest exclusions",
        sample_size=all_program_count,
        snapshot_id=snapshot,
        limitation=common_limit,
    )

    counts_by_source = Counter(str(program["source_key"]) for program in programs)
    source_program_keys = sorted(
        str(entry["source_key"])
        for entry in program_source_entries
        if isinstance(entry.get("source_key"), str)
    )
    for source_key in source_program_keys:
        count = counts_by_source[source_key]
        source_filter = f"{included_filter}; source_key = {source_key}"
        metrics[f"opportunities.source.{source_key}.count"] = _metric(
            value=count,
            formula=f"count(distinct program_id where source_key = '{source_key}')",
            unit="program",
            period=point_period,
            filter_description=source_filter,
            missing="zero when the included source has no program row in this snapshot",
            sample_size=count,
            snapshot_id=snapshot,
            limitation=common_limit,
        )
        metrics[f"opportunities.source.{source_key}.share"] = _metric(
            value=(count / all_program_count if all_program_count else None),
            formula="source distinct program count / all included distinct programs",
            unit="share of included programs",
            period=point_period,
            filter_description=source_filter,
            missing="null when there are no included programs",
            sample_size=all_program_count,
            snapshot_id=snapshot,
            limitation=common_limit,
            numerator=count,
            denominator=all_program_count,
        )

    funding_states: Counter[str] = Counter()
    numeric_by_group: dict[tuple[str, str, str], list[Decimal]] = defaultdict(list)
    for program in programs:
        kind, currency, amounts = _funding_state(program)
        funding_states[kind] += 1
        if kind == "exact":
            numeric_by_group[(str(currency), "exact", "exact_amount")].append(amounts["funding_exact_amount"])
        elif kind == "minimum":
            numeric_by_group[(str(currency), "minimum", "min_amount")].append(amounts["funding_min_amount"])
        elif kind == "maximum":
            numeric_by_group[(str(currency), "maximum", "max_amount")].append(amounts["funding_max_amount"])
        elif kind == "range":
            numeric_by_group[(str(currency), "range", "min_amount")].append(amounts["funding_min_amount"])
            numeric_by_group[(str(currency), "range", "max_amount")].append(amounts["funding_max_amount"])

    funding_rows = sum(funding_states.values()) - funding_states["missing_record"]
    numeric_programs = sum(
        funding_states[kind] for kind in NUMERIC_FUNDING_FIELDS
    )
    funding_missing = {
        "missing_record": funding_states["missing_record"],
        "unknown": funding_states["unknown"],
        "not_stated": funding_states["not_stated"],
        "numeric_kinds": {
            kind: funding_states[kind] for kind in sorted(NUMERIC_FUNDING_FIELDS)
        },
    }
    metrics["funding.record_share"] = _metric(
        value=(funding_rows / all_program_count if all_program_count else None),
        formula="programs with ProgramFunding row / all included programs",
        unit="share of included programs",
        period=point_period,
        filter_description=included_filter,
        missing=funding_missing,
        sample_size=all_program_count,
        snapshot_id=snapshot,
        limitation="Наличие строки не означает, что в источнике объявлена сумма.",
        numerator=funding_rows,
        denominator=all_program_count,
    )
    metrics["funding.numeric_share"] = _metric(
        value=(numeric_programs / all_program_count if all_program_count else None),
        formula="programs with exact/minimum/maximum/range numeric amount / all included programs",
        unit="share of included programs",
        period=point_period,
        filter_description=included_filter,
        missing=funding_missing,
        sample_size=all_program_count,
        snapshot_id=snapshot,
        limitation="Unknown/not_stated and missing amounts are excluded; currencies are not converted.",
        numerator=numeric_programs,
        denominator=all_program_count,
    )

    funding_groups: dict[str, dict[str, Any]] = {}
    for currency, value_kind, measure in sorted(numeric_by_group):
        values = numeric_by_group[(currency, value_kind, measure)]
        group_key = f"{currency}.{value_kind}.{measure}"
        q_keys: dict[str, str] = {}
        for quantile_name, probability in QUANTILES:
            metric_key = f"funding.quantile.{group_key}.{quantile_name}"
            estimate = _quantile(values, probability)
            metrics[metric_key] = _metric(
                value=_json_quantile(estimate, amount=True),
                formula=f"R-7 {quantile_name} of {measure} for {currency}/{value_kind}",
                unit=f"{currency} per program as represented by source",
                period=point_period,
                filter_description=f"{included_filter}; currency_code = {currency}; value_kind = {value_kind}",
                missing="unknown, not_stated, no funding row, and different currencies/kinds excluded; range bounds remain separate",
                sample_size=len(values),
                snapshot_id=snapshot,
                limitation="Source values are not normalized for recipient scope, inflation, purchasing power, or currency; range bounds are not a single award value.",
                uncertainty=_bootstrap_interval(
                    values,
                    probability=probability,
                    input_fingerprint=input_fingerprint,
                    metric_key=metric_key,
                    amount=True,
                ),
            )
            q_keys[quantile_name] = metric_key
        funding_groups[group_key] = {
            "currency_code": currency,
            "value_kind": value_kind,
            "measure": measure,
            "sample_size": len(values),
            "quantile_metrics": q_keys,
        }
    metrics["funding.quantiles_status"] = _metric(
        value=("ready" if numeric_by_group else "not_computed_empty_sample"),
        formula="calculate R-7 quartiles for each observed currency/value_kind/measure group",
        unit="calculation status",
        period=point_period,
        filter_description=f"{included_filter}; valid numeric ProgramFunding rows only",
        missing=funding_missing,
        sample_size=numeric_programs,
        snapshot_id=snapshot,
        limitation="Если нет numeric funding, числовые квантили не определены и не создаются.",
        group_count=len(numeric_by_group),
    )

    deadline_values: list[Decimal] = []
    deadline_programs = 0
    upcoming_programs = 0
    overdue_programs = 0
    for program in programs:
        raw_deadline = program.get("deadline_on")
        deadline_present = program.get("deadline_present")
        if not isinstance(deadline_present, bool):
            raise BaselineMetricsError("deadline_present must be boolean")
        if raw_deadline is None:
            if deadline_present:
                raise BaselineMetricsError("deadline_present conflicts with missing deadline_on")
            continue
        deadline = _date(raw_deadline, field="deadline_on")
        if not deadline_present:
            raise BaselineMetricsError("deadline_on conflicts with deadline_present")
        days = (deadline - as_of.date()).days
        deadline_programs += 1
        if days >= 0:
            upcoming_programs += 1
            deadline_values.append(Decimal(days))
        else:
            overdue_programs += 1
    deadline_missing = {"no_deadline_on": all_program_count - deadline_programs}
    metrics["deadlines.presence_share"] = _metric(
        value=(deadline_programs / all_program_count if all_program_count else None),
        formula="programs with deadline_on / all included programs",
        unit="share of included programs",
        period=point_period,
        filter_description=included_filter,
        missing=deadline_missing,
        sample_size=all_program_count,
        snapshot_id=snapshot,
        limitation="Измеряется наличие одного канонического дедлайна; другие даты подачи/этапов не входят.",
        numerator=deadline_programs,
        denominator=all_program_count,
    )
    metrics["deadlines.upcoming_share"] = _metric(
        value=(upcoming_programs / all_program_count if all_program_count else None),
        formula="programs with deadline_on >= as_of.date / all included programs",
        unit="share of included programs",
        period=point_period,
        filter_description=included_filter,
        missing=deadline_missing,
        sample_size=all_program_count,
        snapshot_id=snapshot,
        limitation="Дедлайн сегодня считается предстоящим; неизвестные даты не считаются нулём и остаются в знаменателе.",
        numerator=upcoming_programs,
        denominator=all_program_count,
    )
    metrics["deadlines.overdue_count"] = _metric(
        value=overdue_programs,
        formula="count(programs with deadline_on < as_of.date)",
        unit="program",
        period=point_period,
        filter_description=included_filter,
        missing=deadline_missing,
        sample_size=deadline_programs,
        snapshot_id=snapshot,
        limitation="Отражает только зафиксированный канонический deadline_on.",
    )
    for quantile_name, probability in QUANTILES:
        metric_key = f"deadlines.days.{quantile_name}"
        if deadline_values:
            estimate = _quantile(deadline_values, probability)
            value: int | float | None = int(estimate) if estimate == estimate.to_integral_value() else float(estimate)
        else:
            value = None
        uncertainty = (
            _bootstrap_interval(
                deadline_values,
                probability=probability,
                input_fingerprint=input_fingerprint,
                metric_key=metric_key,
                amount=False,
            )
            if deadline_values
            else {
                "status": "not_computed_empty_sample",
                "reason": "no included program has deadline_on",
                "confidence_level": BOOTSTRAP_CONFIDENCE,
                "resamples": BOOTSTRAP_RESAMPLES,
            }
        )
        metrics[metric_key] = _metric(
            value=value,
            formula=f"R-7 {quantile_name} of (deadline_on - as_of.date) for non-overdue deadlines in calendar days",
            unit="calendar day",
            period=point_period,
            filter_description=f"{included_filter}; deadline_on >= as_of.date",
            missing={
                **deadline_missing,
                "overdue_excluded_from_days_distribution": overdue_programs,
            },
            sample_size=len(deadline_values),
            snapshot_id=snapshot,
            limitation="Распределение включает только дедлайны сегодня или позднее; просроченные отдельно считаются, а малая/селективная подвыборка не экстраполируется.",
            uncertainty=uncertainty,
        )

    executions = _as_objects(input_manifest.get("source_executions"), field="source_executions")
    success_keys = {
        str(execution["source_key"])
        for execution in executions
        if execution.get("status") == "succeeded" and execution.get("dry_run") is False
    }
    execution_counts = Counter(str(execution["source_key"]) for execution in executions)
    for entry in sorted(source_entries, key=lambda item: str(item.get("source_key", ""))):
        source_key = str(entry.get("source_key"))
        succeeded = source_key in success_keys
        metrics[f"source.execution_coverage.{source_key}"] = _metric(
            value=1 if succeeded else 0,
            formula="1 if source has >=1 succeeded non-dry-run execution, else 0",
            unit="source coverage indicator",
            period=rolling_period,
            filter_description=f"active real registry source {source_key}; finished_at in rolling freshness window; dry_run excluded",
            missing="no eligible execution means uncovered (0); not interpreted as evidence that a source has no programs",
            sample_size=1,
            snapshot_id=snapshot,
            limitation="Покрывает только запуски реестра в выбранном окне, не полноту содержимого источника.",
            successful=source_key in success_keys,
            execution_count=execution_counts[source_key],
        )

    for metric in metrics.values():
        metric["data_class"] = data_class

    return {
        "version": BASELINE_METRICS_VERSION,
        "snapshot_id": snapshot,
        "data_class": data_class,
        "period": point_period,
        "metrics": metrics,
        "groups": {"funding_quantiles": funding_groups},
        "method": {
            "quantile_definition": "R-7 linear interpolation",
            "confidence_intervals": "95% percentile bootstrap with replacement for numeric funding and known deadline days when n >= 10; 2,000 resamples; seed = SHA-256(input_fingerprint | version | metric_key)",
            "finite_frame_proportions": "No confidence interval: these are exact descriptive fractions of the frozen observed frame, not probability-sample estimates.",
        },
    }


def compare_snapshot_counts(current: Any, previous: Any) -> dict[str, Any]:
    """Compare only two snapshots with identical calculation scope and registry."""

    current_id = str(current.id)
    previous_id = str(previous.id)
    reasons: list[str] = []
    if current.scope != previous.scope:
        reasons.append("different_scope")
    if current.calculation_version != previous.calculation_version:
        reasons.append("different_calculation_version")
    if current.registry_fingerprint != previous.registry_fingerprint:
        reasons.append("different_registry_fingerprint")
    if current.freshness_window_days != previous.freshness_window_days:
        reasons.append("different_freshness_window")
    if current.input_manifest.get("data_class") != previous.input_manifest.get("data_class"):
        reasons.append("different_data_class")
    if current.as_of <= previous.as_of:
        reasons.append("current_as_of_must_be_later")
    current_baseline = current.metrics.get("baseline")
    previous_baseline = previous.metrics.get("baseline")
    if not isinstance(current_baseline, Mapping) or not isinstance(previous_baseline, Mapping):
        reasons.append("baseline_metrics_unavailable")
    comparable = not reasons
    metric: dict[str, Any] | None = None
    if comparable:
        current_count = current_baseline["metrics"]["opportunities.count"]["value"]
        previous_count = previous_baseline["metrics"]["opportunities.count"]["value"]
        delta = current_count - previous_count
        metric = {
            "value": delta,
            "percent_change": (delta / previous_count if previous_count else None),
            "formula": "current count - previous count; percent_change = delta / previous count",
            "unit": "program; percent_change is a ratio",
            "period": {
                "kind": "snapshot_comparison",
                "previous_as_of": previous.as_of.astimezone(timezone.utc).isoformat(),
                "current_as_of": current.as_of.astimezone(timezone.utc).isoformat(),
            },
            "filter": "comparable v2 snapshots with same registry fingerprint and data class",
            "missing": "percent_change is null when previous count is zero",
            "sample_size": 2,
            "snapshot_id": current_id,
            "compared_snapshot_id": previous_id,
            "limitation": "Change in observed catalogue count is not market growth; new records, removals, and source coverage can change it.",
        }
    return {
        "comparable": comparable,
        "reasons": reasons,
        "current_snapshot_id": current_id,
        "previous_snapshot_id": previous_id,
        "opportunities_count_change": metric,
    }

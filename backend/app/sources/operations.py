"""Controlled local execution for allowlisted source adapters.

The module intentionally exposes one-shot operations only. A host scheduler may
invoke ``run_due_sources`` periodically, but this package never starts a daemon.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import re
from time import monotonic, sleep
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError, SQLAlchemyError

from app.core.config import Settings
from app.domain.models import (
    DiscoveryReviewCase,
    IngestionRun,
    IngestionRunStatus,
    ReviewCase,
    ReviewCaseStatus,
    Source,
    SourceExecutionAttempt,
    SourceExecutionAttemptStatus,
    SourceExecutionRun,
    SourceExecutionStatus,
    SourceExecutionTrigger,
)
from app.sources.contract import AdapterIssue, AdapterReport, AdapterStage, RunStatistics
from app.sources.registry import (
    SourceDefinition,
    SourceRegistry,
    SourceRegistryStatus,
    load_registry,
)
from app.sources.runner import run_registered_source
from app.sources.schedule import is_schedule_due


_TRANSIENT_MESSAGE_MARKERS = (
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "connection aborted",
    "temporary failure",
    "name or service not known",
    "network is unreachable",
    "transport error",
    "database unavailable",
)
_HTTP_STATUS_PATTERN = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)
_RETRY_AFTER_PATTERN = re.compile(r"\bretry[- ]after\s*[:=]\s*(\d+)\b", re.IGNORECASE)


class SourceExecutionResult(BaseModel):
    """Safe operational summary with no raw response or exception text."""

    model_config = ConfigDict(extra="forbid")

    source_key: str
    execution_id: UUID
    status: SourceExecutionStatus
    trigger: SourceExecutionTrigger
    started_at: datetime
    finished_at: datetime
    ingestion_run_id: UUID | None = None
    attempt_count: int = Field(ge=0)
    result_kind: str | None = None
    error_codes: tuple[str, ...] = ()
    metrics: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_failure(self) -> bool:
        return self.status in {
            SourceExecutionStatus.FAILED,
            SourceExecutionStatus.INTERRUPTED,
        }


class SchedulerTickResult(BaseModel):
    """Result of one explicit scheduler tick, not a persistent process."""

    model_config = ConfigDict(extra="forbid")

    evaluated_at: datetime
    due_source_keys: tuple[str, ...] = ()
    results: tuple[SourceExecutionResult, ...] = ()

    @property
    def has_failures(self) -> bool:
        return any(result.is_failure for result in self.results)


def _utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        raise ValueError("source operations require a timezone-aware datetime")
    return resolved.astimezone(timezone.utc)


def _lock_key(source_key: str) -> int:
    """Derive a stable signed PostgreSQL advisory-lock key from a registry key."""

    digest = sha256(f"siderfold:source:{source_key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _try_lock(connection: Connection, source_key: str) -> bool:
    return bool(
        connection.scalar(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": _lock_key(source_key)},
        )
    )


def _unlock(connection: Connection, source_key: str) -> None:
    connection.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": _lock_key(source_key)},
    )


def _upsert_source(connection: Connection, definition: SourceDefinition) -> UUID:
    source_id = uuid4()
    created_id = connection.scalar(
        postgresql_insert(Source)
        .values(
            id=source_id,
            name=definition.name,
            canonical_url=definition.canonical_url,
        )
        .on_conflict_do_nothing(index_elements=("canonical_url",))
        .returning(Source.id)
    )
    if created_id is not None:
        return created_id
    existing_id = connection.scalar(
        select(Source.id).where(Source.canonical_url == definition.canonical_url)
    )
    if existing_id is None:
        raise RuntimeError("source was not persisted after a canonical URL conflict")
    return existing_id


def _ensure_source(engine: Engine, definition: SourceDefinition) -> UUID:
    with engine.begin() as connection:
        return _upsert_source(connection, definition)


def _safe_error_codes(report: AdapterReport) -> tuple[str, ...]:
    return tuple(
        sorted({issue.code for issue in report.issues if issue.severity == "error"})
    )


def _is_success(report: AdapterReport) -> bool:
    return report.status == "completed" and report.statistics.errors == 0


def _result_kind(report: AdapterReport) -> str:
    if _is_success(report) and report.statistics.extracted == 0:
        return "empty_success"
    return "completed" if _is_success(report) else "failed"


def _http_status(issue: AdapterIssue) -> int | None:
    match = _HTTP_STATUS_PATTERN.search(issue.message)
    return int(match.group(1)) if match is not None else None


def _is_transient_issue(issue: AdapterIssue) -> bool:
    if issue.code == "database_unavailable":
        return True
    if issue.code not in {"fetch_error", "discover_error", "persist_error"}:
        return False
    status_code = _http_status(issue)
    if status_code is not None:
        return status_code in {408, 429} or status_code >= 500
    message = issue.message.casefold()
    return any(marker in message for marker in _TRANSIENT_MESSAGE_MARKERS)


def _retry_class(report: AdapterReport) -> str:
    if _is_success(report):
        return "success"
    errors = tuple(issue for issue in report.issues if issue.severity == "error")
    if errors and all(_is_transient_issue(issue) for issue in errors):
        return "transient"
    return "permanent"


def _retry_after_seconds(report: AdapterReport, maximum: int) -> int | None:
    candidates: list[int] = []
    for issue in report.issues:
        match = _RETRY_AFTER_PATTERN.search(issue.message)
        if match is not None:
            candidates.append(int(match.group(1)))
    if not candidates:
        return None
    return min(max(candidates), maximum)


def _backoff_seconds(
    *,
    completed_attempts: int,
    settings: Settings,
    report: AdapterReport,
) -> int:
    exponential = min(
        settings.scheduler_initial_backoff_seconds * (5 ** (completed_attempts - 1)),
        settings.scheduler_max_backoff_seconds,
    )
    retry_after = _retry_after_seconds(report, settings.scheduler_retry_after_max_seconds)
    return max(exponential, retry_after or 0)


def _field_error_counts(report: AdapterReport) -> dict[str, int]:
    counts = Counter(
        issue.field
        for issue in report.issues
        if issue.severity == "error" and issue.field is not None
    )
    return dict(sorted(counts.items()))


def _review_queue_sizes(connection: Connection) -> dict[str, int]:
    open_statuses = (ReviewCaseStatus.OPEN, ReviewCaseStatus.NEEDS_CLARIFICATION)
    canonical = int(
        connection.scalar(
            select(func.count())
            .select_from(ReviewCase)
            .where(ReviewCase.status.in_(open_statuses))
        )
        or 0
    )
    discovery = int(
        connection.scalar(
            select(func.count())
            .select_from(DiscoveryReviewCase)
            .where(DiscoveryReviewCase.status.in_(open_statuses))
        )
        or 0
    )
    return {
        "canonical": canonical,
        "discovery": discovery,
        "total": canonical + discovery,
    }


def _metrics(
    engine: Engine,
    report: AdapterReport,
    *,
    duration_seconds: float,
) -> dict[str, Any]:
    import_counts = report.import_counts or {}
    freshness = (
        report.quality.freshness.model_dump(mode="json")
        if report.quality is not None
        else None
    )
    with engine.connect() as connection:
        queue_sizes = _review_queue_sizes(connection)
    return {
        "duration_seconds": round(max(duration_seconds, 0.0), 6),
        "status": report.status,
        "result_kind": _result_kind(report),
        "statistics": report.statistics.model_dump(mode="json"),
        "records": {
            "new": int(import_counts.get("new", 0)),
            "updated": int(import_counts.get("updated", 0)),
            "skipped": int(import_counts.get("skipped", 0)),
            "errors": int(import_counts.get("errors", report.statistics.errors)),
        },
        "field_error_counts": _field_error_counts(report),
        "non_field_error_count": sum(
            issue.severity == "error" and issue.field is None
            for issue in report.issues
        ),
        "freshness": freshness,
        "review_queue": queue_sizes,
    }


def _insert_execution(
    engine: Engine,
    *,
    source_id: UUID,
    definition: SourceDefinition,
    trigger: SourceExecutionTrigger,
    status: SourceExecutionStatus,
    started_at: datetime,
    finished_at: datetime | None,
    owner_token: UUID | None = None,
    scheduled_for: datetime | None = None,
    lease_expires_at: datetime | None = None,
    attempt_count: int = 0,
    ingestion_run_id: UUID | None = None,
    result_kind: str | None = None,
    metrics: Mapping[str, Any] | None = None,
    error_codes: Sequence[str] = (),
) -> UUID:
    execution_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            postgresql_insert(SourceExecutionRun).values(
                id=execution_id,
                source_id=source_id,
                source_key=definition.source_key,
                trigger=trigger,
                status=status,
                owner_token=owner_token,
                scheduled_for=scheduled_for,
                started_at=started_at,
                lease_expires_at=lease_expires_at,
                finished_at=finished_at,
                ingestion_run_id=ingestion_run_id,
                attempt_count=attempt_count,
                result_kind=result_kind,
                metrics=dict(metrics or {}),
                error_codes=list(error_codes),
            )
        )
    return execution_id


def _insert_attempt(
    engine: Engine,
    *,
    execution_id: UUID,
    attempt_number: int,
    success: bool,
    started_at: datetime,
    finished_at: datetime,
    ingestion_run_id: UUID | None,
    retry_class: str | None,
    backoff_seconds: int,
    metrics: Mapping[str, Any],
    error_codes: Sequence[str],
) -> None:
    with engine.begin() as connection:
        connection.execute(
            postgresql_insert(SourceExecutionAttempt).values(
                id=uuid4(),
                source_execution_run_id=execution_id,
                attempt_number=attempt_number,
                status=(
                    SourceExecutionAttemptStatus.SUCCEEDED
                    if success
                    else SourceExecutionAttemptStatus.FAILED
                ),
                started_at=started_at,
                finished_at=finished_at,
                ingestion_run_id=ingestion_run_id,
                retry_class=retry_class,
                backoff_seconds=backoff_seconds,
                metrics=dict(metrics),
                error_codes=list(error_codes),
            )
        )


def _finalize_execution(
    engine: Engine,
    *,
    execution_id: UUID,
    status: SourceExecutionStatus,
    finished_at: datetime,
    attempt_count: int,
    ingestion_run_id: UUID | None,
    result_kind: str,
    metrics: Mapping[str, Any],
    error_codes: Sequence[str],
) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(SourceExecutionRun)
            .where(SourceExecutionRun.id == execution_id)
            .values(
                status=status,
                finished_at=finished_at,
                attempt_count=attempt_count,
                ingestion_run_id=ingestion_run_id,
                result_kind=result_kind,
                metrics=dict(metrics),
                error_codes=list(error_codes),
            )
        )


def _recover_interrupted_executions(
    engine: Engine,
    *,
    source_id: UUID,
    recovered_at: datetime,
) -> None:
    """Close abandoned journals only after acquiring the source advisory lock."""

    with engine.begin() as connection:
        unfinished = connection.execute(
            select(
                SourceExecutionRun.id,
                SourceExecutionRun.metrics,
                SourceExecutionRun.error_codes,
            ).where(
                SourceExecutionRun.source_id == source_id,
                SourceExecutionRun.status == SourceExecutionStatus.RUNNING,
            )
        ).mappings()
        for row in unfinished:
            metrics = dict(row["metrics"]) if isinstance(row["metrics"], Mapping) else {}
            metrics["recovery"] = {
                "at": recovered_at.isoformat(),
                "reason": "advisory_lock_reacquired_after_unfinished_execution",
            }
            error_codes = list(row["error_codes"]) if isinstance(row["error_codes"], list) else []
            connection.execute(
                update(SourceExecutionRun)
                .where(SourceExecutionRun.id == row["id"])
                .values(
                    status=SourceExecutionStatus.INTERRUPTED,
                    finished_at=recovered_at,
                    result_kind="interrupted",
                    metrics=metrics,
                    error_codes=sorted(set([*error_codes, "execution_interrupted"])),
                )
            )

        processing_runs = connection.execute(
            select(IngestionRun.id, IngestionRun.run_statistics).where(
                IngestionRun.source_id == source_id,
                IngestionRun.status == IngestionRunStatus.PROCESSING,
            )
        ).mappings()
        for row in processing_runs:
            statistics = (
                dict(row["run_statistics"])
                if isinstance(row["run_statistics"], Mapping)
                else {}
            )
            statistics["operational_recovery"] = {
                "at": recovered_at.isoformat(),
                "reason": "execution_interrupted_before_terminal_status",
            }
            connection.execute(
                update(IngestionRun)
                .where(IngestionRun.id == row["id"])
                .values(
                    status=IngestionRunStatus.FAILED,
                    finished_at=recovered_at,
                    run_statistics=statistics,
                )
            )


def _next_allowed_at(
    engine: Engine,
    *,
    source_id: UUID,
    min_run_interval_seconds: int,
) -> datetime | None:
    if min_run_interval_seconds == 0:
        return None
    with engine.connect() as connection:
        last_started = connection.scalar(
            select(SourceExecutionRun.started_at)
            .where(
                SourceExecutionRun.source_id == source_id,
                SourceExecutionRun.status.in_(
                    (
                        SourceExecutionStatus.SUCCEEDED,
                        SourceExecutionStatus.FAILED,
                        SourceExecutionStatus.INTERRUPTED,
                    )
                ),
            )
            .order_by(SourceExecutionRun.started_at.desc())
            .limit(1)
        )
    if last_started is None:
        return None
    return last_started + timedelta(seconds=min_run_interval_seconds)


def _failure_report(definition: SourceDefinition, error: Exception) -> AdapterReport:
    code = (
        "database_unavailable"
        if isinstance(error, (DisconnectionError, InterfaceError, OperationalError))
        else "scheduler_execution_error"
    )
    return AdapterReport(
        source_key=definition.source_key,
        adapter_name=definition.adapter_name,
        adapter_version=definition.adapter_version,
        status="failed",
        dry_run=False,
        statistics=RunStatistics(errors=1),
        issues=(
            AdapterIssue(
                stage=AdapterStage.RUN,
                severity="error",
                code=code,
                message=str(error),
            ),
        ),
    )


def _result(
    *,
    definition: SourceDefinition,
    execution_id: UUID,
    status: SourceExecutionStatus,
    trigger: SourceExecutionTrigger,
    started_at: datetime,
    finished_at: datetime,
    ingestion_run_id: UUID | None,
    attempt_count: int,
    result_kind: str | None,
    error_codes: Sequence[str],
    metrics: Mapping[str, Any],
) -> SourceExecutionResult:
    return SourceExecutionResult(
        source_key=definition.source_key,
        execution_id=execution_id,
        status=status,
        trigger=trigger,
        started_at=started_at,
        finished_at=finished_at,
        ingestion_run_id=ingestion_run_id,
        attempt_count=attempt_count,
        result_kind=result_kind,
        error_codes=tuple(error_codes),
        metrics=dict(metrics),
    )


def _skipped_execution(
    engine: Engine,
    *,
    source_id: UUID,
    definition: SourceDefinition,
    trigger: SourceExecutionTrigger,
    now: datetime,
    status: SourceExecutionStatus,
    code: str,
    scheduled_for: datetime | None,
    metrics: Mapping[str, Any] | None = None,
) -> SourceExecutionResult:
    result_metrics = dict(metrics or {})
    result_metrics["skip_reason"] = code
    execution_id = _insert_execution(
        engine,
        source_id=source_id,
        definition=definition,
        trigger=trigger,
        status=status,
        started_at=now,
        finished_at=now,
        scheduled_for=scheduled_for,
        result_kind="skipped",
        metrics=result_metrics,
        error_codes=(code,),
    )
    return _result(
        definition=definition,
        execution_id=execution_id,
        status=status,
        trigger=trigger,
        started_at=now,
        finished_at=now,
        ingestion_run_id=None,
        attempt_count=0,
        result_kind="skipped",
        error_codes=(code,),
        metrics=result_metrics,
    )


def run_managed_source(
    source_key: str,
    *,
    engine: Engine,
    settings: Settings,
    registry_path: Path | None = None,
    registry: SourceRegistry | None = None,
    trigger: SourceExecutionTrigger = SourceExecutionTrigger.MANUAL,
    scheduled_for: datetime | None = None,
    now: datetime | None = None,
    sleeper: Callable[[float], None] = sleep,
    progress_reporter: Callable[[str], None] | None = None,
) -> SourceExecutionResult:
    """Run one source under an advisory lock and append its operation journal."""

    resolved_now = _utc(now)
    execution_clock_started_at = monotonic()
    resolved_registry_path = (
        settings.source_registry_path if registry_path is None else registry_path
    )
    loaded_registry = registry or load_registry(resolved_registry_path)
    definition = loaded_registry.get(source_key)
    source_id = _ensure_source(engine, definition)

    with engine.connect() as lock_connection:
        lock_acquired = False
        try:
            lock_acquired = _try_lock(lock_connection, source_key)
            if not lock_acquired:
                return _skipped_execution(
                    engine,
                    source_id=source_id,
                    definition=definition,
                    trigger=trigger,
                    now=resolved_now,
                    status=SourceExecutionStatus.SKIPPED_LOCKED,
                    code="concurrent_execution",
                    scheduled_for=scheduled_for,
                )

            _recover_interrupted_executions(
                engine,
                source_id=source_id,
                recovered_at=resolved_now,
            )
            if definition.status is not SourceRegistryStatus.ACTIVE:
                execution_id = _insert_execution(
                    engine,
                    source_id=source_id,
                    definition=definition,
                    trigger=trigger,
                    status=SourceExecutionStatus.RUNNING,
                    owner_token=uuid4(),
                    started_at=resolved_now,
                    finished_at=None,
                    scheduled_for=scheduled_for,
                    lease_expires_at=resolved_now
                    + timedelta(seconds=settings.scheduler_run_lease_seconds),
                )
                metrics = {
                    "status": "failed",
                    "result_kind": "failed",
                    "reason": "source_not_active",
                }
                _finalize_execution(
                    engine,
                    execution_id=execution_id,
                    status=SourceExecutionStatus.FAILED,
                    finished_at=resolved_now,
                    attempt_count=0,
                    ingestion_run_id=None,
                    result_kind="failed",
                    metrics=metrics,
                    error_codes=("source_not_active",),
                )
                return _result(
                    definition=definition,
                    execution_id=execution_id,
                    status=SourceExecutionStatus.FAILED,
                    trigger=trigger,
                    started_at=resolved_now,
                    finished_at=resolved_now,
                    ingestion_run_id=None,
                    attempt_count=0,
                    result_kind="failed",
                    error_codes=("source_not_active",),
                    metrics=metrics,
                )

            next_allowed_at = _next_allowed_at(
                engine,
                source_id=source_id,
                min_run_interval_seconds=definition.limits.min_run_interval_seconds,
            )
            if next_allowed_at is not None and resolved_now < next_allowed_at:
                return _skipped_execution(
                    engine,
                    source_id=source_id,
                    definition=definition,
                    trigger=trigger,
                    now=resolved_now,
                    status=SourceExecutionStatus.SKIPPED_RATE_LIMITED,
                    code="min_run_interval_not_elapsed",
                    scheduled_for=scheduled_for,
                    metrics={"next_allowed_at": next_allowed_at.isoformat()},
                )

            owner_token = uuid4()
            lease_expires_at = resolved_now + timedelta(
                seconds=settings.scheduler_run_lease_seconds
            )
            execution_id = _insert_execution(
                engine,
                source_id=source_id,
                definition=definition,
                trigger=trigger,
                status=SourceExecutionStatus.RUNNING,
                owner_token=owner_token,
                started_at=resolved_now,
                finished_at=None,
                scheduled_for=scheduled_for,
                lease_expires_at=lease_expires_at,
            )

            last_report: AdapterReport | None = None
            last_metrics: dict[str, Any] = {}
            last_error_codes: tuple[str, ...] = ()
            last_finished_at = resolved_now
            attempts_completed = 0
            for attempt_number in range(1, settings.scheduler_max_attempts + 1):
                attempt_started_at = resolved_now + timedelta(
                    seconds=monotonic() - execution_clock_started_at
                )
                try:
                    report = run_registered_source(
                        source_key,
                        registry_path=resolved_registry_path,
                        engine=engine,
                        raw_capture_dir=settings.raw_capture_dir,
                        progress_reporter=progress_reporter,
                    )
                except Exception as error:
                    report = _failure_report(definition, error)
                attempt_finished_at = resolved_now + timedelta(
                    seconds=monotonic() - execution_clock_started_at
                )
                success = _is_success(report)
                retry_class = _retry_class(report)
                should_retry = (
                    not success
                    and retry_class == "transient"
                    and attempt_number < settings.scheduler_max_attempts
                )
                backoff_seconds = (
                    _backoff_seconds(
                        completed_attempts=attempt_number,
                        settings=settings,
                        report=report,
                    )
                    if should_retry
                    else 0
                )
                metrics = _metrics(
                    engine,
                    report,
                    duration_seconds=(attempt_finished_at - attempt_started_at).total_seconds(),
                )
                error_codes = _safe_error_codes(report)
                _insert_attempt(
                    engine,
                    execution_id=execution_id,
                    attempt_number=attempt_number,
                    success=success,
                    started_at=attempt_started_at,
                    finished_at=attempt_finished_at,
                    ingestion_run_id=report.ingestion_run_id,
                    retry_class=None if success else retry_class,
                    backoff_seconds=backoff_seconds,
                    metrics=metrics,
                    error_codes=error_codes,
                )
                last_report = report
                last_metrics = metrics
                last_error_codes = error_codes
                last_finished_at = attempt_finished_at
                attempts_completed = attempt_number

                if success:
                    _finalize_execution(
                        engine,
                        execution_id=execution_id,
                        status=SourceExecutionStatus.SUCCEEDED,
                        finished_at=attempt_finished_at,
                        attempt_count=attempt_number,
                        ingestion_run_id=report.ingestion_run_id,
                        result_kind=_result_kind(report),
                        metrics=metrics,
                        error_codes=(),
                    )
                    return _result(
                        definition=definition,
                        execution_id=execution_id,
                        status=SourceExecutionStatus.SUCCEEDED,
                        trigger=trigger,
                        started_at=resolved_now,
                        finished_at=attempt_finished_at,
                        ingestion_run_id=report.ingestion_run_id,
                        attempt_count=attempt_number,
                        result_kind=_result_kind(report),
                        error_codes=(),
                        metrics=metrics,
                    )

                if should_retry:
                    sleeper(float(backoff_seconds))
                    continue
                break

            if last_report is None:
                raise RuntimeError("managed source execution finished without an adapter report")
            _finalize_execution(
                engine,
                execution_id=execution_id,
                status=SourceExecutionStatus.FAILED,
                finished_at=last_finished_at,
                attempt_count=attempts_completed,
                ingestion_run_id=last_report.ingestion_run_id,
                result_kind="failed",
                metrics=last_metrics,
                error_codes=last_error_codes,
            )
            return _result(
                definition=definition,
                execution_id=execution_id,
                status=SourceExecutionStatus.FAILED,
                trigger=trigger,
                started_at=resolved_now,
                finished_at=last_finished_at,
                ingestion_run_id=last_report.ingestion_run_id,
                attempt_count=attempts_completed,
                result_kind="failed",
                error_codes=last_error_codes,
                metrics=last_metrics,
            )
        finally:
            if lock_acquired:
                try:
                    _unlock(lock_connection, source_key)
                except SQLAlchemyError:
                    lock_connection.invalidate()


def run_due_sources(
    *,
    engine: Engine,
    settings: Settings,
    registry_path: Path | None = None,
    at: datetime | None = None,
    sleeper: Callable[[float], None] = sleep,
) -> SchedulerTickResult:
    """Execute due active sources once and continue after individual failures."""

    evaluated_at = _utc(at)
    resolved_registry_path = (
        settings.source_registry_path if registry_path is None else registry_path
    )
    registry = load_registry(resolved_registry_path)
    due_definitions = tuple(
        definition
        for definition in registry.sources.values()
        if definition.status is SourceRegistryStatus.ACTIVE
        and definition.schedule != "manual"
        and is_schedule_due(definition.schedule, evaluated_at)
    )
    scheduled_for = evaluated_at.replace(second=0, microsecond=0)
    results: list[SourceExecutionResult] = []
    for definition in sorted(due_definitions, key=lambda item: item.source_key):
        try:
            results.append(
                run_managed_source(
                    definition.source_key,
                    engine=engine,
                    settings=settings,
                    registry_path=resolved_registry_path,
                    registry=registry,
                    trigger=SourceExecutionTrigger.SCHEDULED,
                    scheduled_for=scheduled_for,
                    now=evaluated_at,
                    sleeper=sleeper,
                )
            )
        except Exception as error:
            source_id = _ensure_source(engine, definition)
            metrics = {
                "status": "failed",
                "result_kind": "failed",
                "reason": "scheduler_dispatch_error",
            }
            execution_id = _insert_execution(
                engine,
                source_id=source_id,
                definition=definition,
                trigger=SourceExecutionTrigger.SCHEDULED,
                status=SourceExecutionStatus.FAILED,
                started_at=evaluated_at,
                finished_at=evaluated_at,
                scheduled_for=scheduled_for,
                result_kind="failed",
                metrics=metrics,
                error_codes=("scheduler_dispatch_error",),
            )
            del error
            results.append(
                _result(
                    definition=definition,
                    execution_id=execution_id,
                    status=SourceExecutionStatus.FAILED,
                    trigger=SourceExecutionTrigger.SCHEDULED,
                    started_at=evaluated_at,
                    finished_at=evaluated_at,
                    ingestion_run_id=None,
                    attempt_count=0,
                    result_kind="failed",
                    error_codes=("scheduler_dispatch_error",),
                    metrics=metrics,
                )
            )
    return SchedulerTickResult(
        evaluated_at=evaluated_at,
        due_source_keys=tuple(definition.source_key for definition in due_definitions),
        results=tuple(results),
    )


def list_execution_runs(
    engine: Engine,
    *,
    source_key: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    statement = select(
        SourceExecutionRun.id,
        SourceExecutionRun.source_key,
        SourceExecutionRun.trigger,
        SourceExecutionRun.status,
        SourceExecutionRun.started_at,
        SourceExecutionRun.finished_at,
        SourceExecutionRun.ingestion_run_id,
        SourceExecutionRun.attempt_count,
        SourceExecutionRun.result_kind,
        SourceExecutionRun.error_codes,
        SourceExecutionRun.metrics,
    ).order_by(SourceExecutionRun.started_at.desc(), SourceExecutionRun.id.desc()).limit(limit)
    if source_key is not None:
        statement = statement.where(SourceExecutionRun.source_key == source_key)
    with engine.connect() as connection:
        rows = connection.execute(statement).mappings()
        return [
            {
                "execution_id": row["id"],
                "source_key": row["source_key"],
                "trigger": SourceExecutionTrigger(row["trigger"]),
                "status": SourceExecutionStatus(row["status"]),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "ingestion_run_id": row["ingestion_run_id"],
                "attempt_count": row["attempt_count"],
                "result_kind": row["result_kind"],
                "error_codes": tuple(row["error_codes"]),
                "metrics": dict(row["metrics"]),
            }
            for row in rows
        ]


def prune_execution_journal(
    engine: Engine,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    """Delete only completed operational journal rows; provenance is untouched."""

    if retention_days < 1:
        raise ValueError("retention_days must be at least one")
    cutoff = _utc(now) - timedelta(days=retention_days)
    with engine.begin() as connection:
        result = connection.execute(
            delete(SourceExecutionRun).where(
                SourceExecutionRun.finished_at.is_not(None),
                SourceExecutionRun.finished_at < cutoff,
                SourceExecutionRun.status != SourceExecutionStatus.RUNNING,
            )
        )
    return int(result.rowcount or 0)

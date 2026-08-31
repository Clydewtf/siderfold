from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.domain.models import (
    IngestionRun,
    IngestionRunStatus,
    SourceExecutionAttempt,
    SourceExecutionAttemptStatus,
    SourceExecutionRun,
    SourceExecutionStatus,
    SourceExecutionTrigger,
)
from app.sources.contract import AdapterIssue, AdapterReport, AdapterStage, RunStatistics
from app.sources.operations import (
    _ensure_source,
    _lock_key,
    _try_lock,
    _unlock,
    list_execution_runs,
    prune_execution_journal,
    run_due_sources,
    run_managed_source,
)
from app.sources.registry import DEFAULT_REGISTRY_PATH


pytestmark = pytest.mark.postgres

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = BACKEND_ROOT / "tests" / "fixtures" / "adapters" / "catalog_v1.json"
NOW = datetime(2026, 9, 1, 4, 15, tzinfo=timezone.utc)


def _settings(test_database_url: str, registry_path: Path, tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": test_database_url,
        "source_registry_path": registry_path,
        "raw_capture_dir": tmp_path / "raw",
        "scheduler_max_attempts": 3,
        "scheduler_initial_backoff_seconds": 2,
        "scheduler_max_backoff_seconds": 60,
        "scheduler_retry_after_max_seconds": 60,
        "scheduler_run_lease_seconds": 900,
        "scheduler_journal_retention_days": 90,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def _registry(
    tmp_path: Path,
    *,
    source_keys: tuple[str, ...] = ("fixture-one",),
    schedules: dict[str, str] | None = None,
    min_run_interval_seconds: int = 0,
) -> Path:
    schedules = schedules or {}
    registry_path = tmp_path / "config" / "sources.toml"
    registry_path.parent.mkdir()
    entries = ["version = 1"]
    for source_key in source_keys:
        entries.append(
            f'''
[sources.{source_key}]
source_key = "{source_key}"
name = "{source_key} fixture"
canonical_url = "https://{source_key}.fixture.test/catalog"
allowed_url_prefixes = ["https://{source_key}.fixture.test/catalog"]
access_method = "fixture"
schedule = "{schedules.get(source_key, "* * * * *")}"
status = "active"
responsible = "tests"
adapter_name = "fixture-catalog"
adapter_version = "1.0.0"
fixture_path = "{FIXTURE_PATH}"
secret_env_vars = []

[sources.{source_key}.limits]
max_requests = 1
max_response_bytes = 100000
max_total_bytes = 100000
max_records = 100
timeout_seconds = 5
min_run_interval_seconds = {min_run_interval_seconds}
'''
        )
    registry_path.write_text("\n".join(entries), encoding="utf-8")
    return registry_path


def _report(
    source_key: str,
    *,
    status: str = "completed",
    errors: int = 0,
    extracted: int = 1,
    issue: AdapterIssue | None = None,
) -> AdapterReport:
    return AdapterReport(
        source_key=source_key,
        adapter_name="fixture-catalog",
        adapter_version="1.0.0",
        status=status,  # type: ignore[arg-type]
        dry_run=False,
        statistics=RunStatistics(extracted=extracted, errors=errors),
        issues=(issue,) if issue is not None else (),
        import_counts={"new": 1, "updated": 0, "skipped": 0, "errors": errors},
    )


def test_managed_fixture_run_writes_execution_metrics_and_journal(
    migrated_engine: Engine,
    test_database_url: str,
    tmp_path: Path,
) -> None:
    settings = _settings(test_database_url, DEFAULT_REGISTRY_PATH, tmp_path)

    result = run_managed_source(
        "fixture-catalog",
        engine=migrated_engine,
        settings=settings,
    )

    assert result.status is SourceExecutionStatus.SUCCEEDED
    assert result.ingestion_run_id is not None
    assert result.attempt_count == 1
    assert result.metrics["records"] == {
        "new": 2,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    assert result.metrics["review_queue"] == {
        "canonical": 2,
        "discovery": 0,
        "total": 2,
    }
    assert result.metrics["freshness"] is not None

    with migrated_engine.connect() as connection:
        execution = connection.execute(
            select(
                SourceExecutionRun.status,
                SourceExecutionRun.attempt_count,
                SourceExecutionRun.ingestion_run_id,
            )
        ).one()
        assert execution.status is SourceExecutionStatus.SUCCEEDED
        assert execution.attempt_count == 1
        assert execution.ingestion_run_id == result.ingestion_run_id
        assert connection.scalar(select(func.count()).select_from(SourceExecutionAttempt)) == 1


def test_concurrent_source_lock_skips_second_execution_without_running_adapter(
    migrated_engine: Engine,
    test_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    settings = _settings(test_database_url, registry_path, tmp_path)

    def should_not_run(*args: object, **kwargs: object) -> AdapterReport:
        raise AssertionError("locked source must not invoke its adapter")

    monkeypatch.setattr("app.sources.operations.run_registered_source", should_not_run)
    with migrated_engine.connect() as lock_connection:
        assert _try_lock(lock_connection, "fixture-one")
        try:
            result = run_managed_source(
                "fixture-one",
                engine=migrated_engine,
                settings=settings,
                now=NOW,
            )
        finally:
            _unlock(lock_connection, "fixture-one")

    assert result.status is SourceExecutionStatus.SKIPPED_LOCKED
    assert result.error_codes == ("concurrent_execution",)
    assert result.attempt_count == 0


def test_transient_failure_retries_then_succeeds_with_recorded_backoff(
    migrated_engine: Engine,
    test_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    settings = _settings(test_database_url, registry_path, tmp_path)
    transient = _report(
        "fixture-one",
        status="failed",
        errors=1,
        issue=AdapterIssue(
            stage=AdapterStage.FETCH,
            severity="error",
            code="fetch_error",
            message="HTTP 503 for a bounded fixture request",
        ),
    )
    reports = [transient, _report("fixture-one")]
    sleeps: list[float] = []

    def fake_run(*args: object, **kwargs: object) -> AdapterReport:
        return reports.pop(0)

    monkeypatch.setattr("app.sources.operations.run_registered_source", fake_run)
    result = run_managed_source(
        "fixture-one",
        engine=migrated_engine,
        settings=settings,
        now=NOW,
        sleeper=sleeps.append,
    )

    assert result.status is SourceExecutionStatus.SUCCEEDED
    assert result.attempt_count == 2
    assert sleeps == [2.0]
    with migrated_engine.connect() as connection:
        attempts = connection.execute(
            select(
                SourceExecutionAttempt.status,
                SourceExecutionAttempt.retry_class,
                SourceExecutionAttempt.backoff_seconds,
            ).order_by(SourceExecutionAttempt.attempt_number)
        ).all()
    assert attempts == [
        (SourceExecutionAttemptStatus.FAILED, "transient", 2),
        (SourceExecutionAttemptStatus.SUCCEEDED, None, 0),
    ]


def test_retry_after_is_bounded_and_takes_precedence_over_base_backoff(
    migrated_engine: Engine,
    test_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    settings = _settings(
        test_database_url,
        registry_path,
        tmp_path,
        scheduler_retry_after_max_seconds=30,
    )
    transient = _report(
        "fixture-one",
        status="failed",
        errors=1,
        issue=AdapterIssue(
            stage=AdapterStage.FETCH,
            severity="error",
            code="fetch_error",
            message="HTTP 429 for a bounded fixture request; Retry-After: 120",
        ),
    )
    reports = [transient, _report("fixture-one")]
    sleeps: list[float] = []
    monkeypatch.setattr(
        "app.sources.operations.run_registered_source",
        lambda *args, **kwargs: reports.pop(0),
    )

    result = run_managed_source(
        "fixture-one",
        engine=migrated_engine,
        settings=settings,
        now=NOW,
        sleeper=sleeps.append,
    )

    assert result.status is SourceExecutionStatus.SUCCEEDED
    assert sleeps == [30.0]


def test_transient_database_availability_failure_retries(
    migrated_engine: Engine,
    test_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    settings = _settings(test_database_url, registry_path, tmp_path)
    results: list[AdapterReport | Exception] = [
        OperationalError(
            "SELECT 1",
            {},
            ConnectionRefusedError("database temporarily unavailable"),
        ),
        _report("fixture-one"),
    ]
    sleeps: list[float] = []

    def fake_run(*args: object, **kwargs: object) -> AdapterReport:
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("app.sources.operations.run_registered_source", fake_run)
    result = run_managed_source(
        "fixture-one",
        engine=migrated_engine,
        settings=settings,
        now=NOW,
        sleeper=sleeps.append,
    )

    assert result.status is SourceExecutionStatus.SUCCEEDED
    assert result.attempt_count == 2
    assert sleeps == [2.0]
    with migrated_engine.connect() as connection:
        first_attempt = connection.execute(
            select(
                SourceExecutionAttempt.retry_class,
                SourceExecutionAttempt.error_codes,
            )
            .where(SourceExecutionAttempt.attempt_number == 1)
        ).one()
    assert first_attempt == ("transient", ["database_unavailable"])


def test_completed_report_with_field_error_is_failed_not_empty_success(
    migrated_engine: Engine,
    test_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    settings = _settings(test_database_url, registry_path, tmp_path)
    report = _report(
        "fixture-one",
        errors=1,
        extracted=0,
        issue=AdapterIssue(
            stage=AdapterStage.VALIDATE,
            severity="error",
            code="invalid_deadline",
            message="Deadline was invalid",
            field="deadline_on",
        ),
    )
    monkeypatch.setattr(
        "app.sources.operations.run_registered_source",
        lambda *args, **kwargs: report,
    )

    result = run_managed_source(
        "fixture-one",
        engine=migrated_engine,
        settings=settings,
        now=NOW,
    )

    assert result.status is SourceExecutionStatus.FAILED
    assert result.result_kind == "failed"
    assert result.attempt_count == 1
    assert result.metrics["field_error_counts"] == {"deadline_on": 1}


def test_scheduler_continues_after_one_source_failure(
    migrated_engine: Engine,
    test_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path, source_keys=("fixture-one", "fixture-two"))
    settings = _settings(
        test_database_url,
        registry_path,
        tmp_path,
        scheduler_max_attempts=1,
    )

    def fake_run(source_key: str, **kwargs: object) -> AdapterReport:
        if source_key == "fixture-one":
            return _report(
                source_key,
                status="failed",
                errors=1,
                issue=AdapterIssue(
                    stage=AdapterStage.VALIDATE,
                    severity="error",
                    code="schema_changed",
                    message="Expected field is absent",
                ),
            )
        return _report(source_key)

    monkeypatch.setattr("app.sources.operations.run_registered_source", fake_run)
    tick = run_due_sources(
        engine=migrated_engine,
        settings=settings,
        registry_path=registry_path,
        at=NOW,
    )

    assert tick.due_source_keys == ("fixture-one", "fixture-two")
    assert [result.status for result in tick.results] == [
        SourceExecutionStatus.FAILED,
        SourceExecutionStatus.SUCCEEDED,
    ]
    assert tick.has_failures is True


def test_recovery_marks_abandoned_run_and_processing_ingestion_failed(
    migrated_engine: Engine,
    test_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path)
    settings = _settings(test_database_url, registry_path, tmp_path)
    from app.sources.registry import load_registry

    definition = load_registry(registry_path).get("fixture-one")
    source_id = _ensure_source(migrated_engine, definition)
    old_execution_id = uuid4()
    old_ingestion_id = uuid4()
    started_at = NOW - timedelta(minutes=30)
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(IngestionRun).values(
                id=old_ingestion_id,
                source_id=source_id,
                input_fingerprint=sha256(b"abandoned-ingestion").hexdigest(),
                adapter_name="fixture-catalog",
                adapter_version="1.0.0",
                status=IngestionRunStatus.RECEIVED,
                received_at=started_at,
            )
        )
        connection.execute(
            update(IngestionRun)
            .where(IngestionRun.id == old_ingestion_id)
            .values(status=IngestionRunStatus.PROCESSING, started_at=started_at)
        )
        connection.execute(
            insert(SourceExecutionRun).values(
                id=old_execution_id,
                source_id=source_id,
                source_key="fixture-one",
                trigger=SourceExecutionTrigger.MANUAL,
                status=SourceExecutionStatus.RUNNING,
                owner_token=uuid4(),
                started_at=started_at,
                lease_expires_at=started_at + timedelta(minutes=15),
                attempt_count=0,
                metrics={},
                error_codes=[],
            )
        )
    monkeypatch.setattr(
        "app.sources.operations.run_registered_source",
        lambda *args, **kwargs: _report("fixture-one"),
    )

    result = run_managed_source(
        "fixture-one",
        engine=migrated_engine,
        settings=settings,
        now=NOW,
    )

    assert result.status is SourceExecutionStatus.SUCCEEDED
    with migrated_engine.connect() as connection:
        old_execution = connection.execute(
            select(SourceExecutionRun.status, SourceExecutionRun.error_codes).where(
                SourceExecutionRun.id == old_execution_id
            )
        ).one()
        old_ingestion = connection.execute(
            select(IngestionRun.status, IngestionRun.run_statistics).where(
                IngestionRun.id == old_ingestion_id
            )
        ).one()
    assert old_execution.status is SourceExecutionStatus.INTERRUPTED
    assert "execution_interrupted" in old_execution.error_codes
    assert old_ingestion.status is IngestionRunStatus.FAILED
    assert old_ingestion.run_statistics["operational_recovery"]["reason"] == (
        "execution_interrupted_before_terminal_status"
    )


def test_manual_rate_limit_and_explicit_journal_pruning(
    migrated_engine: Engine,
    test_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _registry(tmp_path, min_run_interval_seconds=300)
    settings = _settings(test_database_url, registry_path, tmp_path)
    monkeypatch.setattr(
        "app.sources.operations.run_registered_source",
        lambda *args, **kwargs: _report("fixture-one"),
    )

    first = run_managed_source(
        "fixture-one",
        engine=migrated_engine,
        settings=settings,
        now=NOW,
    )
    second = run_managed_source(
        "fixture-one",
        engine=migrated_engine,
        settings=settings,
        now=NOW + timedelta(seconds=1),
    )

    assert first.status is SourceExecutionStatus.SUCCEEDED
    assert second.status is SourceExecutionStatus.SKIPPED_RATE_LIMITED
    assert second.metrics["next_allowed_at"] == (NOW + timedelta(minutes=5)).isoformat()
    assert len(list_execution_runs(migrated_engine, source_key="fixture-one")) == 2

    removed = prune_execution_journal(
        migrated_engine,
        retention_days=1,
        now=NOW + timedelta(days=2),
    )
    assert removed == 2
    assert list_execution_runs(migrated_engine, source_key="fixture-one") == []

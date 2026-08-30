from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.domain.models import (
    IngestionRun,
    IngestionRunStatus,
    Program,
    RawCapture,
    ReviewDecision,
    Source,
    StagedRecord,
    StagedRecordState,
)
from app.sources.registry import DEFAULT_REGISTRY_PATH
from app.sources.runner import run_registered_source


pytestmark = pytest.mark.postgres

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_dry_run_does_not_write_database_records(migrated_engine: Engine) -> None:
    report = run_registered_source(
        "fixture-catalog",
        registry_path=DEFAULT_REGISTRY_PATH,
        engine=migrated_engine,
        dry_run=True,
        project_root=BACKEND_ROOT,
    )

    assert report.status == "completed"
    assert report.dry_run is True
    assert report.source_id is None
    assert report.ingestion_run_id is None
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Source)) == 0
        assert connection.scalar(select(func.count()).select_from(IngestionRun)) == 0
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 0
        assert connection.scalar(select(func.count()).select_from(StagedRecord)) == 0


def test_normal_run_persists_statistics_and_review_candidates(
    migrated_engine: Engine,
) -> None:
    report = run_registered_source(
        "fixture-catalog",
        registry_path=DEFAULT_REGISTRY_PATH,
        engine=migrated_engine,
        project_root=BACKEND_ROOT,
    )

    assert report.status == "completed"
    assert report.dry_run is False
    assert report.statistics.extracted == 2
    assert report.import_counts == {"new": 2, "updated": 0, "skipped": 0, "errors": 0}

    with migrated_engine.connect() as connection:
        run = connection.execute(
            select(IngestionRun.status, IngestionRun.run_statistics)
        ).one()
        assert run.status == IngestionRunStatus.COMPLETED
        assert run.run_statistics["discovered"] == 1
        assert run.run_statistics["warnings"] == 1
        assert run.run_statistics["import"] == {
            "new": 2,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
        }
        assert connection.scalar(select(func.count()).select_from(Source)) == 1
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 1
        assert connection.scalar(select(func.count()).select_from(StagedRecord)) == 2
        assert connection.scalar(select(func.count()).select_from(Program)) == 0
        assert connection.scalar(select(func.count()).select_from(ReviewDecision)) == 0
        assert set(connection.scalars(select(StagedRecord.state))) == {StagedRecordState.REVIEW}


def test_repeated_normal_run_reuses_import_idempotency_key(
    migrated_engine: Engine,
) -> None:
    first = run_registered_source(
        "fixture-catalog",
        registry_path=DEFAULT_REGISTRY_PATH,
        engine=migrated_engine,
        project_root=BACKEND_ROOT,
    )
    repeated = run_registered_source(
        "fixture-catalog",
        registry_path=DEFAULT_REGISTRY_PATH,
        engine=migrated_engine,
        project_root=BACKEND_ROOT,
    )

    assert repeated.ingestion_run_id == first.ingestion_run_id
    assert repeated.import_counts == {"new": 0, "updated": 0, "skipped": 2, "errors": 0}
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(IngestionRun)) == 1
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 1
        assert connection.scalar(select(func.count()).select_from(StagedRecord)) == 2


def test_failed_fetch_persists_failed_run_without_candidates(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "sources.toml"
    registry_path.write_text(
        """version = 1

[sources.broken-fixture]
source_key = "broken-fixture"
name = "Broken fixture"
canonical_url = "https://broken.fixture.test/catalog"
allowed_url_prefixes = ["https://broken.fixture.test/catalog"]
access_method = "fixture"
schedule = "manual"
status = "active"
responsible = "data-team"
adapter_name = "fixture-catalog"
adapter_version = "1.0.0"
fixture_path = "missing.json"

[sources.broken-fixture.limits]
max_requests = 1
max_response_bytes = 100000
max_total_bytes = 100000
max_records = 100
timeout_seconds = 5
""",
        encoding="utf-8",
    )

    report = run_registered_source(
        "broken-fixture",
        registry_path=registry_path,
        engine=migrated_engine,
        project_root=tmp_path,
    )

    assert report.status == "failed"
    assert report.ingestion_run_id is not None
    assert report.issues[0].code == "fetch_error"
    with migrated_engine.connect() as connection:
        run = connection.execute(
            select(IngestionRun.status, IngestionRun.run_statistics)
        ).one()
        assert run.status == IngestionRunStatus.FAILED
        assert run.run_statistics["errors"] == 1
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 0
        assert connection.scalar(select(func.count()).select_from(StagedRecord)) == 0
        assert connection.scalar(select(func.count()).select_from(Program)) == 0

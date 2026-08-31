from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.domain.models import (
    DataQualityIssue,
    DeduplicationMatch,
    DeduplicationMatchDisposition,
    IngestionRun,
    Program,
    RawCapture,
    ReviewAction,
    ReviewActionType,
    ReviewCase,
    ReviewDecision,
    Source,
    StagedRecord,
    StagedRecordState,
)
from app.import_bridge.contract import load_json_contract
from app.import_bridge.service import import_package


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "imports"


def _fixture_package():
    return load_json_contract(FIXTURES_ROOT / "potanin_import_v1.json")


def test_import_creates_review_candidates_without_canonical_publication(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        report = import_package(connection, _fixture_package())

    assert report.new_count == 2
    assert report.updated_count == 0
    assert report.skipped_count == 0
    assert report.error_count == 0

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Source)) == 1
        assert connection.scalar(select(func.count()).select_from(IngestionRun)) == 1
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 1
        assert connection.scalar(select(func.count()).select_from(StagedRecord)) == 2
        assert connection.scalar(select(func.count()).select_from(DataQualityIssue)) == 1
        assert connection.scalar(select(func.count()).select_from(ReviewCase)) == 2
        assert connection.scalar(select(func.count()).select_from(Program)) == 0
        assert connection.scalar(select(func.count()).select_from(ReviewDecision)) == 0
        assert set(connection.scalars(select(StagedRecord.state))) == {StagedRecordState.REVIEW}


def test_identical_repeat_is_skipped_without_duplicate_provenance(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        first_report = import_package(connection, _fixture_package())

    with migrated_engine.begin() as connection:
        repeated_report = import_package(connection, _fixture_package())

    assert first_report.ingestion_run_id == repeated_report.ingestion_run_id
    assert repeated_report.new_count == 0
    assert repeated_report.updated_count == 0
    assert repeated_report.skipped_count == 2
    assert repeated_report.error_count == 0

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(IngestionRun)) == 1
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 1
        assert connection.scalar(select(func.count()).select_from(StagedRecord)) == 2


def test_changed_record_creates_a_new_candidate_and_reports_update(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    with migrated_engine.begin() as connection:
        import_package(connection, _fixture_package())

    revised_payload = json.loads((FIXTURES_ROOT / "potanin_import_v1.json").read_text())
    revised_payload["records"] = [revised_payload["records"][0]]
    revised_payload["records"][0]["title"] = "Конкурс A: обновлённая версия"
    revised_path = tmp_path / "revised.json"
    revised_path.write_text(json.dumps(revised_payload))

    with migrated_engine.begin() as connection:
        report = import_package(connection, load_json_contract(revised_path))

    assert report.new_count == 0
    assert report.updated_count == 1
    assert report.rows[0].previous_staged_record_id is not None

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(IngestionRun)) == 2
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 2
        assert connection.scalar(select(func.count()).select_from(StagedRecord)) == 3


def test_clean_exact_duplicate_auto_merges_after_its_run_is_completed(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    payload = json.loads((FIXTURES_ROOT / "potanin_import_v1.json").read_text())
    payload["records"] = [payload["records"][1]]
    first_path = tmp_path / "clean-import.json"
    second_path = tmp_path / "clean-import-repeat.json"
    first_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    second_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    with migrated_engine.begin() as connection:
        import_package(connection, load_json_contract(first_path))
    with migrated_engine.begin() as connection:
        repeated = import_package(connection, load_json_contract(second_path))

    candidate_id = repeated.rows[0].staged_record_id
    assert candidate_id is not None
    assert repeated.rows[0].status == "updated"
    with migrated_engine.connect() as connection:
        match = connection.execute(
            select(DeduplicationMatch.disposition).where(
                DeduplicationMatch.candidate_staged_record_id == candidate_id
            )
        ).one()
        assert match.disposition is DeduplicationMatchDisposition.AUTO_MERGED
        assert connection.scalar(
            select(ReviewAction.action)
            .join(ReviewCase, ReviewCase.id == ReviewAction.review_case_id)
            .where(ReviewCase.staged_record_id == candidate_id)
        ) is ReviewActionType.AUTO_MERGE
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == candidate_id)
        ) is StagedRecordState.REJECTED


def test_invalid_rows_have_quality_issues_and_do_not_block_valid_candidates(
    migrated_engine: Engine,
    tmp_path: Path,
) -> None:
    payload = json.loads((FIXTURES_ROOT / "potanin_import_v1.json").read_text())
    payload["records"].append(
        {
            "record_key": "",
            "title": "",
            "record_url": "not-a-url"
        }
    )
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(payload))

    with migrated_engine.begin() as connection:
        report = import_package(connection, load_json_contract(invalid_path))

    assert report.new_count == 2
    assert report.error_count == 1
    error_row = next(row for row in report.rows if row.status == "error")
    assert error_row.staged_record_id is not None
    assert {issue.field for issue in error_row.issues} >= {"record_key", "title", "record_url"}

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == error_row.staged_record_id)
        ) == StagedRecordState.ERROR
        assert connection.scalar(
            select(func.count())
            .select_from(DataQualityIssue)
            .where(DataQualityIssue.staged_record_id == error_row.staged_record_id)
        ) == len(error_row.issues)


def test_dry_run_transaction_leaves_no_records(migrated_engine: Engine) -> None:
    connection = migrated_engine.connect()
    transaction = connection.begin()
    try:
        report = import_package(connection, _fixture_package())
        transaction.rollback()
    finally:
        connection.close()

    assert report.new_count == 2
    with migrated_engine.connect() as verification_connection:
        assert verification_connection.scalar(select(func.count()).select_from(Source)) == 0
        assert verification_connection.scalar(select(func.count()).select_from(IngestionRun)) == 0
        assert verification_connection.scalar(select(func.count()).select_from(RawCapture)) == 0
        assert verification_connection.scalar(select(func.count()).select_from(StagedRecord)) == 0

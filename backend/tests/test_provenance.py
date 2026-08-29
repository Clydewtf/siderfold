from __future__ import annotations

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
import pytest

from app.domain.ingestion import build_input_fingerprint, get_or_create_ingestion_run
from app.domain.models import (
    DataQualityIssue,
    DataQualitySeverity,
    IngestionRun,
    IngestionRunStatus,
    Program,
    PublicationStatus,
    RawCapture,
    ReviewDecision,
    ReviewDecisionOutcome,
    Source,
    StagedRecord,
    StagedRecordState,
)
from tests.fixtures.canonical import PUBLISHED_AT, insert_program_with_source, insert_source
from tests.fixtures.provenance import (
    FINISHED_AT,
    STARTED_AT,
    create_published_provenance,
    finish_ingestion_run,
    insert_ingestion_run,
    insert_raw_capture,
    insert_review_decision,
    insert_staged_record,
    start_ingestion_run,
    transition_staged_record,
)


pytestmark = pytest.mark.postgres


def test_ingestion_and_staging_state_machines_reject_forbidden_transitions(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        run_id = insert_ingestion_run(connection, source_id=source_id)

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                update(IngestionRun)
                .where(IngestionRun.id == run_id)
                .values(
                    status=IngestionRunStatus.COMPLETED,
                    started_at=STARTED_AT,
                    finished_at=FINISHED_AT,
                )
            )

    with migrated_engine.begin() as connection:
        start_ingestion_run(connection, run_id=run_id)
        finish_ingestion_run(connection, run_id=run_id, status=IngestionRunStatus.FAILED)
        capture_id = insert_raw_capture(connection, ingestion_run_id=run_id)
        staged_record_id = insert_staged_record(connection, raw_capture_id=capture_id)

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            transition_staged_record(
                connection,
                staged_record_id=staged_record_id,
                state=StagedRecordState.PUBLISHED,
            )

    with migrated_engine.begin() as connection:
        transition_staged_record(
            connection,
            staged_record_id=staged_record_id,
            state=StagedRecordState.EXTRACTED,
        )
        connection.execute(
            insert(DataQualityIssue).values(
                staged_record_id=staged_record_id,
                severity=DataQualitySeverity.WARNING,
                code="deadline_missing",
                message="The source does not provide a deadline.",
            )
        )
        transition_staged_record(
            connection,
            staged_record_id=staged_record_id,
            state=StagedRecordState.WARNING,
        )
        transition_staged_record(
            connection,
            staged_record_id=staged_record_id,
            state=StagedRecordState.REVIEW,
        )
        transition_staged_record(
            connection,
            staged_record_id=staged_record_id,
            state=StagedRecordState.REJECTED,
        )

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            transition_staged_record(
                connection,
                staged_record_id=staged_record_id,
                state=StagedRecordState.REVIEW,
            )


def test_raw_capture_and_review_decision_are_append_only(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        run_id = insert_ingestion_run(connection, source_id=source_id)
        capture_id = insert_raw_capture(connection, ingestion_run_id=run_id)
        staged_record_id = insert_staged_record(connection, raw_capture_id=capture_id)
        transition_staged_record(
            connection,
            staged_record_id=staged_record_id,
            state=StagedRecordState.EXTRACTED,
        )
        transition_staged_record(
            connection,
            staged_record_id=staged_record_id,
            state=StagedRecordState.REVIEW,
        )
        decision_id = insert_review_decision(connection, staged_record_id=staged_record_id)

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                update(RawCapture)
                .where(RawCapture.id == capture_id)
                .values(source_url="https://source.example.test/changed")
            )

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(delete(RawCapture).where(RawCapture.id == capture_id))

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                update(ReviewDecision)
                .where(ReviewDecision.id == decision_id)
                .values(reason="Changed later")
            )

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(RawCapture.source_url).where(RawCapture.id == capture_id)
        ) == f"https://source.example.test/raw/{capture_id}"
        assert connection.scalar(
            select(ReviewDecision.reason).where(ReviewDecision.id == decision_id)
        ) == "Fixture review decision"


def test_repeated_input_reuses_the_original_ingestion_run(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        fingerprint = build_input_fingerprint(
            source_url="https://source.example.test/feed",
            content=b"same normalized input",
            adapter_name="catalog-adapter",
            adapter_version="1.0.0",
        )
        first_run_id, created = get_or_create_ingestion_run(
            connection,
            source_id=source_id,
            input_fingerprint=fingerprint,
            adapter_name="catalog-adapter",
            adapter_version="1.0.0",
        )
        repeated_run_id, repeated_created = get_or_create_ingestion_run(
            connection,
            source_id=source_id,
            input_fingerprint=fingerprint,
            adapter_name="catalog-adapter",
            adapter_version="1.0.0",
        )

    assert created is True
    assert repeated_created is False
    assert repeated_run_id == first_run_id

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(func.count())
            .select_from(IngestionRun)
            .where(
                IngestionRun.source_id == source_id,
                IngestionRun.input_fingerprint == fingerprint,
            )
        ) == 1


def test_published_program_has_a_complete_provenance_trace(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        program_id = insert_program_with_source(
            connection,
            source_id=source_id,
            publication_status=PublicationStatus.PUBLISHED,
            published_at=PUBLISHED_AT,
        )

    with migrated_engine.connect() as connection:
        trace = connection.execute(
            select(
                Source.id.label("source_id"),
                IngestionRun.id.label("run_id"),
                RawCapture.id.label("capture_id"),
                StagedRecord.id.label("staged_record_id"),
                ReviewDecision.id.label("decision_id"),
                IngestionRun.status,
                StagedRecord.state,
                ReviewDecision.decision,
            )
            .select_from(Program)
            .join(
                ReviewDecision,
                ReviewDecision.id == Program.publication_review_decision_id,
            )
            .join(StagedRecord, StagedRecord.id == ReviewDecision.staged_record_id)
            .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
            .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
            .join(Source, Source.id == IngestionRun.source_id)
            .where(Program.id == program_id)
        ).one()

    assert trace.source_id == source_id
    assert trace.run_id
    assert trace.capture_id
    assert trace.staged_record_id
    assert trace.decision_id
    assert trace.status == IngestionRunStatus.COMPLETED
    assert trace.state == StagedRecordState.PUBLISHED
    assert trace.decision == ReviewDecisionOutcome.PUBLISH


def test_failed_ingestion_run_cannot_publish_a_program(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            source_id = insert_source(connection)
            program_id = insert_program_with_source(connection, source_id=source_id)
            run_id = insert_ingestion_run(connection, source_id=source_id)
            start_ingestion_run(connection, run_id=run_id)
            finish_ingestion_run(connection, run_id=run_id, status=IngestionRunStatus.FAILED)
            capture_id = insert_raw_capture(connection, ingestion_run_id=run_id)
            staged_record_id = insert_staged_record(connection, raw_capture_id=capture_id)
            transition_staged_record(
                connection,
                staged_record_id=staged_record_id,
                state=StagedRecordState.EXTRACTED,
            )
            transition_staged_record(
                connection,
                staged_record_id=staged_record_id,
                state=StagedRecordState.REVIEW,
            )
            decision_id = insert_review_decision(
                connection,
                staged_record_id=staged_record_id,
                decision=ReviewDecisionOutcome.PUBLISH,
            )
            transition_staged_record(
                connection,
                staged_record_id=staged_record_id,
                state=StagedRecordState.PUBLISHED,
            )
            connection.execute(
                update(Program)
                .where(Program.id == program_id)
                .values(
                    publication_status=PublicationStatus.PUBLISHED,
                    published_at=PUBLISHED_AT,
                    publication_review_decision_id=decision_id,
                )
            )


def test_review_decision_requires_a_record_in_review(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        run_id = insert_ingestion_run(connection, source_id=source_id)
        capture_id = insert_raw_capture(connection, ingestion_run_id=run_id)
        staged_record_id = insert_staged_record(connection, raw_capture_id=capture_id)

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            insert_review_decision(connection, staged_record_id=staged_record_id)


def test_staging_chain_can_be_published_after_completed_review(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        provenance = create_published_provenance(connection, source_id=source_id)

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == provenance.staged_record_id)
        ) == StagedRecordState.PUBLISHED

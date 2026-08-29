from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import insert, update
from sqlalchemy.engine import Connection

from app.domain.models import (
    IngestionRun,
    IngestionRunStatus,
    RawCapture,
    ReviewDecision,
    ReviewDecisionOutcome,
    StagedRecord,
    StagedRecordState,
)


RECEIVED_AT = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)
STARTED_AT = RECEIVED_AT + timedelta(minutes=1)
FINISHED_AT = RECEIVED_AT + timedelta(minutes=2)


@dataclass(frozen=True)
class PublishedProvenance:
    ingestion_run_id: UUID
    raw_capture_id: UUID
    staged_record_id: UUID
    review_decision_id: UUID


def _digest(*parts: str) -> str:
    value = "\x00".join(parts).encode("utf-8")
    return sha256(value).hexdigest()


def insert_ingestion_run(connection: Connection, *, source_id: UUID) -> UUID:
    run_id = uuid4()
    connection.execute(
        insert(IngestionRun).values(
            id=run_id,
            source_id=source_id,
            input_fingerprint=_digest("input", str(run_id)),
            adapter_name="fixture-adapter",
            adapter_version="1.0.0",
            status=IngestionRunStatus.RECEIVED,
            received_at=RECEIVED_AT,
        )
    )
    return run_id


def start_ingestion_run(connection: Connection, *, run_id: UUID) -> None:
    connection.execute(
        update(IngestionRun)
        .where(IngestionRun.id == run_id)
        .values(status=IngestionRunStatus.PROCESSING, started_at=STARTED_AT)
    )


def finish_ingestion_run(
    connection: Connection,
    *,
    run_id: UUID,
    status: IngestionRunStatus = IngestionRunStatus.COMPLETED,
) -> None:
    connection.execute(
        update(IngestionRun)
        .where(IngestionRun.id == run_id)
        .values(status=status, finished_at=FINISHED_AT)
    )


def insert_raw_capture(connection: Connection, *, ingestion_run_id: UUID) -> UUID:
    capture_id = uuid4()
    connection.execute(
        insert(RawCapture).values(
            id=capture_id,
            ingestion_run_id=ingestion_run_id,
            content_sha256=_digest("raw", str(capture_id)),
            source_url=f"https://source.example.test/raw/{capture_id}",
            received_at=RECEIVED_AT,
            content_format="text/html",
            adapter_name="fixture-adapter",
            adapter_version="1.0.0",
            response_metadata={"http_status": 200},
            external_content_uri=f"s3://siderfold-fixtures/raw/{capture_id}.html",
        )
    )
    return capture_id


def insert_staged_record(connection: Connection, *, raw_capture_id: UUID) -> UUID:
    staged_record_id = uuid4()
    connection.execute(
        insert(StagedRecord).values(
            id=staged_record_id,
            raw_capture_id=raw_capture_id,
            record_key=f"program:{staged_record_id}",
            candidate_payload={"title": "Fixture program"},
            state=StagedRecordState.RECEIVED,
            created_at=RECEIVED_AT,
            updated_at=RECEIVED_AT,
        )
    )
    return staged_record_id


def transition_staged_record(
    connection: Connection,
    *,
    staged_record_id: UUID,
    state: StagedRecordState,
) -> None:
    connection.execute(
        update(StagedRecord)
        .where(StagedRecord.id == staged_record_id)
        .values(state=state, updated_at=FINISHED_AT)
    )


def insert_review_decision(
    connection: Connection,
    *,
    staged_record_id: UUID,
    decision: ReviewDecisionOutcome = ReviewDecisionOutcome.PUBLISH,
) -> UUID:
    decision_id = uuid4()
    connection.execute(
        insert(ReviewDecision).values(
            id=decision_id,
            staged_record_id=staged_record_id,
            decision=decision,
            reason="Fixture review decision",
            decided_at=FINISHED_AT,
        )
    )
    return decision_id


def create_published_provenance(
    connection: Connection,
    *,
    source_id: UUID,
) -> PublishedProvenance:
    run_id = insert_ingestion_run(connection, source_id=source_id)
    start_ingestion_run(connection, run_id=run_id)
    finish_ingestion_run(connection, run_id=run_id)
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
    transition_staged_record(
        connection,
        staged_record_id=staged_record_id,
        state=StagedRecordState.PUBLISHED,
    )
    return PublishedProvenance(
        ingestion_run_id=run_id,
        raw_capture_id=capture_id,
        staged_record_id=staged_record_id,
        review_decision_id=decision_id,
    )

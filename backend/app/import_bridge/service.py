from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection

from app.domain.ingestion import build_input_fingerprint, get_or_create_ingestion_run
from app.domain.models import (
    DataQualityIssue,
    DataQualitySeverity,
    IngestionRun,
    IngestionRunStatus,
    RawCapture,
    Source,
    StagedRecord,
    StagedRecordState,
)
from app.import_bridge.contract import CONTRACT_VERSION, ImportPackage, ParsedRow, ValidationIssue


REPORT_VERSION = "siderfold.import-report/v1"


class ImportRowReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_number: int = Field(ge=1)
    record_key: str | None = None
    status: Literal["new", "updated", "skipped", "error"]
    staged_record_id: UUID | None = None
    previous_staged_record_id: UUID | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)


class ImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: Literal[REPORT_VERSION] = REPORT_VERSION
    contract_version: str = CONTRACT_VERSION
    dry_run: bool = False
    source_id: UUID | None = None
    source_created: bool = False
    ingestion_run_id: UUID | None = None
    raw_capture_id: UUID | None = None
    new_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    rows: list[ImportRowReport] = Field(default_factory=list)
    package_errors: list[ValidationIssue] = Field(default_factory=list)

    @classmethod
    def invalid_package(cls, issues: list[ValidationIssue]) -> ImportReport:
        return cls(error_count=len(issues), package_errors=issues)


def _get_or_create_source(connection: Connection, package: ImportPackage) -> tuple[UUID, bool]:
    source_id = uuid4()
    statement = (
        postgresql_insert(Source)
        .values(
            id=source_id,
            name=package.metadata.source.name,
            canonical_url=package.metadata.source.canonical_url,
        )
        .on_conflict_do_nothing(index_elements=("canonical_url",))
        .returning(Source.id)
    )
    persisted_source_id = connection.scalar(statement)
    if persisted_source_id is not None:
        return persisted_source_id, True

    existing_source_id = connection.scalar(
        select(Source.id).where(Source.canonical_url == package.metadata.source.canonical_url)
    )
    if existing_source_id is None:
        raise RuntimeError("source was not persisted after a canonical URL conflict")
    return existing_source_id, False


def _transition_ingestion_run(
    connection: Connection,
    *,
    run_id: UUID,
    status: IngestionRunStatus,
    now: datetime,
) -> None:
    values: dict[str, object] = {"status": status}
    if status is IngestionRunStatus.PROCESSING:
        values["started_at"] = now
    elif status in {IngestionRunStatus.COMPLETED, IngestionRunStatus.FAILED}:
        values["finished_at"] = now
    connection.execute(update(IngestionRun).where(IngestionRun.id == run_id).values(**values))


def _transition_staged_record(
    connection: Connection,
    *,
    staged_record_id: UUID,
    state: StagedRecordState,
    now: datetime,
) -> None:
    connection.execute(
        update(StagedRecord)
        .where(StagedRecord.id == staged_record_id)
        .values(state=state, updated_at=now)
    )


def _create_data_quality_issue(
    connection: Connection,
    *,
    staged_record_id: UUID,
    severity: DataQualitySeverity,
    code: str,
    message: str,
) -> None:
    connection.execute(
        insert(DataQualityIssue).values(
            id=uuid4(),
            staged_record_id=staged_record_id,
            severity=severity,
            code=code,
            message=message,
        )
    )


def _create_error_staging_record(
    connection: Connection,
    *,
    package: ImportPackage,
    raw_capture_id: UUID,
    row: ParsedRow,
    now: datetime,
) -> UUID:
    staged_record_id = uuid4()
    connection.execute(
        insert(StagedRecord).values(
            id=staged_record_id,
            raw_capture_id=raw_capture_id,
            record_key=f"invalid:{row.row_number}",
            candidate_payload={
                "contract_version": package.metadata.contract_version,
                "row_number": row.row_number,
                "invalid_fields": [issue.field for issue in row.issues],
            },
            state=StagedRecordState.RECEIVED,
            created_at=now,
            updated_at=now,
        )
    )
    _transition_staged_record(
        connection,
        staged_record_id=staged_record_id,
        state=StagedRecordState.ERROR,
        now=now,
    )
    for index, issue in enumerate(row.issues, 1):
        _create_data_quality_issue(
            connection,
            staged_record_id=staged_record_id,
            severity=DataQualitySeverity.ERROR,
            code=f"import_error_{index}",
            message=f"{issue.field}: {issue.message}",
        )
    return staged_record_id


def _find_previous_staged_record(
    connection: Connection,
    *,
    source_id: UUID,
    record_key: str,
) -> UUID | None:
    return connection.scalar(
        select(StagedRecord.id)
        .select_from(StagedRecord)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
        .where(
            IngestionRun.source_id == source_id,
            StagedRecord.record_key == record_key,
        )
        .order_by(StagedRecord.created_at.desc())
        .limit(1)
    )


def _create_candidate_staging_record(
    connection: Connection,
    *,
    package: ImportPackage,
    raw_capture_id: UUID,
    row: ParsedRow,
    now: datetime,
) -> UUID:
    if row.record is None:
        raise ValueError("candidate staging records require a valid import record")

    staged_record_id = uuid4()
    connection.execute(
        insert(StagedRecord).values(
            id=staged_record_id,
            raw_capture_id=raw_capture_id,
            record_key=row.record.record_key,
            candidate_payload={
                "contract_version": package.metadata.contract_version,
                "record": row.record.candidate_payload(),
            },
            state=StagedRecordState.RECEIVED,
            created_at=now,
            updated_at=now,
        )
    )
    _transition_staged_record(
        connection,
        staged_record_id=staged_record_id,
        state=StagedRecordState.EXTRACTED,
        now=now,
    )
    if row.record.warnings:
        for index, message in enumerate(row.record.warnings, 1):
            _create_data_quality_issue(
                connection,
                staged_record_id=staged_record_id,
                severity=DataQualitySeverity.WARNING,
                code=f"import_warning_{index}",
                message=message,
            )
        _transition_staged_record(
            connection,
            staged_record_id=staged_record_id,
            state=StagedRecordState.WARNING,
            now=now,
        )
    _transition_staged_record(
        connection,
        staged_record_id=staged_record_id,
        state=StagedRecordState.REVIEW,
        now=now,
    )
    return staged_record_id


def _duplicate_package_report(
    package: ImportPackage,
    *,
    source_id: UUID,
    run_id: UUID,
    raw_capture_id: UUID | None,
) -> ImportReport:
    report = ImportReport(
        source_id=source_id,
        ingestion_run_id=run_id,
        raw_capture_id=raw_capture_id,
    )
    for row in package.rows:
        if row.issues:
            report.error_count += 1
            report.rows.append(
                ImportRowReport(
                    row_number=row.row_number,
                    record_key=row.record.record_key if row.record is not None else None,
                    status="error",
                    issues=list(row.issues),
                )
            )
            continue
        report.skipped_count += 1
        report.rows.append(
            ImportRowReport(
                row_number=row.row_number,
                record_key=row.record.record_key if row.record is not None else None,
                status="skipped",
            )
        )
    return report


def import_package(connection: Connection, package: ImportPackage) -> ImportReport:
    """Persist one validated package as raw and review-ready staged candidates.

    The caller owns the transaction. A dry-run uses this exact function and
    rolls its transaction back after serializing the resulting report.
    """

    source_id, source_created = _get_or_create_source(connection, package)
    input_fingerprint = build_input_fingerprint(
        source_url=package.metadata.source.canonical_url,
        content=package.fingerprint_bytes(),
        adapter_name=package.metadata.adapter.name,
        adapter_version=package.metadata.adapter.version,
    )
    run_id, run_created = get_or_create_ingestion_run(
        connection,
        source_id=source_id,
        input_fingerprint=input_fingerprint,
        adapter_name=package.metadata.adapter.name,
        adapter_version=package.metadata.adapter.version,
        received_at=package.metadata.capture.received_at,
    )
    if not run_created:
        existing_raw_capture_id = connection.scalar(
            select(RawCapture.id)
            .where(RawCapture.ingestion_run_id == run_id)
            .order_by(RawCapture.received_at)
            .limit(1)
        )
        report = _duplicate_package_report(
            package,
            source_id=source_id,
            run_id=run_id,
            raw_capture_id=existing_raw_capture_id,
        )
        return report.model_copy(
            update={
                "source_created": False,
            }
        )

    now = datetime.now(timezone.utc)
    _transition_ingestion_run(
        connection,
        run_id=run_id,
        status=IngestionRunStatus.PROCESSING,
        now=now,
    )
    raw_capture_id = uuid4()
    response_metadata = {
        **package.metadata.capture.response_metadata,
        "contract_version": package.metadata.contract_version,
        "input_row_count": len(package.rows),
    }
    connection.execute(
        insert(RawCapture).values(
            id=raw_capture_id,
            ingestion_run_id=run_id,
            content_sha256=sha256(package.raw_bytes).hexdigest(),
            source_url=package.metadata.capture.source_url,
            received_at=package.metadata.capture.received_at,
            content_format=package.metadata.capture.content_format,
            adapter_name=package.metadata.adapter.name,
            adapter_version=package.metadata.adapter.version,
            response_metadata=response_metadata,
            external_content_uri=package.metadata.capture.external_content_uri,
        )
    )

    report = ImportReport(
        source_id=source_id,
        source_created=source_created,
        ingestion_run_id=run_id,
        raw_capture_id=raw_capture_id,
    )
    for row in package.rows:
        if row.issues:
            staged_record_id = _create_error_staging_record(
                connection,
                package=package,
                raw_capture_id=raw_capture_id,
                row=row,
                now=now,
            )
            report.error_count += 1
            report.rows.append(
                ImportRowReport(
                    row_number=row.row_number,
                    record_key=row.record.record_key if row.record is not None else None,
                    status="error",
                    staged_record_id=staged_record_id,
                    issues=list(row.issues),
                )
            )
            continue

        if row.record is None:
            raise RuntimeError("import row has neither a record nor validation issues")
        previous_staged_record_id = _find_previous_staged_record(
            connection,
            source_id=source_id,
            record_key=row.record.record_key,
        )
        staged_record_id = _create_candidate_staging_record(
            connection,
            package=package,
            raw_capture_id=raw_capture_id,
            row=row,
            now=now,
        )
        if previous_staged_record_id is None:
            status: Literal["new", "updated"] = "new"
            report.new_count += 1
        else:
            status = "updated"
            report.updated_count += 1
        report.rows.append(
            ImportRowReport(
                row_number=row.row_number,
                record_key=row.record.record_key,
                status=status,
                staged_record_id=staged_record_id,
                previous_staged_record_id=previous_staged_record_id,
            )
        )

    _transition_ingestion_run(
        connection,
        run_id=run_id,
        status=IngestionRunStatus.COMPLETED,
        now=datetime.now(timezone.utc),
    )
    return report

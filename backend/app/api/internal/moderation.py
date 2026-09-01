from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import asc, desc, func, select
from sqlalchemy.engine import Connection

from app.api.internal.auth import InternalAccess, require_internal_access
from app.api.internal.schemas import (
    CanonicalReviewActionRequest,
    CanonicalReviewActionResponse,
    DiscoveryReviewActionRequest,
    DiscoveryReviewActionResponse,
    InternalDiscoveryReviewQueueItem,
    InternalError,
    InternalErrorResponse,
    InternalExecutionRun,
    InternalIngestionRun,
    InternalQualityIssue,
    InternalReviewAction,
    InternalReviewCaseDetail,
    InternalReviewQueueItem,
    InternalSource,
    ProgramRepublishRequest,
    ProgramRepublishResponse,
)
from app.domain.models import (
    DataQualityIssue,
    DataQualitySeverity,
    IngestionRun,
    RawCapture,
    ReviewAction,
    ReviewCase,
    ReviewCaseStatus,
    Source,
    SourceExecutionRun,
    StagedRecord,
)
from app.review.discovery import (
    DiscoveryReviewPolicyError,
    link_discovery_case_to_registered_source,
    list_discovery_review_queue,
    reject_discovery_case,
    request_discovery_clarification,
)
from app.review.operator import (
    IdempotencyKeyConflict,
    OperatorAuditLink,
    OperatorOperationOutcome,
    execute_idempotent_operator_operation,
    republish_program,
)
from app.review.service import (
    ReviewPolicyError,
    accept_review_case,
    merge_review_case,
    reject_review_case,
    request_clarification,
)
from app.sources.registry import RegistryValidationError, load_registry


class InternalApiError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = InternalErrorResponse(error=InternalError(code=code, message=message))


router = APIRouter(prefix="/api/internal/v1", tags=["internal"], include_in_schema=False)


def register_internal_api_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(InternalApiError, _handle_internal_api_error)
    application.add_exception_handler(IdempotencyKeyConflict, _handle_idempotency_key_conflict)
    application.add_exception_handler(ReviewPolicyError, _handle_review_policy_error)
    application.add_exception_handler(
        DiscoveryReviewPolicyError,
        _handle_discovery_review_policy_error,
    )


async def _handle_internal_api_error(_request: Request, exc: InternalApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.response.model_dump(mode="json"),
    )


async def _handle_idempotency_key_conflict(
    _request: Request,
    _exc: IdempotencyKeyConflict,
) -> JSONResponse:
    return _internal_error_response(
        status_code=status.HTTP_409_CONFLICT,
        code="idempotency_key_reused",
        message="Idempotency-Key is already associated with a different request.",
    )


async def _handle_review_policy_error(_request: Request, _exc: ReviewPolicyError) -> JSONResponse:
    return _internal_error_response(
        status_code=status.HTTP_409_CONFLICT,
        code="review_transition_not_allowed",
        message="The requested review transition is not allowed.",
    )


async def _handle_discovery_review_policy_error(
    _request: Request,
    _exc: DiscoveryReviewPolicyError,
) -> JSONResponse:
    return _internal_error_response(
        status_code=status.HTTP_409_CONFLICT,
        code="discovery_review_transition_not_allowed",
        message="The requested discovery review transition is not allowed.",
    )


def _internal_error_response(*, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=InternalErrorResponse(error=InternalError(code=code, message=message)).model_dump(
            mode="json"
        ),
    )


def get_internal_database_connection(
    request: Request,
    _access: InternalAccess = Depends(require_internal_access),
) -> Iterator[Connection]:
    with request.app.state.db_engine.begin() as connection:
        yield connection


def require_idempotency_key(
    value: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    if value is None or not value.strip():
        raise InternalApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="idempotency_key_required",
            message="Idempotency-Key is required for internal write operations.",
        )
    if len(value.strip()) > 255:
        raise InternalApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_idempotency_key",
            message="Idempotency-Key must be at most 255 characters.",
        )
    return value.strip()


def _reason_codes(opened_snapshot: object) -> list[str]:
    if not isinstance(opened_snapshot, Mapping):
        return []
    values = opened_snapshot.get("reason_codes", [])
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def _review_queue_item(row: Mapping[str, Any]) -> InternalReviewQueueItem:
    return InternalReviewQueueItem(
        review_case_id=row["id"],
        staged_record_id=row["staged_record_id"],
        status=row["status"],
        opened_at=row["opened_at"],
        reason_codes=_reason_codes(row["opened_snapshot"]),
    )


def _internal_quality_issue(row: Mapping[str, Any]) -> InternalQualityIssue:
    return InternalQualityIssue(
        id=row["id"],
        staged_record_id=row["staged_record_id"],
        record_key=row["record_key"],
        staged_state=row["staged_state"],
        source_id=row["source_id"],
        severity=row["severity"],
        code=row["code"],
        message=row["message"],
        created_at=row["created_at"],
        review_case_id=row.get("review_case_id"),
    )


@router.get("/sources", response_model=list[InternalSource])
def list_internal_sources(
    connection: Connection = Depends(get_internal_database_connection),
    _access: InternalAccess = Depends(require_internal_access),
    limit: int = Query(default=100, ge=1, le=1_000),
) -> list[InternalSource]:
    rows = connection.execute(
        select(Source.id, Source.name, Source.canonical_url, Source.created_at)
        .order_by(asc(Source.name), asc(Source.id))
        .limit(limit)
    ).mappings()
    return [InternalSource(**row) for row in rows]


@router.get("/runs", response_model=list[InternalExecutionRun])
def list_internal_execution_runs(
    connection: Connection = Depends(get_internal_database_connection),
    _access: InternalAccess = Depends(require_internal_access),
    source_key: str | None = Query(default=None, min_length=2, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[InternalExecutionRun]:
    statement = (
        select(
            SourceExecutionRun.id,
            SourceExecutionRun.source_id,
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
        )
        .order_by(desc(SourceExecutionRun.started_at), desc(SourceExecutionRun.id))
        .limit(limit)
    )
    if source_key is not None:
        statement = statement.where(SourceExecutionRun.source_key == source_key)
    rows = connection.execute(statement).mappings()
    return [
        InternalExecutionRun(
            **{
                **row,
                "error_codes": list(row["error_codes"]),
                "metrics": dict(row["metrics"]),
            },
        )
        for row in rows
    ]


@router.get("/ingestion-runs", response_model=list[InternalIngestionRun])
def list_internal_ingestion_runs(
    connection: Connection = Depends(get_internal_database_connection),
    _access: InternalAccess = Depends(require_internal_access),
    source_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[InternalIngestionRun]:
    raw_capture_count = (
        select(func.count(RawCapture.id))
        .where(RawCapture.ingestion_run_id == IngestionRun.id)
        .correlate(IngestionRun)
        .scalar_subquery()
    )
    staged_record_count = (
        select(func.count(StagedRecord.id))
        .select_from(StagedRecord)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .where(RawCapture.ingestion_run_id == IngestionRun.id)
        .correlate(IngestionRun)
        .scalar_subquery()
    )
    quality_issue_count = (
        select(func.count(DataQualityIssue.id))
        .select_from(DataQualityIssue)
        .join(StagedRecord, StagedRecord.id == DataQualityIssue.staged_record_id)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .where(RawCapture.ingestion_run_id == IngestionRun.id)
        .correlate(IngestionRun)
        .scalar_subquery()
    )
    quality_error_count = (
        select(func.count(DataQualityIssue.id))
        .select_from(DataQualityIssue)
        .join(StagedRecord, StagedRecord.id == DataQualityIssue.staged_record_id)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .where(
            RawCapture.ingestion_run_id == IngestionRun.id,
            DataQualityIssue.severity == DataQualitySeverity.ERROR,
        )
        .correlate(IngestionRun)
        .scalar_subquery()
    )
    statement = (
        select(
            IngestionRun.id,
            IngestionRun.source_id,
            IngestionRun.adapter_name,
            IngestionRun.adapter_version,
            IngestionRun.status,
            IngestionRun.received_at,
            IngestionRun.started_at,
            IngestionRun.finished_at,
            raw_capture_count.label("raw_capture_count"),
            staged_record_count.label("staged_record_count"),
            quality_issue_count.label("quality_issue_count"),
            quality_error_count.label("quality_error_count"),
            IngestionRun.run_statistics,
        )
        .order_by(desc(IngestionRun.received_at), desc(IngestionRun.id))
        .limit(limit)
    )
    if source_id is not None:
        statement = statement.where(IngestionRun.source_id == source_id)
    rows = connection.execute(statement).mappings()
    return [
        InternalIngestionRun(
            **{
                **row,
                "run_statistics": dict(row["run_statistics"]),
            }
        )
        for row in rows
    ]


@router.get("/quality/issues", response_model=list[InternalQualityIssue])
def list_internal_quality_issues(
    connection: Connection = Depends(get_internal_database_connection),
    _access: InternalAccess = Depends(require_internal_access),
    limit: int = Query(default=100, ge=1, le=1_000),
) -> list[InternalQualityIssue]:
    rows = connection.execute(
        select(
            DataQualityIssue.id,
            DataQualityIssue.staged_record_id,
            StagedRecord.record_key,
            StagedRecord.state.label("staged_state"),
            IngestionRun.source_id,
            DataQualityIssue.severity,
            DataQualityIssue.code,
            DataQualityIssue.message,
            DataQualityIssue.created_at,
            ReviewCase.id.label("review_case_id"),
        )
        .select_from(DataQualityIssue)
        .join(StagedRecord, StagedRecord.id == DataQualityIssue.staged_record_id)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
        .outerjoin(ReviewCase, ReviewCase.staged_record_id == StagedRecord.id)
        .order_by(desc(DataQualityIssue.created_at), desc(DataQualityIssue.id))
        .limit(limit)
    ).mappings()
    return [_internal_quality_issue(row) for row in rows]


@router.get("/review/cases", response_model=list[InternalReviewQueueItem])
def list_internal_review_cases(
    connection: Connection = Depends(get_internal_database_connection),
    _access: InternalAccess = Depends(require_internal_access),
    limit: int = Query(default=100, ge=1, le=1_000),
) -> list[InternalReviewQueueItem]:
    rows = connection.execute(
        select(
            ReviewCase.id,
            ReviewCase.staged_record_id,
            ReviewCase.status,
            ReviewCase.opened_at,
            ReviewCase.opened_snapshot,
        )
        .where(
            ReviewCase.status.in_(
                (ReviewCaseStatus.OPEN, ReviewCaseStatus.NEEDS_CLARIFICATION)
            )
        )
        .order_by(asc(ReviewCase.opened_at), asc(ReviewCase.id))
        .limit(limit)
    ).mappings()
    return [_review_queue_item(row) for row in rows]


@router.get("/review/cases/{review_case_id}", response_model=InternalReviewCaseDetail)
def get_internal_review_case(
    review_case_id: UUID,
    connection: Connection = Depends(get_internal_database_connection),
    _access: InternalAccess = Depends(require_internal_access),
) -> InternalReviewCaseDetail:
    row = connection.execute(
        select(
            ReviewCase.id,
            ReviewCase.staged_record_id,
            ReviewCase.status,
            ReviewCase.opened_at,
            ReviewCase.opened_snapshot,
        ).where(ReviewCase.id == review_case_id)
    ).mappings().one_or_none()
    if row is None:
        raise InternalApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="review_case_not_found",
            message="Review case was not found.",
        )

    issue_rows = connection.execute(
        select(
            DataQualityIssue.id,
            DataQualityIssue.staged_record_id,
            StagedRecord.record_key,
            StagedRecord.state.label("staged_state"),
            IngestionRun.source_id,
            DataQualityIssue.severity,
            DataQualityIssue.code,
            DataQualityIssue.message,
            DataQualityIssue.created_at,
            ReviewCase.id.label("review_case_id"),
        )
        .select_from(DataQualityIssue)
        .join(StagedRecord, StagedRecord.id == DataQualityIssue.staged_record_id)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
        .join(ReviewCase, ReviewCase.staged_record_id == StagedRecord.id)
        .where(ReviewCase.id == review_case_id)
        .order_by(asc(DataQualityIssue.created_at), asc(DataQualityIssue.id))
    ).mappings()
    action_rows = connection.execute(
        select(
            ReviewAction.id,
            ReviewAction.action,
            ReviewAction.reason,
            ReviewAction.actor,
            ReviewAction.deduplication_match_id,
            ReviewAction.target_staged_record_id,
            ReviewAction.target_program_id,
            ReviewAction.review_decision_id,
            ReviewAction.prior_values,
            ReviewAction.result_values,
            ReviewAction.created_at,
        )
        .where(ReviewAction.review_case_id == review_case_id)
        .order_by(asc(ReviewAction.created_at), asc(ReviewAction.id))
    ).mappings()
    item = _review_queue_item(row)
    snapshot = row["opened_snapshot"]
    return InternalReviewCaseDetail(
        **item.model_dump(),
        opened_snapshot=dict(snapshot) if isinstance(snapshot, Mapping) else {},
        quality_issues=[_internal_quality_issue(issue) for issue in issue_rows],
        actions=[
            InternalReviewAction(
                **{
                    **action,
                    "prior_values": dict(action["prior_values"]),
                    "result_values": dict(action["result_values"]),
                }
            )
            for action in action_rows
        ],
    )


@router.post("/review/cases/{review_case_id}/actions", response_model=CanonicalReviewActionResponse)
def apply_internal_review_action(
    review_case_id: UUID,
    payload: CanonicalReviewActionRequest,
    connection: Connection = Depends(get_internal_database_connection),
    access: InternalAccess = Depends(require_internal_access),
    idempotency_key: str = Depends(require_idempotency_key),
) -> CanonicalReviewActionResponse:
    request_payload = payload.model_dump(mode="json", exclude_none=False)

    def execute() -> OperatorOperationOutcome:
        if payload.action == "accept":
            action_result = accept_review_case(
                connection,
                review_case_id,
                reason=payload.reason,
                actor=access.actor,
            )
        elif payload.action == "reject":
            action_result = reject_review_case(
                connection,
                review_case_id,
                reason=payload.reason,
                actor=access.actor,
            )
        elif payload.action == "merge":
            if payload.deduplication_match_id is None:
                raise RuntimeError("merge request was validated without a match id")
            action_result = merge_review_case(
                connection,
                review_case_id,
                deduplication_match_id=payload.deduplication_match_id,
                reason=payload.reason,
                actor=access.actor,
            )
        else:
            action_result = request_clarification(
                connection,
                review_case_id,
                reason=payload.reason,
                actor=access.actor,
            )
        return OperatorOperationOutcome(
            result_payload={
                "review_case_id": str(action_result.review_case_id),
                "staged_record_id": str(action_result.staged_record_id),
                "review_action_id": str(action_result.review_action_id),
                "program_id": str(action_result.program_id) if action_result.program_id else None,
                "review_decision_id": (
                    str(action_result.review_decision_id)
                    if action_result.review_decision_id
                    else None
                ),
            },
            audit_link=OperatorAuditLink(review_action_id=action_result.review_action_id),
        )

    result = execute_idempotent_operator_operation(
        connection,
        actor=access.actor,
        idempotency_key=idempotency_key,
        action=payload.action,
        target_type="review_case",
        target_id=review_case_id,
        request_payload=request_payload,
        execute=execute,
    )
    values = result.result_payload
    return CanonicalReviewActionResponse(
        operation_id=result.operation_id,
        replayed=result.replayed,
        review_case_id=values["review_case_id"],
        staged_record_id=values["staged_record_id"],
        review_action_id=values["review_action_id"],
        program_id=values["program_id"],
        review_decision_id=values["review_decision_id"],
    )


@router.get("/discovery-review/cases", response_model=list[InternalDiscoveryReviewQueueItem])
def list_internal_discovery_review_cases(
    connection: Connection = Depends(get_internal_database_connection),
    _access: InternalAccess = Depends(require_internal_access),
    limit: int = Query(default=100, ge=1, le=1_000),
) -> list[InternalDiscoveryReviewQueueItem]:
    return [
        InternalDiscoveryReviewQueueItem(
            review_case_id=item.review_case_id,
            status=item.status,
            subject_type=item.subject_type,
            subject_reference=item.subject_reference,
            opened_at=item.opened_at,
            reason_codes=list(item.reason_codes),
        )
        for item in list_discovery_review_queue(connection, limit=limit)
    ]


@router.post(
    "/discovery-review/cases/{review_case_id}/actions",
    response_model=DiscoveryReviewActionResponse,
)
def apply_internal_discovery_review_action(
    review_case_id: UUID,
    payload: DiscoveryReviewActionRequest,
    request: Request,
    connection: Connection = Depends(get_internal_database_connection),
    access: InternalAccess = Depends(require_internal_access),
    idempotency_key: str = Depends(require_idempotency_key),
) -> DiscoveryReviewActionResponse:
    request_payload = payload.model_dump(mode="json", exclude_none=False)

    def execute() -> OperatorOperationOutcome:
        if payload.action == "link_to_registered_source":
            if payload.source_key is None:
                raise RuntimeError("link request was validated without a source key")
            try:
                registry = load_registry(request.app.state.settings.source_registry_path)
            except RegistryValidationError as error:
                raise InternalApiError(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    code="source_registry_unavailable",
                    message="The source registry is unavailable for discovery review.",
                ) from error
            action_result = link_discovery_case_to_registered_source(
                connection,
                review_case_id=review_case_id,
                registry=registry,
                source_key=payload.source_key,
                actor=access.actor,
                reason=payload.reason,
            )
        elif payload.action == "reject":
            action_result = reject_discovery_case(
                connection,
                review_case_id=review_case_id,
                actor=access.actor,
                reason=payload.reason,
            )
        else:
            action_result = request_discovery_clarification(
                connection,
                review_case_id=review_case_id,
                actor=access.actor,
                reason=payload.reason,
            )
        return OperatorOperationOutcome(
            result_payload={
                "review_case_id": str(action_result.review_case_id),
                "discovery_review_action_id": str(action_result.review_action_id),
                "status": action_result.status.value,
                "target_source_key": action_result.target_source_key,
            },
            audit_link=OperatorAuditLink(
                discovery_review_action_id=action_result.review_action_id
            ),
        )

    result = execute_idempotent_operator_operation(
        connection,
        actor=access.actor,
        idempotency_key=idempotency_key,
        action=payload.action,
        target_type="discovery_review_case",
        target_id=review_case_id,
        request_payload=request_payload,
        execute=execute,
    )
    values = result.result_payload
    return DiscoveryReviewActionResponse(
        operation_id=result.operation_id,
        replayed=result.replayed,
        review_case_id=values["review_case_id"],
        discovery_review_action_id=values["discovery_review_action_id"],
        status=values["status"],
        target_source_key=values["target_source_key"],
    )


@router.post("/programs/{program_id}/republish", response_model=ProgramRepublishResponse)
def apply_internal_republish(
    program_id: UUID,
    payload: ProgramRepublishRequest,
    connection: Connection = Depends(get_internal_database_connection),
    access: InternalAccess = Depends(require_internal_access),
    idempotency_key: str = Depends(require_idempotency_key),
) -> ProgramRepublishResponse:
    request_payload = payload.model_dump(mode="json")

    def execute() -> OperatorOperationOutcome:
        action_result = republish_program(
            connection,
            program_id,
            reason=payload.reason,
            actor=access.actor,
        )
        return OperatorOperationOutcome(
            result_payload={
                "program_id": str(action_result.program_id),
                "review_case_id": str(action_result.review_case_id),
                "review_decision_id": str(action_result.review_decision_id),
                "program_publication_action_id": str(action_result.publication_action_id),
                "published_at": action_result.published_at.isoformat(),
            },
            audit_link=OperatorAuditLink(
                program_publication_action_id=action_result.publication_action_id
            ),
        )

    result = execute_idempotent_operator_operation(
        connection,
        actor=access.actor,
        idempotency_key=idempotency_key,
        action="republish",
        target_type="program",
        target_id=program_id,
        request_payload=request_payload,
        execute=execute,
    )
    values = result.result_payload
    return ProgramRepublishResponse(
        operation_id=result.operation_id,
        replayed=result.replayed,
        program_id=values["program_id"],
        review_case_id=values["review_case_id"],
        review_decision_id=values["review_decision_id"],
        program_publication_action_id=values["program_publication_action_id"],
        published_at=values["published_at"],
    )

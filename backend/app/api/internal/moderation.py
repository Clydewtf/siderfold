from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import asc, desc, func, select
from sqlalchemy.engine import Connection

from app.analytics.baseline import BASELINE_METRICS_VERSION, compare_snapshot_counts
from app.analytics.network import NetworkAnalyticsError, calculate_network_metrics
from app.analytics.regional import REGIONAL_INDICATORS_VERSION
from app.analytics.snapshots import (
    INPUT_MANIFEST_VERSION,
    SUPPORTED_INPUT_MANIFEST_VERSIONS,
    AnalyticsSnapshotError,
    get_analytics_snapshot,
    list_analytics_snapshots,
)
from app.analytics.temporal import TemporalAnalyticsError, calculate_temporal_series
from app.api.internal.auth import InternalAccess, require_internal_access
from app.api.internal.schemas import (
    CanonicalReviewActionRequest,
    CanonicalReviewActionResponse,
    InternalAnalyticsBaselineResponse,
    InternalNetworkMetricsResponse,
    InternalRegionalIndicatorsResponse,
    InternalTemporalSeriesResponse,
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
    InternalReviewIssueResolution,
    InternalReviewMatchTarget,
    InternalReviewQueueItem,
    InternalReviewProvenance,
    InternalReviewRevision,
    InternalRegisteredSource,
    InternalSource,
    ProgramArchiveRequest,
    ProgramArchiveResponse,
    ProgramRepublishRequest,
    ProgramRepublishResponse,
    SaveReviewRevisionRequest,
    SaveReviewRevisionResponse,
)
from app.domain.models import (
    DataQualityIssue,
    DataQualitySeverity,
    DeduplicationMatch,
    IngestionRun,
    Program,
    ProgramDeadline,
    ProgramSource,
    RawCapture,
    ReviewAction,
    ReviewCase,
    ReviewCaseStatus,
    ReviewDecision,
    ReviewIssueResolution,
    ReviewRevision,
    Source,
    SourceExecutionRun,
    StagedRecord,
)
from app.domain.presentation import public_program_title
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
    archive_program,
    execute_idempotent_operator_operation,
    republish_program,
)
from app.review.service import (
    ReviewPolicyError,
    accept_review_case,
    merge_review_case,
    reject_review_case,
    review_effective_record,
    review_public_preview,
    request_clarification,
    save_review_revision,
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


@router.get(
    "/analytics/snapshots/{snapshot_id}/baseline",
    response_model=InternalAnalyticsBaselineResponse,
)
def get_internal_analytics_baseline(
    snapshot_id: UUID,
    compare_to: UUID | None = Query(default=None),
    connection: Connection = Depends(get_internal_database_connection),
) -> InternalAnalyticsBaselineResponse:
    snapshot = get_analytics_snapshot(connection, snapshot_id)
    if snapshot is None:
        raise InternalApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="analytics_snapshot_not_found",
            message="The requested analytics snapshot does not exist.",
        )
    baseline = snapshot.metrics.get("baseline")
    if (
        snapshot.input_manifest.get("version") not in SUPPORTED_INPUT_MANIFEST_VERSIONS
        or not isinstance(baseline, Mapping)
        or baseline.get("version") != BASELINE_METRICS_VERSION
    ):
        raise InternalApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="baseline_metrics_unavailable",
            message="This snapshot predates the baseline metrics calculation.",
        )

    comparison: dict[str, Any] | None = None
    if compare_to is not None:
        previous = get_analytics_snapshot(connection, compare_to)
        if previous is None:
            raise InternalApiError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="comparison_snapshot_not_found",
                message="The requested comparison snapshot does not exist.",
            )
        try:
            comparison = compare_snapshot_counts(snapshot, previous)
        except (KeyError, TypeError, AnalyticsSnapshotError) as error:
            raise InternalApiError(
                status_code=status.HTTP_409_CONFLICT,
                code="snapshot_comparison_invalid",
                message="The snapshots do not contain comparable baseline metrics.",
            ) from error

    return InternalAnalyticsBaselineResponse(
        snapshot_id=snapshot.id,
        scope=snapshot.scope,
        calculation_version=snapshot.calculation_version,
        as_of=snapshot.as_of,
        input_fingerprint=snapshot.input_fingerprint,
        data_class=str(snapshot.input_manifest.get("data_class", "unknown")),
        baseline=dict(baseline),
        comparison=comparison,
    )


@router.get(
    "/analytics/snapshots/{snapshot_id}/regional-indicators",
    response_model=InternalRegionalIndicatorsResponse,
)
def get_internal_regional_indicators(
    snapshot_id: UUID,
    connection: Connection = Depends(get_internal_database_connection),
) -> InternalRegionalIndicatorsResponse:
    snapshot = get_analytics_snapshot(connection, snapshot_id)
    if snapshot is None:
        raise InternalApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="analytics_snapshot_not_found",
            message="The requested analytics snapshot does not exist.",
        )
    indicators = snapshot.metrics.get("regional_indicators")
    if (
        snapshot.input_manifest.get("version") != INPUT_MANIFEST_VERSION
        or not isinstance(indicators, Mapping)
        or indicators.get("version") != REGIONAL_INDICATORS_VERSION
        or indicators.get("snapshot_id") != str(snapshot.id)
    ):
        raise InternalApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="regional_indicators_unavailable",
            message="This snapshot does not contain reproducible regional and thematic indicators.",
        )
    return InternalRegionalIndicatorsResponse(
        snapshot_id=snapshot.id,
        scope=snapshot.scope,
        calculation_version=snapshot.calculation_version,
        as_of=snapshot.as_of,
        input_fingerprint=snapshot.input_fingerprint,
        data_class=str(snapshot.input_manifest.get("data_class", "unknown")),
        regional_indicators=dict(indicators),
    )


@router.get(
    "/analytics/time-series",
    response_model=InternalTemporalSeriesResponse,
)
def get_internal_analytics_time_series(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    frequency: str = Query(default="weekly", pattern="^weekly$"),
    data_class: str = Query(default="real", pattern="^(real|test|synthetic|unknown)$"),
    connection: Connection = Depends(get_internal_database_connection),
) -> InternalTemporalSeriesResponse:
    if from_date > to_date:
        raise InternalApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_analytics_window",
            message="The from date must not be after the to date.",
        )
    as_of_before = datetime(
        to_date.year,
        to_date.month,
        to_date.day,
        tzinfo=timezone.utc,
    ) + timedelta(days=1)
    snapshots = list_analytics_snapshots(connection, as_of_before=as_of_before)
    try:
        series = calculate_temporal_series(
            snapshots,
            from_date=from_date,
            to_date=to_date,
            data_class=data_class,
            frequency=frequency,
        )
    except TemporalAnalyticsError as error:
        raise InternalApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_analytics_window",
            message=str(error),
        ) from error
    return InternalTemporalSeriesResponse(**series)


@router.get(
    "/analytics/snapshots/{snapshot_id}/network",
    response_model=InternalNetworkMetricsResponse,
)
def get_internal_analytics_network(
    snapshot_id: UUID,
    dimension: str | None = Query(
        default=None,
        pattern="^(program|theme|region|geography)$",
    ),
    connection: Connection = Depends(get_internal_database_connection),
) -> InternalNetworkMetricsResponse:
    snapshot = get_analytics_snapshot(connection, snapshot_id)
    if snapshot is None:
        raise InternalApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="analytics_snapshot_not_found",
            message="The requested analytics snapshot does not exist.",
        )
    try:
        network = calculate_network_metrics(snapshot)
    except NetworkAnalyticsError as error:
        raise InternalApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="network_metrics_unavailable",
            message=str(error),
        ) from error
    if dimension is not None:
        selected_dimension = "geography" if dimension == "region" else dimension
        network["dimensions"] = {
            selected_dimension: network["dimensions"][selected_dimension]
        }
    return InternalNetworkMetricsResponse(
        snapshot_id=snapshot.id,
        scope=snapshot.scope,
        calculation_version=snapshot.calculation_version,
        as_of=snapshot.as_of,
        input_fingerprint=snapshot.input_fingerprint,
        data_class=str(snapshot.input_manifest.get("data_class", "unknown")),
        network=network,
    )


def _reason_codes(opened_snapshot: object) -> list[str]:
    if not isinstance(opened_snapshot, Mapping):
        return []
    values = opened_snapshot.get("reason_codes", [])
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def _review_queue_item(row: Mapping[str, Any]) -> InternalReviewQueueItem:
    record = _candidate_record(row.get("candidate_payload"))
    source_url = _candidate_source_url(record)
    title = _candidate_title(record, source_url=source_url)
    return InternalReviewQueueItem(
        review_case_id=row["id"],
        staged_record_id=row["staged_record_id"],
        status=row["status"],
        opened_at=row["opened_at"],
        reason_codes=_reason_codes(row["opened_snapshot"]),
        title=title,
        source_url=source_url if isinstance(source_url, str) else None,
    )


def _candidate_record(candidate_payload: object) -> Mapping[str, Any]:
    candidate = candidate_payload if isinstance(candidate_payload, Mapping) else {}
    record = candidate.get("record")
    return record if isinstance(record, Mapping) else candidate


def _candidate_source_url(record: Mapping[str, Any]) -> str | None:
    value = record.get("record_url") or record.get("record_key")
    return value if isinstance(value, str) and value.strip() else None


def _candidate_title(record: Mapping[str, Any], *, source_url: str | None) -> str | None:
    raw_title = record.get("title")
    if not isinstance(raw_title, str) or not raw_title.strip():
        return None
    return public_program_title(raw_title, source_url=source_url)


def _candidate_deadline(record: Mapping[str, Any]) -> date | None:
    value = record.get("deadline_on")
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _internal_quality_issue(row: Mapping[str, Any]) -> InternalQualityIssue:
    resolution = None
    if row.get("resolution_id") is not None:
        resolution = InternalReviewIssueResolution(
            id=row["resolution_id"],
            review_revision_id=row["resolution_review_revision_id"],
            reason=row["resolution_reason"],
            actor=row["resolution_actor"],
            created_at=row["resolution_created_at"],
        )
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
        resolution=resolution,
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


@router.get("/source-definitions", response_model=list[InternalRegisteredSource])
def list_internal_registered_sources(
    request: Request,
    _access: InternalAccess = Depends(require_internal_access),
) -> list[InternalRegisteredSource]:
    """Expose source routing metadata without configuration secrets."""

    try:
        registry = load_registry(request.app.state.settings.source_registry_path)
    except RegistryValidationError as error:
        raise InternalApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="source_registry_unavailable",
            message="The source registry is unavailable.",
        ) from error

    return [
        InternalRegisteredSource(
            source_key=definition.source_key,
            name=definition.name,
            canonical_url=definition.canonical_url,
            allowed_url_prefixes=list(definition.allowed_url_prefixes),
            allowed_exact_urls=list(definition.allowed_exact_urls),
            access_method=definition.access_method.value,
            schedule=definition.schedule,
            status=definition.status.value,
            responsible=definition.responsible,
            adapter_name=definition.adapter_name,
            adapter_version=definition.adapter_version,
        )
        for definition in sorted(
            registry.sources.values(),
            key=lambda definition: definition.source_key,
        )
    ]


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
            ReviewIssueResolution.id.label("resolution_id"),
            ReviewIssueResolution.review_revision_id.label("resolution_review_revision_id"),
            ReviewIssueResolution.reason.label("resolution_reason"),
            ReviewIssueResolution.actor.label("resolution_actor"),
            ReviewIssueResolution.created_at.label("resolution_created_at"),
        )
        .select_from(DataQualityIssue)
        .join(StagedRecord, StagedRecord.id == DataQualityIssue.staged_record_id)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
        .outerjoin(ReviewCase, ReviewCase.staged_record_id == StagedRecord.id)
        .outerjoin(
            ReviewIssueResolution,
            ReviewIssueResolution.data_quality_issue_id == DataQualityIssue.id,
        )
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
            StagedRecord.candidate_payload,
        )
        .select_from(ReviewCase)
        .join(StagedRecord, StagedRecord.id == ReviewCase.staged_record_id)
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
            StagedRecord.candidate_payload,
            StagedRecord.raw_capture_id,
            RawCapture.ingestion_run_id,
            RawCapture.source_url.label("raw_capture_source_url"),
            RawCapture.received_at,
            RawCapture.content_sha256,
            RawCapture.content_format,
            RawCapture.adapter_name,
            RawCapture.adapter_version,
            IngestionRun.source_id,
            Source.name.label("source_name"),
            Source.canonical_url.label("source_canonical_url"),
        )
        .select_from(ReviewCase)
        .join(StagedRecord, StagedRecord.id == ReviewCase.staged_record_id)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
        .join(Source, Source.id == IngestionRun.source_id)
        .where(ReviewCase.id == review_case_id)
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
            ReviewIssueResolution.id.label("resolution_id"),
            ReviewIssueResolution.review_revision_id.label("resolution_review_revision_id"),
            ReviewIssueResolution.reason.label("resolution_reason"),
            ReviewIssueResolution.actor.label("resolution_actor"),
            ReviewIssueResolution.created_at.label("resolution_created_at"),
        )
        .select_from(DataQualityIssue)
        .join(StagedRecord, StagedRecord.id == DataQualityIssue.staged_record_id)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
        .join(ReviewCase, ReviewCase.staged_record_id == StagedRecord.id)
        .outerjoin(
            ReviewIssueResolution,
            ReviewIssueResolution.data_quality_issue_id == DataQualityIssue.id,
        )
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
    revision_rows = connection.execute(
        select(
            ReviewRevision.id,
            ReviewRevision.revision_number,
            ReviewRevision.changed_fields,
            ReviewRevision.deduplication_snapshot,
            ReviewRevision.reason,
            ReviewRevision.actor,
            ReviewRevision.created_at,
        )
        .where(ReviewRevision.review_case_id == review_case_id)
        .order_by(asc(ReviewRevision.revision_number), asc(ReviewRevision.id))
    ).mappings().all()
    resolution_rows = connection.execute(
        select(
            ReviewIssueResolution.review_revision_id,
            ReviewIssueResolution.data_quality_issue_id,
        )
        .join(ReviewRevision, ReviewRevision.id == ReviewIssueResolution.review_revision_id)
        .where(ReviewRevision.review_case_id == review_case_id)
        .order_by(
            asc(ReviewIssueResolution.created_at),
            asc(ReviewIssueResolution.data_quality_issue_id),
        )
    ).mappings()
    resolved_by_revision: dict[UUID, list[UUID]] = {}
    for resolution in resolution_rows:
        resolved_by_revision.setdefault(resolution["review_revision_id"], []).append(
            resolution["data_quality_issue_id"]
        )
    item = _review_queue_item(row)
    snapshot = row["opened_snapshot"]
    candidate_payload = row["candidate_payload"]
    candidate = candidate_payload if isinstance(candidate_payload, Mapping) else {}
    source_record = candidate.get("record") if isinstance(candidate.get("record"), Mapping) else candidate
    return InternalReviewCaseDetail(
        **item.model_dump(),
        opened_snapshot=dict(snapshot) if isinstance(snapshot, Mapping) else {},
        source_record=dict(source_record) if isinstance(source_record, Mapping) else {},
        effective_record=review_effective_record(connection, review_case_id),
        provenance=InternalReviewProvenance(
            source_id=row["source_id"],
            source_name=row["source_name"],
            source_canonical_url=row["source_canonical_url"],
            source_url=row["raw_capture_source_url"],
            raw_capture_id=row["raw_capture_id"],
            ingestion_run_id=row["ingestion_run_id"],
            received_at=row["received_at"],
            content_sha256=row["content_sha256"],
            content_format=row["content_format"],
            adapter_name=row["adapter_name"],
            adapter_version=row["adapter_version"],
        ),
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
        revisions=[
            InternalReviewRevision(
                id=revision["id"],
                revision_number=revision["revision_number"],
                changed_fields=list(revision["changed_fields"]),
                deduplication_snapshot=dict(revision["deduplication_snapshot"]),
                reason=revision["reason"],
                actor=revision["actor"],
                created_at=revision["created_at"],
                resolved_issue_ids=resolved_by_revision.get(revision["id"], []),
            )
            for revision in revision_rows
        ],
        public_preview=review_public_preview(connection, review_case_id),
    )


@router.get(
    "/review/matches/{deduplication_match_id}/target",
    response_model=InternalReviewMatchTarget,
)
def get_internal_review_match_target(
    deduplication_match_id: UUID,
    connection: Connection = Depends(get_internal_database_connection),
    _access: InternalAccess = Depends(require_internal_access),
) -> InternalReviewMatchTarget:
    """Return a safe, current summary of the target behind a match evidence row."""

    match = connection.execute(
        select(
            DeduplicationMatch.target_staged_record_id,
            DeduplicationMatch.target_program_id,
        ).where(DeduplicationMatch.id == deduplication_match_id)
    ).mappings().one_or_none()
    if match is None:
        raise InternalApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="deduplication_match_not_found",
            message="Deduplication match was not found.",
        )

    staged_record_id = match["target_staged_record_id"]
    if staged_record_id is not None:
        row = connection.execute(
            select(
                StagedRecord.id,
                StagedRecord.state,
                StagedRecord.candidate_payload,
                RawCapture.source_url.label("raw_capture_source_url"),
                Source.name.label("source_name"),
                ReviewCase.id.label("review_case_id"),
                ReviewCase.status.label("review_case_status"),
            )
            .select_from(StagedRecord)
            .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
            .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
            .join(Source, Source.id == IngestionRun.source_id)
            .outerjoin(ReviewCase, ReviewCase.staged_record_id == StagedRecord.id)
            .where(StagedRecord.id == staged_record_id)
        ).mappings().one_or_none()
        if row is None:
            raise InternalApiError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="deduplication_match_target_not_found",
                message="Deduplication match target was not found.",
            )
        record = _candidate_record(row["candidate_payload"])
        source_url = _candidate_source_url(record) or row["raw_capture_source_url"]
        return InternalReviewMatchTarget(
            kind="staged_record",
            id=row["id"],
            title=_candidate_title(record, source_url=source_url) or "Кандидат без названия",
            source_name=row["source_name"],
            source_url=source_url,
            deadline_on=_candidate_deadline(record),
            staged_state=row["state"],
            review_case_id=row["review_case_id"],
            review_case_status=row["review_case_status"],
        )

    program_id = match["target_program_id"]
    if program_id is None:
        raise InternalApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="deduplication_match_target_not_found",
            message="Deduplication match target was not found.",
        )
    row = connection.execute(
        select(
            Program.id,
            Program.title,
            Program.publication_status,
            ProgramSource.source_url,
            Source.name.label("source_name"),
            ProgramDeadline.deadline_on,
            ReviewCase.id.label("review_case_id"),
            ReviewCase.status.label("review_case_status"),
        )
        .select_from(Program)
        .join(
            ProgramSource,
            (ProgramSource.program_id == Program.id)
            & (ProgramSource.source_id == Program.primary_source_id),
        )
        .join(Source, Source.id == ProgramSource.source_id)
        .outerjoin(ProgramDeadline, ProgramDeadline.program_id == Program.id)
        .outerjoin(ReviewDecision, ReviewDecision.id == Program.publication_review_decision_id)
        .outerjoin(ReviewCase, ReviewCase.staged_record_id == ReviewDecision.staged_record_id)
        .where(Program.id == program_id)
    ).mappings().one_or_none()
    if row is None:
        raise InternalApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="deduplication_match_target_not_found",
            message="Deduplication match target was not found.",
        )
    return InternalReviewMatchTarget(
        kind="program",
        id=row["id"],
        title=public_program_title(row["title"], source_url=row["source_url"]),
        source_name=row["source_name"],
        source_url=row["source_url"],
        deadline_on=row["deadline_on"],
        review_case_id=row["review_case_id"],
        review_case_status=row["review_case_status"],
        publication_status=row["publication_status"],
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


@router.post(
    "/review/cases/{review_case_id}/revisions",
    response_model=SaveReviewRevisionResponse,
)
def save_internal_review_revision(
    review_case_id: UUID,
    payload: SaveReviewRevisionRequest,
    connection: Connection = Depends(get_internal_database_connection),
    access: InternalAccess = Depends(require_internal_access),
    idempotency_key: str = Depends(require_idempotency_key),
) -> SaveReviewRevisionResponse:
    request_payload = payload.model_dump(mode="json", exclude_none=False)

    def execute() -> OperatorOperationOutcome:
        revision = save_review_revision(
            connection,
            review_case_id,
            patch=payload.patch_values(),
            resolved_issue_ids=payload.resolve_issue_ids,
            reason=payload.reason,
            actor=access.actor,
        )
        return OperatorOperationOutcome(
            result_payload={
                "review_case_id": str(revision.review_case_id),
                "staged_record_id": str(revision.staged_record_id),
                "review_revision_id": str(revision.review_revision_id),
                "revision_number": revision.revision_number,
                "changed_fields": list(revision.changed_fields),
                "resolved_issue_ids": [str(value) for value in revision.resolved_issue_ids],
            },
            audit_link=OperatorAuditLink(review_revision_id=revision.review_revision_id),
        )

    result = execute_idempotent_operator_operation(
        connection,
        actor=access.actor,
        idempotency_key=idempotency_key,
        action="save_revision",
        target_type="review_case",
        target_id=review_case_id,
        request_payload=request_payload,
        execute=execute,
    )
    values = result.result_payload
    return SaveReviewRevisionResponse(
        operation_id=result.operation_id,
        replayed=result.replayed,
        review_case_id=values["review_case_id"],
        staged_record_id=values["staged_record_id"],
        review_revision_id=values["review_revision_id"],
        revision_number=values["revision_number"],
        changed_fields=values["changed_fields"],
        resolved_issue_ids=values["resolved_issue_ids"],
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


@router.post("/programs/{program_id}/archive", response_model=ProgramArchiveResponse)
def apply_internal_archive(
    program_id: UUID,
    payload: ProgramArchiveRequest,
    connection: Connection = Depends(get_internal_database_connection),
    access: InternalAccess = Depends(require_internal_access),
    idempotency_key: str = Depends(require_idempotency_key),
) -> ProgramArchiveResponse:
    request_payload = payload.model_dump(mode="json")

    def execute() -> OperatorOperationOutcome:
        action_result = archive_program(
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
                "archived_at": action_result.archived_at.isoformat(),
            },
            audit_link=OperatorAuditLink(
                program_publication_action_id=action_result.publication_action_id
            ),
        )

    result = execute_idempotent_operator_operation(
        connection,
        actor=access.actor,
        idempotency_key=idempotency_key,
        action="archive",
        target_type="program",
        target_id=program_id,
        request_payload=request_payload,
        execute=execute,
    )
    values = result.result_payload
    return ProgramArchiveResponse(
        operation_id=result.operation_id,
        replayed=result.replayed,
        program_id=values["program_id"],
        review_case_id=values["review_case_id"],
        review_decision_id=values["review_decision_id"],
        program_publication_action_id=values["program_publication_action_id"],
        archived_at=values["archived_at"],
    )

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterable
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection, Engine

from app.domain.ingestion import build_input_fingerprint, get_or_create_ingestion_run
from app.domain.models import (
    IngestionRun,
    IngestionRunStatus,
    RawCapture,
    Source,
    TelegramDiscoveryCursor,
    TelegramDiscoveryMessage,
    TelegramDiscoveryMessageObservation,
    TelegramDiscoveryMessageUrl,
    TelegramDiscoveryRoute,
    TelegramDiscoveryUrl,
    TelegramLinkRole,
)
from app.review.discovery import (
    ensure_discovery_review_case_for_message,
    ensure_discovery_review_case_for_url,
)
from app.sources.adapters.telegram.adapter import (
    TelegramDiscoveryAdapter,
    TelegramExtractedMessage,
)
from app.sources.contract import (
    AdapterContext,
    AdapterIssue,
    AdapterQualityMetrics,
    AdapterReport,
    AdapterRunSummary,
    AdapterStage,
    FreshnessMetric,
    QualityRatio,
    RunStatistics,
)
from app.sources.registry import (
    SourceDefinition,
    SourceRegistry,
    SourceRegistryStatus,
    is_url_allowed,
)


_CAPTURE_FORMAT = "application/vnd.siderfold.telegram-discovery+json"


@dataclass(frozen=True)
class RoutedTelegramLink:
    normalized_url: str
    link_role: TelegramLinkRole
    route: TelegramDiscoveryRoute
    target_source_key: str | None
    manual_review_reason: str | None


@dataclass(frozen=True)
class RoutedTelegramMessage:
    message_id: int
    message_url: str
    published_at: datetime
    service_label: str | None
    external_urls: tuple[RoutedTelegramLink, ...]
    review_required: bool
    issues: tuple[AdapterIssue, ...]


@dataclass(frozen=True)
class TelegramDiscoveryExecution:
    report: AdapterReport
    records: tuple[RoutedTelegramMessage, ...]
    snapshot_bytes: bytes
    received_at: datetime


@dataclass(frozen=True)
class TelegramPersistenceResult:
    source_id: UUID
    ingestion_run_id: UUID
    import_counts: dict[str, int]


def _ratio(numerator: int, denominator: int) -> QualityRatio:
    return QualityRatio(
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
    )


def _issue_payload(issue: AdapterIssue) -> dict[str, str]:
    return {
        "stage": issue.stage,
        "severity": issue.severity,
        "code": issue.code,
    }


def _message_payload(record: RoutedTelegramMessage) -> dict[str, object]:
    return {
        "message_id": record.message_id,
        "message_url": record.message_url,
        "published_at": record.published_at.isoformat(),
        "service_label": record.service_label,
        "external_urls": [
            {
                "url": link.normalized_url,
                "link_role": link.link_role.value,
                "route": link.route.value,
                "target_source_key": link.target_source_key,
                "manual_review_reason": link.manual_review_reason,
            }
            for link in record.external_urls
        ],
        "review_required": record.review_required,
        "issues": [_issue_payload(issue) for issue in record.issues],
    }


def _snapshot_bytes(records: Iterable[RoutedTelegramMessage]) -> bytes:
    payload = {
        "capture_policy": "minimal_metadata_and_external_urls_only",
        "messages": [
            _message_payload(record)
            for record in sorted(records, key=lambda item: item.message_id)
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _run_fingerprint_content(execution: TelegramDiscoveryExecution) -> bytes:
    """Keep empty polls as distinct audit events while retaining content idempotency."""

    if execution.records:
        return execution.snapshot_bytes
    return json.dumps(
        {
            "snapshot_sha256": sha256(execution.snapshot_bytes).hexdigest(),
            "poll_marker": str(uuid4()),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _route_url(
    url: str,
    *,
    registry: SourceRegistry,
    discovery_source_key: str,
) -> tuple[TelegramDiscoveryRoute, str | None, str | None, AdapterIssue | None]:
    matches = [
        definition
        for definition in registry.sources.values()
        if (
            definition.source_key != discovery_source_key
            and definition.status is SourceRegistryStatus.ACTIVE
            and definition.adapter_name != "telegram-discovery"
            and is_url_allowed(url, definition)
        )
    ]
    if len(matches) == 1:
        return (
            TelegramDiscoveryRoute.SOURCE_ADAPTER,
            matches[0].source_key,
            None,
            None,
        )
    if len(matches) > 1:
        return (
            TelegramDiscoveryRoute.MANUAL_REVIEW,
            None,
            "ambiguous_registered_sources",
            AdapterIssue(
                stage=AdapterStage.VALIDATE,
                severity="warning",
                code="ambiguous_source_route",
                message="An external URL matches more than one registered source allowlist.",
            ),
        )
    return (
        TelegramDiscoveryRoute.MANUAL_REVIEW,
        None,
        "no_registered_source",
        AdapterIssue(
            stage=AdapterStage.VALIDATE,
            severity="warning",
            code="unregistered_external_url",
            message="An external URL has no registered source adapter and needs manual review.",
        ),
    )


def _route_messages(
    records: Iterable[TelegramExtractedMessage],
    *,
    registry: SourceRegistry,
    definition: SourceDefinition,
    validation_issues: Iterable[AdapterIssue],
) -> tuple[tuple[RoutedTelegramMessage, ...], tuple[AdapterIssue, ...]]:
    validation_issue_values = tuple(validation_issues)
    issues_by_message: dict[int, list[AdapterIssue]] = defaultdict(list)
    for issue in validation_issue_values:
        if issue.resource_key is not None and issue.resource_key.isdigit():
            issues_by_message[int(issue.resource_key)].append(issue)

    routed_messages: list[RoutedTelegramMessage] = []
    route_issues: list[AdapterIssue] = []
    for record in records:
        message_issues = list(issues_by_message.get(record.message_id, ()))
        links: list[RoutedTelegramLink] = []
        for external_url in record.external_urls:
            route, target_source_key, reason, issue = _route_url(
                external_url.normalized_url,
                registry=registry,
                discovery_source_key=definition.source_key,
            )
            if issue is not None:
                issue = issue.model_copy(update={"resource_key": str(record.message_id)})
                message_issues.append(issue)
                route_issues.append(issue)
            links.append(
                RoutedTelegramLink(
                    normalized_url=external_url.normalized_url,
                    link_role=TelegramLinkRole(external_url.role),
                    route=route,
                    target_source_key=target_source_key,
                    manual_review_reason=reason,
                )
            )
        routed_messages.append(
            RoutedTelegramMessage(
                message_id=record.message_id,
                message_url=record.message_url,
                published_at=record.published_at,
                service_label=record.service_label,
                external_urls=tuple(links),
                review_required=(
                    not links
                    or any(
                        link.route is TelegramDiscoveryRoute.MANUAL_REVIEW
                        for link in links
                    )
                ),
                issues=tuple(message_issues),
            )
        )
    return tuple(routed_messages), tuple((*validation_issue_values, *route_issues))


def _quality_metrics(
    *,
    records: tuple[RoutedTelegramMessage, ...],
    discovered_message_count: int,
    duplicate_url_count: int,
    received_at: datetime,
    limitations: Iterable[str],
) -> AdapterQualityMetrics:
    record_count = len(records)
    messages_with_external_url = sum(bool(record.external_urls) for record in records)
    valid_messages = sum(
        not any(issue.severity == "error" for issue in record.issues)
        for record in records
    )
    external_url_occurrences = sum(len(record.external_urls) for record in records)
    timestamps = [record.published_at.isoformat() for record in records]
    return AdapterQualityMetrics(
        coverage_scope=(
            "new public messages from the configured Telegram channel after the stored cursor"
        ),
        completeness=_ratio(messages_with_external_url, record_count),
        validity=_ratio(valid_messages, record_count),
        duplicate_rate=_ratio(duplicate_url_count, external_url_occurrences),
        freshness=FreshnessMetric(
            numerator=len(timestamps),
            denominator=record_count,
            value=len(timestamps) / record_count if record_count else None,
            newest_source_last_modified_at=max(timestamps) if timestamps else None,
            captured_at=received_at,
        ),
        limitations=tuple(
            dict.fromkeys(
                (
                    *limitations,
                    "Completeness measures external URL presence, not completeness of Telegram history.",
                    "No message body or media is retained.",
                )
            )
        ),
    )


def _failed_execution(
    definition: SourceDefinition,
    adapter: TelegramDiscoveryAdapter,
    *,
    dry_run: bool,
    received_at: datetime,
    issue: AdapterIssue,
) -> TelegramDiscoveryExecution:
    report = AdapterReport(
        source_key=definition.source_key,
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        status="failed",
        dry_run=dry_run,
        statistics=RunStatistics(errors=1),
        issues=(issue,),
    )
    return TelegramDiscoveryExecution(
        report=report,
        records=(),
        snapshot_bytes=b"",
        received_at=received_at,
    )


def execute_telegram_discovery(
    definition: SourceDefinition,
    registry: SourceRegistry,
    adapter: TelegramDiscoveryAdapter,
    *,
    dry_run: bool,
    project_root: Path,
    cursor_message_id: int | None = None,
    started_at: datetime | None = None,
) -> TelegramDiscoveryExecution:
    """Run the bounded discovery stages without persisting a canonical program."""

    received_at = started_at or datetime.now(timezone.utc)
    context = AdapterContext(
        source=definition,
        dry_run=dry_run,
        project_root=project_root,
        started_at=received_at,
    )
    try:
        discovery = adapter.discover(context)
    except Exception as error:
        return _failed_execution(
            definition,
            adapter,
            dry_run=dry_run,
            received_at=received_at,
            issue=AdapterIssue(
                stage=AdapterStage.DISCOVER,
                severity="error",
                code="discover_error",
                message=str(error),
            ),
        )

    try:
        fetched = adapter.fetch(
            discovery.resources,
            context,
            cursor_message_id=cursor_message_id,
        )
    except Exception as error:
        return _failed_execution(
            definition,
            adapter,
            dry_run=dry_run,
            received_at=received_at,
            issue=AdapterIssue(
                stage=AdapterStage.FETCH,
                severity="error",
                code="fetch_error",
                message=str(error),
            ),
        )

    try:
        extracted = adapter.extract(
            fetched,
            context,
            cursor_message_id=cursor_message_id,
        )
        validation = adapter.validate(extracted.records, context)
    except Exception as error:
        return _failed_execution(
            definition,
            adapter,
            dry_run=dry_run,
            received_at=received_at,
            issue=AdapterIssue(
                stage=AdapterStage.EXTRACT,
                severity="error",
                code="extract_error",
                message=str(error),
            ),
        )

    routed_records, routing_issues = _route_messages(
        validation.records,
        registry=registry,
        definition=definition,
        validation_issues=validation.issues,
    )
    report_issues = tuple(
        (*discovery.issues, *fetched.issues, *extracted.issues, *routing_issues)
    )
    failed = any(issue.severity == "error" for issue in report_issues)
    duplicate_messages = sum(
        issue.code == "duplicate_message_in_run" for issue in report_issues
    )
    statistics = RunStatistics(
        discovered=extracted.discovered_message_count,
        fetched=len(fetched.pages),
        extracted=len(routed_records),
        valid=sum(
            not any(issue.severity == "error" for issue in record.issues)
            for record in routed_records
        ),
        warnings=sum(issue.severity == "warning" for issue in report_issues),
        errors=sum(issue.severity == "error" for issue in report_issues),
        duplicates=validation.duplicate_url_count + duplicate_messages,
        requests=fetched.request_count,
        response_bytes=fetched.response_bytes,
    )
    summary = AdapterRunSummary(
        source_key=definition.source_key,
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        status="failed" if failed else "completed",
        dry_run=dry_run,
        statistics=statistics,
        issues=report_issues,
        quality=_quality_metrics(
            records=routed_records,
            discovered_message_count=extracted.discovered_message_count,
            duplicate_url_count=validation.duplicate_url_count,
            received_at=received_at,
            limitations=(*discovery.quality_limitations, *fetched.limitations),
        ),
    )
    return TelegramDiscoveryExecution(
        report=adapter.report(summary),
        records=routed_records,
        snapshot_bytes=_snapshot_bytes(routed_records),
        received_at=received_at,
    )


def _upsert_source(connection: Connection, definition: SourceDefinition) -> UUID:
    source_id = uuid4()
    statement = (
        postgresql_insert(Source)
        .values(
            id=source_id,
            name=definition.name,
            canonical_url=definition.canonical_url,
        )
        .on_conflict_do_nothing(index_elements=("canonical_url",))
        .returning(Source.id)
    )
    persisted_source_id = connection.scalar(statement)
    if persisted_source_id is not None:
        return persisted_source_id
    existing_source_id = connection.scalar(
        select(Source.id).where(Source.canonical_url == definition.canonical_url)
    )
    if existing_source_id is None:
        raise RuntimeError("source was not persisted after a canonical URL conflict")
    return existing_source_id


def _persist_failed_run(
    engine: Engine,
    definition: SourceDefinition,
    adapter: TelegramDiscoveryAdapter,
    report: AdapterReport,
    *,
    received_at: datetime,
) -> tuple[UUID, UUID]:
    failure_material = json.dumps(
        {
            "source_key": definition.source_key,
            "received_at": received_at.isoformat(),
            "nonce": str(uuid4()),
        },
        sort_keys=True,
    ).encode("utf-8")
    with engine.begin() as connection:
        source_id = _upsert_source(connection, definition)
        run_id, created = get_or_create_ingestion_run(
            connection,
            source_id=source_id,
            input_fingerprint=build_input_fingerprint(
                source_url=definition.canonical_url,
                content=failure_material,
                adapter_name=adapter.name,
                adapter_version=adapter.version,
            ),
            adapter_name=adapter.name,
            adapter_version=adapter.version,
            received_at=received_at,
        )
        if not created:
            raise RuntimeError("failed Telegram discovery run unexpectedly reused a run")
        connection.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(status=IngestionRunStatus.PROCESSING, started_at=received_at)
        )
        connection.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(
                status=IngestionRunStatus.FAILED,
                finished_at=datetime.now(timezone.utc),
                run_statistics={
                    **report.statistics.model_dump(mode="json"),
                    "issues": [issue.model_dump(mode="json") for issue in report.issues],
                },
            )
        )
    return source_id, run_id


def _content_sha256(record: RoutedTelegramMessage) -> str:
    payload = _message_payload(record)
    payload["external_urls"] = [
        {
            "url": link.normalized_url,
            "link_role": link.link_role.value,
        }
        for link in record.external_urls
    ]
    payload.pop("issues", None)
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _get_existing_message_ids(
    connection: Connection,
    *,
    source_id: UUID,
    message_ids: tuple[int, ...],
) -> dict[int, UUID]:
    if not message_ids:
        return {}
    return {
        row.message_id: row.id
        for row in connection.execute(
            select(TelegramDiscoveryMessage.message_id, TelegramDiscoveryMessage.id).where(
                TelegramDiscoveryMessage.source_id == source_id,
                TelegramDiscoveryMessage.message_id.in_(message_ids),
            )
        )
    }


def _record_message_observation(
    connection: Connection,
    *,
    telegram_discovery_message_id: UUID,
    ingestion_run_id: UUID,
    raw_capture_id: UUID,
    record: RoutedTelegramMessage,
    observed_at: datetime,
    expires_at: datetime,
    content_sha256: str,
) -> None:
    connection.execute(
        postgresql_insert(TelegramDiscoveryMessageObservation)
        .values(
            id=uuid4(),
            telegram_discovery_message_id=telegram_discovery_message_id,
            ingestion_run_id=ingestion_run_id,
            raw_capture_id=raw_capture_id,
            observed_at=observed_at,
            message_url=record.message_url,
            published_at=record.published_at,
            service_label=record.service_label,
            content_sha256=content_sha256,
            review_required=record.review_required,
            discovery_issues=[_issue_payload(issue) for issue in record.issues],
            expires_at=expires_at,
        )
        .on_conflict_do_nothing(
            index_elements=(
                "telegram_discovery_message_id",
                "ingestion_run_id",
            )
        )
    )


def _get_or_create_url(
    connection: Connection,
    *,
    link: RoutedTelegramLink,
    observed_at: datetime,
    expires_at: datetime,
) -> tuple[UUID, bool]:
    existing_url_id = connection.scalar(
        select(TelegramDiscoveryUrl.id).where(
            TelegramDiscoveryUrl.normalized_url == link.normalized_url
        )
    )
    if existing_url_id is None:
        discovery_url_id = uuid4()
        connection.execute(
            postgresql_insert(TelegramDiscoveryUrl).values(
                id=discovery_url_id,
                normalized_url=link.normalized_url,
                route=link.route,
                target_source_key=link.target_source_key,
                manual_review_reason=link.manual_review_reason,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                expires_at=expires_at,
                seen_count=1,
            )
        )
        return discovery_url_id, True

    connection.execute(
        update(TelegramDiscoveryUrl)
        .where(TelegramDiscoveryUrl.id == existing_url_id)
        .values(
            route=link.route,
            target_source_key=link.target_source_key,
            manual_review_reason=link.manual_review_reason,
            last_seen_at=observed_at,
            expires_at=expires_at,
            seen_count=TelegramDiscoveryUrl.seen_count + 1,
        )
    )
    return existing_url_id, False


def _persist_execution(
    engine: Engine,
    definition: SourceDefinition,
    execution: TelegramDiscoveryExecution,
) -> TelegramPersistenceResult:
    channel = definition.telegram_channel
    if channel is None:
        raise ValueError("telegram-discovery requires telegram_channel configuration")
    observed_at = execution.received_at
    expires_at = observed_at + timedelta(days=channel.retention_days)
    input_fingerprint = build_input_fingerprint(
        source_url=definition.canonical_url,
        content=_run_fingerprint_content(execution),
        adapter_name=execution.report.adapter_name,
        adapter_version=execution.report.adapter_version,
    )

    with engine.begin() as connection:
        source_id = _upsert_source(connection, definition)
        run_id, created = get_or_create_ingestion_run(
            connection,
            source_id=source_id,
            input_fingerprint=input_fingerprint,
            adapter_name=execution.report.adapter_name,
            adapter_version=execution.report.adapter_version,
            received_at=observed_at,
        )
        if not created:
            return TelegramPersistenceResult(
                source_id=source_id,
                ingestion_run_id=run_id,
                import_counts={
                    "new": 0,
                    "updated": 0,
                    "skipped": len(execution.records),
                    "errors": 0,
                    "routed_to_source": 0,
                    "manual_review": 0,
                },
            )

        connection.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(status=IngestionRunStatus.PROCESSING, started_at=observed_at)
        )
        raw_capture_id = uuid4()
        connection.execute(
            postgresql_insert(RawCapture).values(
                id=raw_capture_id,
                ingestion_run_id=run_id,
                content_sha256=sha256(execution.snapshot_bytes).hexdigest(),
                source_url=channel.public_read_url,
                received_at=observed_at,
                content_format=_CAPTURE_FORMAT,
                adapter_name=execution.report.adapter_name,
                adapter_version=execution.report.adapter_version,
                response_metadata={
                    "capture_policy": "minimal_metadata_and_external_urls_only",
                    "channel_handle": channel.channel_handle,
                    "page_count": execution.report.statistics.fetched,
                    "retention_days": channel.retention_days,
                    "expires_at": expires_at.isoformat(),
                },
                external_content_uri=channel.public_read_url,
            )
        )

        existing_messages = _get_existing_message_ids(
            connection,
            source_id=source_id,
            message_ids=tuple(record.message_id for record in execution.records),
        )
        new_count = 0
        updated_count = 0
        routed_to_source = 0
        manual_review = 0
        for record in execution.records:
            existing_message_id = existing_messages.get(record.message_id)
            content_sha256 = _content_sha256(record)
            if existing_message_id is None:
                message_row_id = uuid4()
                connection.execute(
                    postgresql_insert(TelegramDiscoveryMessage).values(
                        id=message_row_id,
                        source_id=source_id,
                        ingestion_run_id=run_id,
                        raw_capture_id=raw_capture_id,
                        message_id=record.message_id,
                        message_url=record.message_url,
                        published_at=record.published_at,
                        received_at=observed_at,
                        last_observed_at=observed_at,
                        service_label=record.service_label,
                        content_sha256=content_sha256,
                        review_required=record.review_required,
                        discovery_issues=[
                            _issue_payload(issue) for issue in record.issues
                        ],
                        expires_at=expires_at,
                    )
                )
                new_count += 1
            else:
                message_row_id = existing_message_id
                connection.execute(
                    update(TelegramDiscoveryMessage)
                    .where(TelegramDiscoveryMessage.id == message_row_id)
                    .values(
                        message_url=record.message_url,
                        published_at=record.published_at,
                        last_observed_at=observed_at,
                        service_label=record.service_label,
                        content_sha256=content_sha256,
                        review_required=record.review_required,
                        discovery_issues=[
                            _issue_payload(issue) for issue in record.issues
                        ],
                        expires_at=expires_at,
                    )
                )
                updated_count += 1

            _record_message_observation(
                connection,
                telegram_discovery_message_id=message_row_id,
                ingestion_run_id=run_id,
                raw_capture_id=raw_capture_id,
                record=record,
                observed_at=observed_at,
                expires_at=expires_at,
                content_sha256=content_sha256,
            )
            if record.review_required:
                manual_review += 1
            if record.review_required and not record.external_urls:
                ensure_discovery_review_case_for_message(
                    connection,
                    telegram_discovery_message_id=message_row_id,
                    message_id=record.message_id,
                    message_url=record.message_url,
                    reason_codes=tuple(
                        issue.code for issue in record.issues
                    )
                    or ("missing_reliable_external_url",),
                    opened_at=observed_at,
                )
            for link in record.external_urls:
                discovery_url_id, _is_new_url = _get_or_create_url(
                    connection,
                    link=link,
                    observed_at=observed_at,
                    expires_at=expires_at,
                )
                if link.route is TelegramDiscoveryRoute.SOURCE_ADAPTER:
                    routed_to_source += 1
                else:
                    ensure_discovery_review_case_for_url(
                        connection,
                        telegram_discovery_url_id=discovery_url_id,
                        normalized_url=link.normalized_url,
                        reason_code=(
                            link.manual_review_reason or "manual_review_required"
                        ),
                        opened_at=observed_at,
                    )
                connection.execute(
                    postgresql_insert(TelegramDiscoveryMessageUrl)
                    .values(
                        message_id=message_row_id,
                        discovery_url_id=discovery_url_id,
                        link_role=link.link_role,
                    )
                    .on_conflict_do_update(
                        index_elements=("message_id", "discovery_url_id"),
                        set_={"link_role": link.link_role},
                    )
                )

        if execution.records:
            max_message_id = max(record.message_id for record in execution.records)
            cursor_statement = postgresql_insert(TelegramDiscoveryCursor).values(
                source_id=source_id,
                last_message_id=max_message_id,
                updated_at=observed_at,
            )
            connection.execute(
                cursor_statement.on_conflict_do_update(
                    index_elements=("source_id",),
                    set_={
                        "last_message_id": func.greatest(
                            TelegramDiscoveryCursor.last_message_id,
                            max_message_id,
                        ),
                        "updated_at": observed_at,
                    },
                )
            )

        statistics = execution.report.statistics.model_dump(mode="json")
        statistics["issues"] = [
            issue.model_dump(mode="json") for issue in execution.report.issues
        ]
        statistics["routing"] = {
            "routed_to_source": routed_to_source,
            "manual_review": manual_review,
        }
        connection.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(
                status=IngestionRunStatus.COMPLETED,
                finished_at=datetime.now(timezone.utc),
                run_statistics=statistics,
            )
        )

    return TelegramPersistenceResult(
        source_id=source_id,
        ingestion_run_id=run_id,
        import_counts={
            "new": new_count,
            "updated": updated_count,
            "skipped": 0,
            "errors": 0,
            "routed_to_source": routed_to_source,
            "manual_review": manual_review,
        },
    )


def _cursor_for_source(engine: Engine, definition: SourceDefinition) -> int | None:
    with engine.connect() as connection:
        source_id = connection.scalar(
            select(Source.id).where(Source.canonical_url == definition.canonical_url)
        )
        if source_id is None:
            return None
        return connection.scalar(
            select(TelegramDiscoveryCursor.last_message_id).where(
                TelegramDiscoveryCursor.source_id == source_id
            )
        )


def run_telegram_discovery_source(
    definition: SourceDefinition,
    registry: SourceRegistry,
    adapter: TelegramDiscoveryAdapter,
    *,
    engine: Engine | None,
    dry_run: bool,
    project_root: Path,
    started_at: datetime | None = None,
) -> AdapterReport:
    cursor_message_id = None
    if not dry_run and engine is not None:
        cursor_message_id = _cursor_for_source(engine, definition)
    execution = execute_telegram_discovery(
        definition,
        registry,
        adapter,
        dry_run=dry_run,
        project_root=project_root,
        cursor_message_id=cursor_message_id,
        started_at=started_at,
    )
    if dry_run:
        return execution.report
    if engine is None:
        raise ValueError("engine is required for a non-dry-run source execution")
    if execution.report.status == "failed":
        source_id, run_id = _persist_failed_run(
            engine,
            definition,
            adapter,
            execution.report,
            received_at=execution.received_at,
        )
        return execution.report.model_copy(
            update={"source_id": source_id, "ingestion_run_id": run_id}
        )
    try:
        persisted = _persist_execution(engine, definition, execution)
    except Exception as error:
        failed_report = execution.report.model_copy(
            update={
                "status": "failed",
                "statistics": execution.report.statistics.model_copy(
                    update={"errors": execution.report.statistics.errors + 1}
                ),
                "issues": (
                    *execution.report.issues,
                    AdapterIssue(
                        stage=AdapterStage.RUN,
                        severity="error",
                        code="persist_error",
                        message=str(error),
                    ),
                ),
            }
        )
        source_id, run_id = _persist_failed_run(
            engine,
            definition,
            adapter,
            failed_report,
            received_at=execution.received_at,
        )
        return failed_report.model_copy(
            update={"source_id": source_id, "ingestion_run_id": run_id}
        )
    return execution.report.model_copy(
        update={
            "source_id": persisted.source_id,
            "ingestion_run_id": persisted.ingestion_run_id,
            "import_counts": persisted.import_counts,
        }
    )

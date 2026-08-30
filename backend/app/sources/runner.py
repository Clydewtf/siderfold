from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection, Engine

from app.domain.ingestion import build_input_fingerprint, get_or_create_ingestion_run
from app.domain.models import IngestionRun, IngestionRunStatus, Source
from app.import_bridge.contract import (
    CONTRACT_VERSION,
    ContractAdapter,
    ContractCapture,
    ContractSource,
    ImportPackage,
    PackageMetadata,
)
from app.import_bridge.service import ImportReport, import_package
from app.sources.contract import (
    ADAPTER_CONTRACT_VERSION,
    AdapterContext,
    AdapterIssue,
    AdapterReport,
    AdapterRunSummary,
    AdapterStage,
    DiscoveredResource,
    ExtractedRecord,
    FetchResult,
    RunStatistics,
    SourceAdapter,
    ValidationResult,
    validation_issue_to_adapter_issue,
)
from app.sources.fixture_adapter import fixture_adapter
from app.sources.registry import (
    DEFAULT_REGISTRY_PATH,
    SourceDefinition,
    SourceRegistry,
    SourceRegistryStatus,
    UrlAllowlistError,
    load_registry,
)


AdapterFactory = Callable[[], SourceAdapter]

ADAPTER_FACTORIES: dict[str, AdapterFactory] = {
    "fixture-catalog": fixture_adapter,
}


class AdapterExecutionError(ValueError):
    """Raised when an adapter cannot satisfy the configured execution contract."""


@dataclass(frozen=True)
class AdapterExecution:
    package: ImportPackage | None
    report: AdapterReport


def _project_root_for_registry(registry_path: Path) -> Path:
    resolved = registry_path.resolve()
    return resolved.parents[1] if len(resolved.parents) > 1 else resolved.parent


def resolve_adapter(definition: SourceDefinition) -> SourceAdapter:
    factory = ADAPTER_FACTORIES.get(definition.adapter_name)
    if factory is None:
        raise AdapterExecutionError(
            f"adapter is not registered: {definition.adapter_name}"
        )
    adapter = factory()
    if adapter.version != definition.adapter_version:
        raise AdapterExecutionError(
            f"adapter version mismatch for '{definition.source_key}': "
            f"registry requires {definition.adapter_version}, implementation is {adapter.version}"
        )
    return adapter


def _failure_report(
    definition: SourceDefinition,
    *,
    dry_run: bool,
    issue: AdapterIssue,
    source_id: UUID | None = None,
    ingestion_run_id: UUID | None = None,
) -> AdapterReport:
    return AdapterReport(
        source_key=definition.source_key,
        adapter_name=definition.adapter_name,
        adapter_version=definition.adapter_version,
        status="failed",
        dry_run=dry_run,
        statistics=RunStatistics(errors=1),
        issues=(issue,),
        source_id=source_id,
        ingestion_run_id=ingestion_run_id,
    )


def _row_issues(rows: Sequence) -> tuple[AdapterIssue, ...]:
    issues: list[AdapterIssue] = []
    for row in rows:
        for issue in row.issues:
            issues.append(validation_issue_to_adapter_issue(issue))
    return tuple(issues)


def _statistics(
    *,
    discovered: int,
    fetched: int,
    extracted: int,
    requests: int,
    response_bytes: int,
    validation: ValidationResult,
    pipeline_issues: Sequence[AdapterIssue],
) -> RunStatistics:
    valid = sum(1 for row in validation.rows if row.record is not None and not row.issues)
    record_warnings = sum(
        len(row.record.warnings)
        for row in validation.rows
        if row.record is not None
    )
    pipeline_warnings = sum(issue.severity == "warning" for issue in pipeline_issues)
    row_issues = [issue for row in validation.rows for issue in row.issues]
    duplicates = sum(issue.code == "duplicate_record_key" for issue in row_issues)
    errors = sum(issue.severity == "error" for issue in pipeline_issues)
    return RunStatistics(
        discovered=discovered,
        fetched=fetched,
        extracted=extracted,
        valid=valid,
        warnings=record_warnings + pipeline_warnings,
        errors=errors,
        duplicates=duplicates,
        requests=requests,
        response_bytes=response_bytes,
    )


def _build_import_package(
    definition: SourceDefinition,
    adapter: SourceAdapter,
    fetched: Sequence[FetchResult],
    validation: ValidationResult,
) -> ImportPackage:
    if not fetched:
        raise AdapterExecutionError("an import package requires at least one fetch result")

    first = fetched[0]
    if len(fetched) == 1:
        raw_bytes = first.content
        content_format = first.content_format
        external_content_uri = first.external_content_uri
    else:
        raw_bytes = b"\n".join(item.content for item in fetched)
        content_format = "application/octet-stream"
        external_content_uri = first.external_content_uri

    metadata = PackageMetadata(
        contract_version=CONTRACT_VERSION,
        source=ContractSource(
            name=definition.name,
            canonical_url=definition.canonical_url,
        ),
        capture=ContractCapture(
            source_url=first.final_url,
            received_at=first.received_at,
            external_content_uri=external_content_uri,
            content_format=content_format,
            response_metadata={
                "adapter_contract_version": ADAPTER_CONTRACT_VERSION,
                "fetch_count": len(fetched),
                "fetches": [
                    {
                        "source_url": item.final_url,
                        "external_content_uri": item.external_content_uri,
                        "response_metadata": dict(item.response_metadata),
                    }
                    for item in fetched
                ],
            },
        ),
        adapter=ContractAdapter(
            name=adapter.name,
            version=adapter.version,
        ),
    )
    return ImportPackage(
        metadata=metadata,
        raw_bytes=raw_bytes,
        rows=validation.rows,
    )


def execute_adapter(
    definition: SourceDefinition,
    adapter: SourceAdapter,
    *,
    dry_run: bool,
    project_root: Path,
    started_at: datetime | None = None,
) -> AdapterExecution:
    started = started_at or datetime.now(timezone.utc)
    context = AdapterContext(
        source=definition,
        dry_run=dry_run,
        project_root=project_root,
        started_at=started,
    )
    pipeline_issues: list[AdapterIssue] = []
    fetched_results: list[FetchResult] = []
    extracted_records: list[ExtractedRecord] = []
    request_count = 0
    response_bytes = 0

    try:
        discovery = adapter.discover(context)
    except Exception as error:
        pipeline_issues.append(
            AdapterIssue(
                stage=AdapterStage.DISCOVER,
                severity="error",
                code="discover_error",
                message=str(error),
            )
        )
        discovery_resources: tuple[DiscoveredResource, ...] = ()
        discovery_issues: tuple[AdapterIssue, ...] = ()
    else:
        discovery_resources = discovery.resources
        discovery_issues = discovery.issues
        pipeline_issues.extend(discovery_issues)

    if not discovery_resources and not any(
        issue.severity == "error" for issue in pipeline_issues
    ):
        pipeline_issues.append(
            AdapterIssue(
                stage=AdapterStage.DISCOVER,
                severity="error",
                code="empty_discovery",
                message="adapter did not discover any resources",
            )
        )

    for resource in discovery_resources:
        if request_count >= definition.limits.max_requests:
            pipeline_issues.append(
                AdapterIssue(
                    stage=AdapterStage.FETCH,
                    severity="error",
                    code="request_limit_exceeded",
                    message=(
                        f"max_requests limit ({definition.limits.max_requests}) "
                        "was exceeded"
                    ),
                    resource_key=resource.external_key,
                )
            )
            break

        request_count += 1
        try:
            context.require_allowed_url(resource.url)
            fetched = adapter.fetch(resource, context)
            context.require_allowed_url(fetched.final_url)
            response_size = len(fetched.content)
            if response_size > definition.limits.max_response_bytes:
                raise AdapterExecutionError(
                    "max_response_bytes limit "
                    f"({definition.limits.max_response_bytes}) was exceeded"
                )
            if response_bytes + response_size > definition.limits.max_total_bytes:
                raise AdapterExecutionError(
                    "max_total_bytes limit "
                    f"({definition.limits.max_total_bytes}) was exceeded"
                )
        except UrlAllowlistError as error:
            pipeline_issues.append(
                AdapterIssue(
                    stage=AdapterStage.FETCH,
                    severity="error",
                    code="url_not_allowed",
                    message=str(error),
                    resource_key=resource.external_key,
                )
            )
            continue
        except Exception as error:
            pipeline_issues.append(
                AdapterIssue(
                    stage=AdapterStage.FETCH,
                    severity="error",
                    code="fetch_error",
                    message=str(error),
                    resource_key=resource.external_key,
                )
            )
            continue

        fetched_results.append(fetched)
        response_bytes += len(fetched.content)
        try:
            extracted = adapter.extract(fetched, context)
        except Exception as error:
            pipeline_issues.append(
                AdapterIssue(
                    stage=AdapterStage.EXTRACT,
                    severity="error",
                    code="extract_error",
                    message=str(error),
                    resource_key=resource.external_key,
                )
            )
            continue
        pipeline_issues.extend(extracted.issues)
        extracted_records.extend(extracted.records)

    if len(extracted_records) > definition.limits.max_records:
        pipeline_issues.append(
            AdapterIssue(
                stage=AdapterStage.VALIDATE,
                severity="error",
                code="record_limit_exceeded",
                message=(
                    f"max_records limit ({definition.limits.max_records}) was exceeded"
                ),
            )
        )

    if fetched_results and not extracted_records and not any(
        issue.severity == "error" for issue in pipeline_issues
    ):
        pipeline_issues.append(
            AdapterIssue(
                stage=AdapterStage.EXTRACT,
                severity="error",
                code="empty_result",
                message="adapter did not extract any records",
            )
        )

    validation = ValidationResult()
    if extracted_records and not any(
        issue.stage == AdapterStage.EXTRACT and issue.severity == "error"
        for issue in pipeline_issues
    ):
        try:
            validation = adapter.validate(tuple(extracted_records), context)
        except Exception as error:
            pipeline_issues.append(
                AdapterIssue(
                    stage=AdapterStage.VALIDATE,
                    severity="error",
                    code="validate_error",
                    message=str(error),
                )
            )
        else:
            pipeline_issues.extend(validation.issues)

    row_issues = _row_issues(validation.rows)
    report_issues = (*pipeline_issues, *row_issues)
    statistics = _statistics(
        discovered=len(discovery_resources),
        fetched=len(fetched_results),
        extracted=len(extracted_records),
        requests=request_count,
        response_bytes=response_bytes,
        validation=validation,
        pipeline_issues=report_issues,
    )
    failed = any(issue.severity == "error" for issue in pipeline_issues)
    package = None
    if not failed and fetched_results:
        package = _build_import_package(
            definition,
            adapter,
            fetched_results,
            validation,
        )

    summary = AdapterRunSummary(
        source_key=definition.source_key,
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        status="failed" if failed else "completed",
        dry_run=dry_run,
        statistics=statistics,
        issues=report_issues,
    )
    report = adapter.report(summary)
    return AdapterExecution(package=package, report=report)


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
        raise RuntimeError("source was not persisted after canonical URL conflict")
    return existing_source_id


def _failed_run_fingerprint(
    definition: SourceDefinition,
    adapter_name: str,
    adapter_version: str,
    started_at: datetime,
) -> str:
    attempt = json.dumps(
        {
            "source_key": definition.source_key,
            "started_at": started_at.isoformat(),
            "nonce": str(uuid4()),
        },
        sort_keys=True,
    ).encode("utf-8")
    return build_input_fingerprint(
        source_url=definition.canonical_url,
        content=attempt,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
    )


def _persist_failed_run(
    engine: Engine,
    definition: SourceDefinition,
    adapter_name: str,
    adapter_version: str,
    report: AdapterReport,
    *,
    started_at: datetime,
) -> tuple[UUID, UUID]:
    with engine.begin() as connection:
        source_id = _upsert_source(connection, definition)
        run_id, created = get_or_create_ingestion_run(
            connection,
            source_id=source_id,
            input_fingerprint=_failed_run_fingerprint(
                definition,
                adapter_name,
                adapter_version,
                started_at,
            ),
            adapter_name=adapter_name,
            adapter_version=adapter_version,
            received_at=started_at,
        )
        if not created:
            raise RuntimeError("failed adapter run unexpectedly reused an existing run")
        connection.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(
                status=IngestionRunStatus.PROCESSING,
                started_at=started_at,
            )
        )
        connection.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(
                status=IngestionRunStatus.FAILED,
                finished_at=datetime.now(timezone.utc),
                run_statistics={
                    **report.statistics.model_dump(mode="json"),
                    "issues": [
                        issue.model_dump(mode="json") for issue in report.issues
                    ],
                },
            )
        )
    return source_id, run_id


def _persist_successful_run(
    engine: Engine,
    package: ImportPackage,
    report: AdapterReport,
) -> tuple[ImportReport, dict[str, int]]:
    with engine.begin() as connection:
        import_result = import_package(connection, package)
        import_counts = {
            "new": import_result.new_count,
            "updated": import_result.updated_count,
            "skipped": import_result.skipped_count,
            "errors": import_result.error_count,
        }
        statistics = report.statistics.model_dump(mode="json")
        statistics["import"] = import_counts
        statistics["issues"] = [
            issue.model_dump(mode="json") for issue in report.issues
        ]
        if import_result.ingestion_run_id is None:
            raise RuntimeError("import did not return an ingestion run id")
        connection.execute(
            update(IngestionRun)
            .where(IngestionRun.id == import_result.ingestion_run_id)
            .values(run_statistics=statistics)
        )
    return import_result, import_counts


def run_registered_source(
    source_key: str,
    *,
    registry_path: Path | None = None,
    engine: Engine | None = None,
    dry_run: bool = False,
    project_root: Path | None = None,
) -> AdapterReport:
    resolved_registry_path = registry_path or DEFAULT_REGISTRY_PATH
    registry = load_registry(resolved_registry_path)
    definition = registry.get(source_key)
    root = (project_root or _project_root_for_registry(resolved_registry_path)).resolve()
    started_at = datetime.now(timezone.utc)

    if definition.status is not SourceRegistryStatus.ACTIVE:
        return _failure_report(
            definition,
            dry_run=dry_run,
            issue=AdapterIssue(
                stage=AdapterStage.RUN,
                severity="error",
                code="source_not_active",
                message=f"source status is '{definition.status.value}'",
            ),
        )

    try:
        adapter = resolve_adapter(definition)
        execution = execute_adapter(
            definition,
            adapter,
            dry_run=dry_run,
            project_root=root,
            started_at=started_at,
        )
    except Exception as error:
        report = _failure_report(
            definition,
            dry_run=dry_run,
            issue=AdapterIssue(
                stage=AdapterStage.RUN,
                severity="error",
                code="adapter_setup_error",
                message=str(error),
            ),
        )
        if dry_run or engine is None:
            return report
        source_id, run_id = _persist_failed_run(
            engine,
            definition,
            definition.adapter_name,
            definition.adapter_version,
            report,
            started_at=started_at,
        )
        return report.model_copy(update={"source_id": source_id, "ingestion_run_id": run_id})

    if dry_run:
        return execution.report

    if engine is None:
        raise ValueError("engine is required for a non-dry-run source execution")

    if execution.package is None:
        source_id, run_id = _persist_failed_run(
            engine,
            definition,
            adapter.name,
            adapter.version,
            execution.report,
            started_at=started_at,
        )
        return execution.report.model_copy(
            update={"source_id": source_id, "ingestion_run_id": run_id}
        )

    try:
        import_result, import_counts = _persist_successful_run(
            engine,
            execution.package,
            execution.report,
        )
    except Exception as error:
        report = execution.report.model_copy(
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
            adapter.name,
            adapter.version,
            report,
            started_at=started_at,
        )
        return report.model_copy(update={"source_id": source_id, "ingestion_run_id": run_id})

    return execution.report.model_copy(
        update={
            "source_id": import_result.source_id,
            "ingestion_run_id": import_result.ingestion_run_id,
            "import_counts": import_counts,
        }
    )


def list_registered_sources(registry: SourceRegistry) -> list[dict[str, object]]:
    return [
        {
            "source_key": definition.source_key,
            "name": definition.name,
            "canonical_url": definition.canonical_url,
            "allowed_url_prefixes": list(definition.allowed_url_prefixes),
            "access_method": definition.access_method.value,
            "schedule": definition.schedule,
            "status": definition.status.value,
            "responsible": definition.responsible,
            "adapter_name": definition.adapter_name,
            "adapter_version": definition.adapter_version,
            "limits": definition.limits.model_dump(mode="json"),
        }
        for definition in registry.sources.values()
    ]

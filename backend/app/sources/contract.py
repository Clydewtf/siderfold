from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from math import ceil
from pathlib import Path
from time import monotonic
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.import_bridge.contract import (
    ParsedRow,
    ValidationIssue,
    add_duplicate_key_issues,
    parse_record,
)
from app.sources.registry import SourceDefinition, SourceLimits, require_allowed_url


ADAPTER_CONTRACT_VERSION = "siderfold.adapter/v1"
ADAPTER_REPORT_VERSION = "siderfold.adapter-report/v1"


class AdapterStage(str):
    DISCOVER = "discover"
    FETCH = "fetch"
    EXTRACT = "extract"
    VALIDATE = "validate"
    REPORT = "report"
    RUN = "run"


class AdapterRunTimeoutError(RuntimeError):
    """Raised when an adapter exhausts its configured total runtime budget."""


class AdapterIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    severity: Literal["warning", "error"]
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2_000)
    resource_key: str | None = Field(default=None, max_length=512)
    row_number: int | None = Field(default=None, ge=1)
    field: str | None = Field(default=None, max_length=255)


class AdapterContext:
    """Runtime context shared by all adapter stages."""

    def __init__(
        self,
        *,
        source: SourceDefinition,
        dry_run: bool,
        project_root: Path,
        started_at: datetime,
        run_id: UUID | None = None,
        raw_capture_dir: Path | None = None,
        progress_reporter: Callable[[str], None] | None = None,
    ) -> None:
        self.source = source
        self.dry_run = dry_run
        self.project_root = project_root
        self.started_at = started_at
        self.run_id = run_id
        self.raw_capture_dir = raw_capture_dir
        self._progress_reporter = progress_reporter
        self._started_monotonic = monotonic()

    @property
    def limits(self) -> SourceLimits:
        return self.source.limits

    def require_allowed_url(self, url: str) -> str:
        return require_allowed_url(url, self.source)

    @property
    def remaining_run_seconds(self) -> float:
        elapsed_seconds = monotonic() - self._started_monotonic
        return max(0.0, self.limits.max_run_seconds - elapsed_seconds)

    def require_time_remaining(self) -> float:
        remaining_seconds = self.remaining_run_seconds
        if remaining_seconds <= 0:
            raise AdapterRunTimeoutError(
                f"source run exceeded max_run_seconds ({self.limits.max_run_seconds})"
            )
        return remaining_seconds

    def request_timeout_seconds(self) -> int:
        return min(self.limits.timeout_seconds, max(1, ceil(self.require_time_remaining())))

    def report_progress(self, message: str) -> None:
        if self._progress_reporter is None:
            return
        normalized = " ".join(message.split())
        if normalized:
            self._progress_reporter(normalized)


class DiscoveredResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_key: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=2_048)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        from app.sources.registry import normalize_url

        return normalize_url(value)


@dataclass(frozen=True)
class FetchResult:
    resource: DiscoveredResource
    final_url: str
    content: bytes
    content_format: str
    received_at: datetime
    external_content_uri: str
    response_metadata: Mapping[str, Any] = field(default_factory=dict)


class DiscoveryResult(BaseModel):
    """URLs discovered from a source plus immutable discovery captures.

    Some official sources publish their catalog as a bounded sitemap. Keeping
    that sitemap capture alongside the detail URLs preserves the discovery
    evidence and makes its request visible in run statistics.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    resources: tuple[DiscoveredResource, ...] = ()
    captures: tuple[FetchResult, ...] = ()
    record_resources: tuple[DiscoveredResource, ...] = ()
    issues: tuple[AdapterIssue, ...] = ()
    request_count: int = Field(default=0, ge=0)
    response_bytes: int = Field(default=0, ge=0)
    artifact_discovered: int = Field(default=0, ge=0)
    artifact_fetched: int = Field(default=0, ge=0)
    artifact_deferred: int = Field(default=0, ge=0)
    coverage_scope: str = Field(
        default="resources returned by discovery",
        min_length=1,
        max_length=500,
    )
    quality_limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractedRecord:
    row_number: int
    raw_payload: Mapping[str, Any]
    capture_key: str | None = None


@dataclass(frozen=True)
class ExtractResult:
    records: tuple[ExtractedRecord, ...] = ()
    issues: tuple[AdapterIssue, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    rows: tuple[ParsedRow, ...] = ()
    issues: tuple[AdapterIssue, ...] = ()


class RunStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discovered: int = Field(default=0, ge=0)
    fetched: int = Field(default=0, ge=0)
    extracted: int = Field(default=0, ge=0)
    valid: int = Field(default=0, ge=0)
    warnings: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    duplicates: int = Field(default=0, ge=0)
    requests: int = Field(default=0, ge=0)
    response_bytes: int = Field(default=0, ge=0)
    artifact_discovered: int = Field(default=0, ge=0)
    artifact_fetched: int = Field(default=0, ge=0)
    artifact_deferred: int = Field(default=0, ge=0)


class QualityRatio(BaseModel):
    """A bounded quality calculation with its explicit denominator."""

    model_config = ConfigDict(extra="forbid")

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_ratio(self) -> QualityRatio:
        if self.denominator == 0:
            if self.value is not None:
                raise ValueError("value must be null when denominator is zero")
            return self
        if self.numerator > self.denominator:
            raise ValueError("numerator cannot exceed denominator")
        expected = self.numerator / self.denominator
        if self.value is None or abs(self.value - expected) > 1e-12:
            raise ValueError("value must equal numerator divided by denominator")
        return self


class FreshnessMetric(QualityRatio):
    """Coverage of source-provided freshness metadata, not a staleness claim."""

    newest_source_last_modified_at: str | None = None
    captured_at: datetime


class AdapterQualityMetrics(BaseModel):
    """Comparable, denominator-based quality measurements for one source run."""

    model_config = ConfigDict(extra="forbid")

    coverage_scope: str = Field(min_length=1, max_length=500)
    completeness: QualityRatio
    validity: QualityRatio
    duplicate_rate: QualityRatio
    freshness: FreshnessMetric
    limitations: tuple[str, ...] = ()


class AdapterRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str
    adapter_name: str
    adapter_version: str
    status: Literal["completed", "failed"]
    dry_run: bool
    statistics: RunStatistics
    issues: tuple[AdapterIssue, ...] = ()
    import_counts: dict[str, int] | None = None
    quality: AdapterQualityMetrics | None = None


class AdapterReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: Literal[ADAPTER_REPORT_VERSION] = ADAPTER_REPORT_VERSION
    contract_version: Literal[ADAPTER_CONTRACT_VERSION] = ADAPTER_CONTRACT_VERSION
    source_key: str
    adapter_name: str
    adapter_version: str
    status: Literal["completed", "failed"]
    dry_run: bool
    statistics: RunStatistics
    issues: tuple[AdapterIssue, ...] = ()
    import_counts: dict[str, int] | None = None
    quality: AdapterQualityMetrics | None = None
    source_id: UUID | None = None
    ingestion_run_id: UUID | None = None


class SourceAdapter(Protocol):
    name: str
    version: str

    def discover(self, context: AdapterContext) -> DiscoveryResult:
        ...

    def fetch(
        self,
        resource: DiscoveredResource,
        context: AdapterContext,
    ) -> FetchResult:
        ...

    def extract(
        self,
        fetched: FetchResult,
        context: AdapterContext,
    ) -> ExtractResult:
        ...

    def validate(
        self,
        records: Sequence[ExtractedRecord],
        context: AdapterContext,
    ) -> ValidationResult:
        ...

    def report(self, summary: AdapterRunSummary) -> AdapterReport:
        ...


class RecordEnricher(Protocol):
    """Optional extension for adapters that associate auxiliary captures with records."""

    def enrich(
        self,
        records: Sequence[ExtractedRecord],
        fetched: Sequence[FetchResult],
        context: AdapterContext,
    ) -> ExtractResult:
        ...


def validate_import_records(records: Sequence[ExtractedRecord]) -> ValidationResult:
    parsed_rows = [
        parse_record(
            record.raw_payload,
            row_number=record.row_number,
            capture_key=record.capture_key,
        )
        for record in records
    ]
    return ValidationResult(rows=add_duplicate_key_issues(parsed_rows))


def validation_issue_to_adapter_issue(
    issue: ValidationIssue,
    *,
    stage: str = AdapterStage.VALIDATE,
    resource_key: str | None = None,
) -> AdapterIssue:
    return AdapterIssue(
        stage=stage,
        severity="error",
        code=issue.code,
        message=issue.message,
        resource_key=resource_key,
        row_number=issue.row_number,
        field=issue.field,
    )


def adapter_report(
    adapter: SourceAdapter,
    summary: AdapterRunSummary,
    *,
    source_id: UUID | None = None,
    ingestion_run_id: UUID | None = None,
) -> AdapterReport:
    return AdapterReport(
        source_key=summary.source_key,
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        status=summary.status,
        dry_run=summary.dry_run,
        statistics=summary.statistics,
        issues=summary.issues,
        import_counts=summary.import_counts,
        quality=summary.quality,
        source_id=source_id,
        ingestion_run_id=ingestion_run_id,
    )

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.models import (
    DataQualitySeverity,
    FundingValueKind,
    IngestionRunStatus,
    ProgramAccessMode,
    ProgramFundingScope,
    ProgramResourceKind,
    ProgramSourceStatus,
    ProgramTimelineEventKind,
    ReviewActionType,
    ReviewCaseStatus,
    SourceExecutionStatus,
    SourceExecutionTrigger,
    StagedRecordState,
)
from app.import_bridge.contract import FundingInput


class InternalSchema(BaseModel):
    """Base schema for authenticated operational responses."""

    model_config = ConfigDict(extra="forbid")


class InternalError(InternalSchema):
    code: str
    message: str


class InternalErrorResponse(InternalSchema):
    error: InternalError


class InternalSource(InternalSchema):
    id: UUID
    name: str
    canonical_url: str
    created_at: datetime


class InternalRegisteredSource(InternalSchema):
    """Non-secret source registry data available to local operators."""

    source_key: str
    name: str
    canonical_url: str
    allowed_url_prefixes: list[str]
    allowed_exact_urls: list[str]
    access_method: str
    schedule: str
    status: str
    responsible: str
    adapter_name: str
    adapter_version: str


class InternalReviewQueueItem(InternalSchema):
    review_case_id: UUID
    staged_record_id: UUID
    status: ReviewCaseStatus
    opened_at: datetime
    reason_codes: list[str]
    title: str | None = None
    source_url: str | None = None


class InternalReviewIssueResolution(InternalSchema):
    id: UUID
    review_revision_id: UUID
    reason: str
    actor: str
    created_at: datetime


class InternalQualityIssue(InternalSchema):
    id: UUID
    staged_record_id: UUID
    record_key: str
    staged_state: StagedRecordState
    source_id: UUID
    severity: DataQualitySeverity
    code: str
    message: str
    created_at: datetime
    review_case_id: UUID | None = None
    resolution: InternalReviewIssueResolution | None = None


class InternalReviewAction(InternalSchema):
    id: UUID
    action: ReviewActionType
    reason: str
    actor: str
    deduplication_match_id: UUID | None = None
    target_staged_record_id: UUID | None = None
    target_program_id: UUID | None = None
    review_decision_id: UUID | None = None
    prior_values: dict[str, Any]
    result_values: dict[str, Any]
    created_at: datetime


class InternalReviewRevision(InternalSchema):
    id: UUID
    revision_number: int = Field(ge=1)
    changed_fields: list[str]
    deduplication_snapshot: dict[str, Any]
    reason: str
    actor: str
    created_at: datetime
    resolved_issue_ids: list[UUID]


class InternalReviewProvenance(InternalSchema):
    source_id: UUID
    source_name: str
    source_canonical_url: str
    source_url: str
    raw_capture_id: UUID
    ingestion_run_id: UUID
    received_at: datetime
    content_sha256: str
    content_format: str
    adapter_name: str
    adapter_version: str


class InternalReviewTaxonomyOption(InternalSchema):
    slug: str
    name: str


class InternalReviewFunding(InternalSchema):
    value_kind: FundingValueKind
    currency_code: str | None = None
    exact_amount: str | None = None
    min_amount: str | None = None
    max_amount: str | None = None


class InternalReviewFundingAmount(InternalReviewFunding):
    scope: ProgramFundingScope
    label: str | None = None


class InternalReviewTimelineEvent(InternalSchema):
    kind: ProgramTimelineEventKind
    label: str
    start_on: date | None = None
    end_on: date | None = None


class InternalReviewResource(InternalSchema):
    kind: ProgramResourceKind
    title: str | None = None
    url: str
    source_section: str | None = None


class InternalReviewContentSection(InternalSchema):
    heading: str
    category: str
    content: str


class InternalReviewPreviewSource(InternalSchema):
    id: UUID
    name: str
    canonical_url: str


class InternalReviewPublicPreview(InternalSchema):
    title: str
    source: InternalReviewPreviewSource
    source_url: str
    observed_at: datetime
    source_published_on: date | None = None
    summary: str | None = None
    source_status: ProgramSourceStatus
    deadline_on: date | None = None
    funding: InternalReviewFunding | None = None
    geographies: list[InternalReviewTaxonomyOption]
    themes: list[InternalReviewTaxonomyOption]
    eligibility_summary: str | None = None
    eligibility_geography_note: str | None = None
    access_mode: ProgramAccessMode
    application_url: str | None = None
    application_start_on: date | None = None
    application_end_on: date | None = None
    funding_amounts: list[InternalReviewFundingAmount]
    timeline: list[InternalReviewTimelineEvent]
    resources: list[InternalReviewResource]
    content_sections: list[InternalReviewContentSection]


class InternalReviewCaseDetail(InternalReviewQueueItem):
    opened_snapshot: dict[str, Any]
    source_record: dict[str, Any]
    effective_record: dict[str, Any]
    provenance: InternalReviewProvenance
    quality_issues: list[InternalQualityIssue]
    actions: list[InternalReviewAction]
    revisions: list[InternalReviewRevision]
    public_preview: InternalReviewPublicPreview


CanonicalReviewAction = Literal["accept", "reject", "merge", "needs_clarification"]


class CanonicalReviewActionRequest(InternalSchema):
    action: CanonicalReviewAction
    reason: str = Field(min_length=1, max_length=4_000)
    deduplication_match_id: UUID | None = None

    @model_validator(mode="after")
    def validate_merge_target(self) -> CanonicalReviewActionRequest:
        if self.action == "merge" and self.deduplication_match_id is None:
            raise ValueError("deduplication_match_id is required for merge")
        if self.action != "merge" and self.deduplication_match_id is not None:
            raise ValueError("deduplication_match_id is only allowed for merge")
        return self


class CanonicalReviewActionResponse(InternalSchema):
    operation_id: UUID
    replayed: bool
    review_case_id: UUID
    staged_record_id: UUID
    review_action_id: UUID
    program_id: UUID | None = None
    review_decision_id: UUID | None = None


class InternalReviewApplicationPatch(InternalSchema):
    url: str | None = Field(default=None, max_length=2_048)
    start_on: date | None = None
    end_on: date | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("must be an absolute http(s) URL")
        return normalized


class InternalReviewEligibilityPatch(InternalSchema):
    summary: str | None = Field(default=None, max_length=20_000)
    geography_note: str | None = Field(default=None, max_length=4_000)
    access_mode: ProgramAccessMode | None = None


class InternalReviewTaxonomyPatchItem(InternalSchema):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", normalized):
            raise ValueError("must use lowercase letters, numbers, and hyphens")
        return normalized


class InternalReviewTaxonomyPatch(InternalSchema):
    themes: list[InternalReviewTaxonomyPatchItem] | None = Field(default=None, max_length=100)
    geographies: list[InternalReviewTaxonomyPatchItem] | None = Field(
        default=None,
        max_length=100,
    )


class InternalReviewFundingAmountPatch(InternalSchema):
    scope: ProgramFundingScope
    value: FundingInput
    label: str | None = Field(default=None, max_length=500)
    evidence: str | None = Field(default=None, max_length=2_000)


class InternalReviewTimelinePatch(InternalSchema):
    kind: ProgramTimelineEventKind = ProgramTimelineEventKind.OTHER
    label: str = Field(min_length=1, max_length=500)
    start_on: date | None = None
    end_on: date | None = None
    evidence: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_date_range(self) -> InternalReviewTimelinePatch:
        if self.start_on is None and self.end_on is None:
            raise ValueError("at least one event date is required")
        if self.start_on is not None and self.end_on is not None and self.start_on > self.end_on:
            raise ValueError("start_on must not be after end_on")
        return self


class InternalReviewResourcePatch(InternalSchema):
    kind: Literal["application", "document", "result", "detail", "reference"]
    url: str = Field(min_length=1, max_length=2_048)
    label: str | None = Field(default=None, max_length=500)
    section_title: str | None = Field(default=None, max_length=500)
    section_category: str | None = Field(default=None, max_length=64)
    content_format: str | None = Field(default=None, max_length=100)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("must be an absolute http(s) URL")
        return normalized


class InternalReviewContentBlockPatch(InternalSchema):
    heading: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=50_000)


class InternalReviewRecordPatch(InternalSchema):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    deadline_on: date | None = None
    funding: FundingInput | None = None
    summary: str | None = Field(default=None, max_length=20_000)
    source_published_on: date | None = None
    source_status: ProgramSourceStatus | None = None
    application: InternalReviewApplicationPatch | None = None
    eligibility: InternalReviewEligibilityPatch | None = None
    taxonomy: InternalReviewTaxonomyPatch | None = None
    funding_amounts: list[InternalReviewFundingAmountPatch] | None = Field(
        default=None,
        max_length=100,
    )
    timeline: list[InternalReviewTimelinePatch] | None = Field(default=None, max_length=100)
    resources: list[InternalReviewResourcePatch] | None = Field(default=None, max_length=100)
    content_blocks: list[InternalReviewContentBlockPatch] | None = Field(
        default=None,
        max_length=100,
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("must not be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class SaveReviewRevisionRequest(InternalSchema):
    reason: str = Field(min_length=1, max_length=4_000)
    patch: InternalReviewRecordPatch
    resolve_issue_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @field_validator("resolve_issue_ids")
    @classmethod
    def reject_duplicate_issue_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("resolve_issue_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def require_a_change_or_resolution(self) -> SaveReviewRevisionRequest:
        if not self.patch.model_fields_set and not self.resolve_issue_ids:
            raise ValueError("a patch or an issue resolution is required")
        return self

    def patch_values(self) -> dict[str, Any]:
        return self.patch.model_dump(mode="json", exclude_unset=True)


class SaveReviewRevisionResponse(InternalSchema):
    operation_id: UUID
    replayed: bool
    review_case_id: UUID
    staged_record_id: UUID
    review_revision_id: UUID
    revision_number: int = Field(ge=1)
    changed_fields: list[str]
    resolved_issue_ids: list[UUID]


class InternalDiscoveryReviewQueueItem(InternalSchema):
    review_case_id: UUID
    status: ReviewCaseStatus
    subject_type: Literal["message", "url"]
    subject_reference: str
    opened_at: datetime
    reason_codes: list[str]


DiscoveryReviewAction = Literal[
    "link_to_registered_source",
    "reject",
    "needs_clarification",
]


class DiscoveryReviewActionRequest(InternalSchema):
    action: DiscoveryReviewAction
    reason: str = Field(min_length=1, max_length=4_000)
    source_key: str | None = Field(default=None, min_length=2, max_length=64)

    @model_validator(mode="after")
    def validate_source_key(self) -> DiscoveryReviewActionRequest:
        if self.action == "link_to_registered_source" and self.source_key is None:
            raise ValueError("source_key is required when linking to a source")
        if self.action != "link_to_registered_source" and self.source_key is not None:
            raise ValueError("source_key is only allowed when linking to a source")
        return self


class DiscoveryReviewActionResponse(InternalSchema):
    operation_id: UUID
    replayed: bool
    review_case_id: UUID
    discovery_review_action_id: UUID
    status: ReviewCaseStatus
    target_source_key: str | None = None


class InternalExecutionRun(InternalSchema):
    id: UUID
    source_id: UUID
    source_key: str
    trigger: SourceExecutionTrigger
    status: SourceExecutionStatus
    started_at: datetime
    finished_at: datetime | None = None
    ingestion_run_id: UUID | None = None
    attempt_count: int
    result_kind: str | None = None
    error_codes: list[str]
    metrics: dict[str, Any]


class InternalIngestionRun(InternalSchema):
    id: UUID
    source_id: UUID
    adapter_name: str
    adapter_version: str
    status: IngestionRunStatus
    received_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    raw_capture_count: int
    staged_record_count: int
    quality_issue_count: int
    quality_error_count: int
    run_statistics: dict[str, Any]


class ProgramRepublishRequest(InternalSchema):
    reason: str = Field(min_length=1, max_length=4_000)


class ProgramRepublishResponse(InternalSchema):
    operation_id: UUID
    replayed: bool
    program_id: UUID
    review_case_id: UUID
    review_decision_id: UUID
    program_publication_action_id: UUID
    published_at: datetime


class ProgramArchiveRequest(InternalSchema):
    reason: str = Field(min_length=1, max_length=4_000)


class ProgramArchiveResponse(InternalSchema):
    operation_id: UUID
    replayed: bool
    program_id: UUID
    review_case_id: UUID
    review_decision_id: UUID
    program_publication_action_id: UUID
    archived_at: datetime

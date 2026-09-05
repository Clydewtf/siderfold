from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import (
    DataQualitySeverity,
    IngestionRunStatus,
    ReviewActionType,
    ReviewCaseStatus,
    SourceExecutionStatus,
    SourceExecutionTrigger,
    StagedRecordState,
)


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


class InternalReviewQueueItem(InternalSchema):
    review_case_id: UUID
    staged_record_id: UUID
    status: ReviewCaseStatus
    opened_at: datetime
    reason_codes: list[str]
    title: str | None = None
    source_url: str | None = None


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


class InternalReviewCaseDetail(InternalReviewQueueItem):
    opened_snapshot: dict[str, Any]
    quality_issues: list[InternalQualityIssue]
    actions: list[InternalReviewAction]


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

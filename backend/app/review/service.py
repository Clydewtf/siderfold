from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from hashlib import sha256
import re
from typing import Any
from unicodedata import normalize as unicode_normalize
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection

from app.domain.models import (
    DataQualityIssue,
    DataQualitySeverity,
    DeduplicationMatch,
    DeduplicationMatchDisposition,
    DeduplicationMatchLevel,
    IngestionRun,
    IngestionRunStatus,
    Geography,
    Program,
    ProgramAccessMode,
    ProgramContact,
    ProgramContentSection,
    ProgramDeadline,
    ProgramDetails,
    ProgramFunding,
    ProgramFundingAmount,
    ProgramFundingScope,
    ProgramGeography,
    ProgramResource,
    ProgramResourceKind,
    ProgramSource,
    ProgramSourceStatus,
    ProgramTheme,
    ProgramTimelineEvent,
    ProgramTimelineEventKind,
    PublicationStatus,
    RawCapture,
    ReviewAction,
    ReviewActionType,
    ReviewCase,
    ReviewCaseStatus,
    ReviewDecision,
    ReviewDecisionOutcome,
    ReviewIssueResolution,
    ReviewRevision,
    Source,
    StagedRecord,
    StagedRecordState,
    Theme,
)
from app.domain.presentation import (
    has_russia_scope,
    is_public_content_section,
    is_public_resource,
    is_winner_resource,
    public_resource_kind,
    public_program_title,
    resolved_access_mode,
    winner_resource_group_key,
)
from app.import_bridge.contract import FundingInput
from app.review.deduplication import (
    CandidateFingerprint,
    conflicting_fields,
    normalized_fields_match,
    program_fingerprint,
    staged_fingerprint,
)


class ReviewPolicyError(ValueError):
    """Raised when an attempted review action would violate the review policy."""


@dataclass(frozen=True)
class QualitySummary:
    warning_codes: tuple[str, ...]
    error_codes: tuple[str, ...]

    @property
    def blocks_publication(self) -> bool:
        return bool(self.error_codes)

    @property
    def blocks_auto_merge(self) -> bool:
        return bool(self.warning_codes or self.error_codes)

    def audit_values(self) -> dict[str, list[str]]:
        return {
            "warnings": list(self.warning_codes),
            "errors": list(self.error_codes),
        }


@dataclass(frozen=True)
class StagedCandidate:
    id: UUID
    raw_capture_id: UUID
    record_key: str
    candidate_payload: Mapping[str, Any]
    state: StagedRecordState
    source_id: UUID
    received_at: datetime
    ingestion_status: IngestionRunStatus
    fingerprint: CandidateFingerprint
    quality: QualitySummary


@dataclass(frozen=True)
class MatchObservation:
    target_staged_record_id: UUID | None
    target_program_id: UUID | None
    level: DeduplicationMatchLevel
    target: CandidateFingerprint
    conflicts: tuple[str, ...]
    target_quality: QualitySummary
    target_ingestion_status: IngestionRunStatus | None

    @property
    def is_staged_target(self) -> bool:
        return self.target_staged_record_id is not None


@dataclass(frozen=True)
class PersistedMatch:
    id: UUID
    observation: MatchObservation
    disposition: DeduplicationMatchDisposition


@dataclass(frozen=True)
class ReviewEvaluation:
    review_case_id: UUID
    staged_record_id: UUID
    match_ids: tuple[UUID, ...]
    auto_merged: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ReviewActionResult:
    review_case_id: UUID
    review_action_id: UUID
    staged_record_id: UUID
    program_id: UUID | None = None
    review_decision_id: UUID | None = None


@dataclass(frozen=True)
class ReviewRevisionResult:
    review_case_id: UUID
    staged_record_id: UUID
    review_revision_id: UUID
    revision_number: int
    changed_fields: tuple[str, ...]
    resolved_issue_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class ReviewQueueItem:
    review_case_id: UUID
    staged_record_id: UUID
    status: ReviewCaseStatus
    opened_at: datetime
    reason_codes: tuple[str, ...]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _nonblank(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ReviewPolicyError(f"{field} must not be blank")
    return normalized


def _quality_summary(connection: Connection, staged_record_id: UUID) -> QualitySummary:
    rows = connection.execute(
        select(DataQualityIssue.severity, DataQualityIssue.code)
        .where(DataQualityIssue.staged_record_id == staged_record_id)
        .order_by(DataQualityIssue.created_at, DataQualityIssue.id)
    )
    warnings: list[str] = []
    errors: list[str] = []
    for severity, code in rows:
        if severity is DataQualitySeverity.ERROR:
            errors.append(code)
        else:
            warnings.append(code)
    return QualitySummary(tuple(warnings), tuple(errors))


def _load_staged_candidate(
    connection: Connection,
    staged_record_id: UUID,
    *,
    lock: bool = False,
) -> StagedCandidate:
    statement = (
        select(
            StagedRecord.id,
            StagedRecord.raw_capture_id,
            StagedRecord.record_key,
            StagedRecord.candidate_payload,
            StagedRecord.state,
            IngestionRun.source_id,
            RawCapture.received_at,
            IngestionRun.status.label("ingestion_status"),
        )
        .select_from(StagedRecord)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
        .where(StagedRecord.id == staged_record_id)
    )
    if lock:
        statement = statement.with_for_update()
    row = connection.execute(statement).mappings().one_or_none()
    if row is None:
        raise ReviewPolicyError(f"unknown staged record: {staged_record_id}")
    payload = row["candidate_payload"]
    if not isinstance(payload, Mapping):
        raise ReviewPolicyError("staged candidate payload must be an object")
    source_id = row["source_id"]
    record_key = row["record_key"]
    return StagedCandidate(
        id=row["id"],
        raw_capture_id=row["raw_capture_id"],
        record_key=record_key,
        candidate_payload=payload,
        state=StagedRecordState(row["state"]),
        source_id=source_id,
        received_at=row["received_at"],
        ingestion_status=IngestionRunStatus(row["ingestion_status"]),
        fingerprint=staged_fingerprint(
            source_id=source_id,
            record_key=record_key,
            candidate_payload=payload,
        ),
        quality=_quality_summary(connection, row["id"]),
    )


def _review_case_id(connection: Connection, staged_record_id: UUID) -> UUID | None:
    return connection.scalar(
        select(ReviewCase.id).where(ReviewCase.staged_record_id == staged_record_id)
    )


def _load_staged_targets(
    connection: Connection,
    candidate: StagedCandidate,
) -> tuple[StagedCandidate, ...]:
    statement = (
        select(StagedRecord.id)
        .where(
            StagedRecord.id != candidate.id,
            StagedRecord.state == StagedRecordState.REVIEW,
        )
        .order_by(StagedRecord.created_at, StagedRecord.id)
    )
    targets: list[StagedCandidate] = []
    for staged_record_id in connection.scalars(statement):
        target = _load_staged_candidate(connection, staged_record_id)
        existing_case_status = connection.scalar(
            select(ReviewCase.status).where(ReviewCase.staged_record_id == target.id)
        )
        if existing_case_status is ReviewCaseStatus.NEEDS_CLARIFICATION:
            continue
        targets.append(target)
    return tuple(targets)


def _load_program_targets(connection: Connection) -> tuple[tuple[UUID, CandidateFingerprint], ...]:
    statement = (
        select(
            Program.id.label("program_id"),
            Program.title,
            ProgramSource.source_id,
            ProgramSource.source_url,
            ProgramDeadline.deadline_on,
            ProgramFunding.value_kind,
            ProgramFunding.currency_code,
            ProgramFunding.exact_amount,
            ProgramFunding.min_amount,
            ProgramFunding.max_amount,
            ReviewDecision.staged_record_id.label("provenance_staged_record_id"),
            StagedRecord.record_key.label("provenance_record_key"),
            StagedRecord.candidate_payload.label("provenance_candidate_payload"),
        )
        .select_from(Program)
        .join(ProgramSource, ProgramSource.program_id == Program.id)
        .outerjoin(ProgramDeadline, ProgramDeadline.program_id == Program.id)
        .outerjoin(ProgramFunding, ProgramFunding.program_id == Program.id)
        .outerjoin(
            ReviewDecision,
            ReviewDecision.id == Program.publication_review_decision_id,
        )
        .outerjoin(StagedRecord, StagedRecord.id == ReviewDecision.staged_record_id)
    )
    targets: list[tuple[UUID, CandidateFingerprint]] = []
    for row in connection.execute(statement).mappings():
        funding: dict[str, Any] | None = None
        if row["value_kind"] is not None:
            funding = {
                "value_kind": row["value_kind"].value,
                "currency_code": row["currency_code"],
                "exact_amount": row["exact_amount"],
                "min_amount": row["min_amount"],
                "max_amount": row["max_amount"],
            }
        canonical = program_fingerprint(
            source_id=row["source_id"],
            title=row["title"],
            source_url=row["source_url"],
            deadline_on=row["deadline_on"],
            funding=funding,
        )
        provenance_payload = row["provenance_candidate_payload"]
        provenance_key = row["provenance_record_key"]
        if isinstance(provenance_payload, Mapping) and isinstance(provenance_key, str):
            provenance = staged_fingerprint(
                source_id=row["source_id"],
                record_key=provenance_key,
                candidate_payload=provenance_payload,
            )
            canonical = CandidateFingerprint(
                source_id=canonical.source_id,
                record_key=provenance.record_key,
                external_id=provenance.external_id,
                source_url=canonical.source_url or provenance.source_url,
                title=canonical.title,
                organizer=provenance.organizer,
                deadline_on=canonical.deadline_on,
                funding=canonical.funding,
            )
        targets.append((row["program_id"], canonical))
    return tuple(targets)


def _match_level(
    candidate: CandidateFingerprint,
    target: CandidateFingerprint,
) -> DeduplicationMatchLevel | None:
    if (
        candidate.source_id == target.source_id
        and candidate.external_id is not None
        and candidate.external_id == target.external_id
    ):
        return DeduplicationMatchLevel.EXACT_EXTERNAL_ID
    if (
        candidate.source_id == target.source_id
        and candidate.source_url is not None
        and candidate.source_url == target.source_url
    ):
        return DeduplicationMatchLevel.EXACT_URL
    if normalized_fields_match(candidate, target):
        return DeduplicationMatchLevel.NORMALIZED_FIELDS
    return None


def _find_matches(
    connection: Connection,
    candidate: StagedCandidate,
) -> tuple[MatchObservation, ...]:
    observations: list[MatchObservation] = []
    for target in _load_staged_targets(connection, candidate):
        level = _match_level(candidate.fingerprint, target.fingerprint)
        if level is None:
            continue
        observations.append(
            MatchObservation(
                target_staged_record_id=target.id,
                target_program_id=None,
                level=level,
                target=target.fingerprint,
                conflicts=conflicting_fields(candidate.fingerprint, target.fingerprint),
                target_quality=target.quality,
                target_ingestion_status=target.ingestion_status,
            )
        )
    for program_id, target in _load_program_targets(connection):
        level = _match_level(candidate.fingerprint, target)
        if level is None:
            continue
        observations.append(
            MatchObservation(
                target_staged_record_id=None,
                target_program_id=program_id,
                level=level,
                target=target,
                conflicts=conflicting_fields(candidate.fingerprint, target),
                target_quality=QualitySummary((), ()),
                target_ingestion_status=None,
            )
        )
    return tuple(observations)


def _is_high_confidence_auto_merge(
    candidate: StagedCandidate,
    observation: MatchObservation,
) -> bool:
    return (
        observation.is_staged_target
        and observation.level
        in {DeduplicationMatchLevel.EXACT_EXTERNAL_ID, DeduplicationMatchLevel.EXACT_URL}
        and not observation.conflicts
        and not candidate.quality.blocks_auto_merge
        and not observation.target_quality.blocks_auto_merge
        and candidate.ingestion_status is IngestionRunStatus.COMPLETED
        and observation.target_ingestion_status is IngestionRunStatus.COMPLETED
    )


def _match_evidence(
    candidate: StagedCandidate,
    observation: MatchObservation,
) -> dict[str, Any]:
    return {
        "candidate": candidate.fingerprint.audit_values(),
        "target": observation.target.audit_values(),
        "match_level": observation.level.value,
        "conflicting_fields": list(observation.conflicts),
        "candidate_quality": candidate.quality.audit_values(),
        "target_quality": observation.target_quality.audit_values(),
        "candidate_ingestion_status": candidate.ingestion_status.value,
        "target_ingestion_status": (
            observation.target_ingestion_status.value
            if observation.target_ingestion_status is not None
            else None
        ),
    }


def _persist_match(
    connection: Connection,
    *,
    candidate: StagedCandidate,
    observation: MatchObservation,
    disposition: DeduplicationMatchDisposition,
) -> PersistedMatch:
    match_id = uuid4()
    connection.execute(
        insert(DeduplicationMatch).values(
            id=match_id,
            candidate_staged_record_id=candidate.id,
            target_staged_record_id=observation.target_staged_record_id,
            target_program_id=observation.target_program_id,
            match_level=observation.level,
            disposition=disposition,
            evidence=_match_evidence(candidate, observation),
        )
    )
    return PersistedMatch(
        id=match_id,
        observation=observation,
        disposition=disposition,
    )


def _reason_codes(
    candidate: StagedCandidate,
    observations: Sequence[MatchObservation],
    auto_merge: MatchObservation | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if candidate.quality.error_codes:
        reasons.append("quality_error")
    elif candidate.quality.warning_codes:
        reasons.append("quality_warning")
    if auto_merge is not None:
        reasons.append("high_confidence_duplicate")
    elif observations:
        if any(observation.conflicts for observation in observations):
            reasons.append("exact_identity_conflict")
        elif any(
            observation.level is DeduplicationMatchLevel.NORMALIZED_FIELDS
            for observation in observations
        ):
            reasons.append("possible_duplicate")
        else:
            reasons.append("exact_identity_requires_review")
        if len(observations) > 1:
            reasons.append("multiple_candidates")
    else:
        reasons.append("candidate_ready")
    return tuple(reasons)


def _case_snapshot(
    candidate: StagedCandidate,
    *,
    reason_codes: Sequence[str],
    matches: Sequence[PersistedMatch],
) -> dict[str, Any]:
    return {
        "staged_record_id": str(candidate.id),
        "raw_capture_id": str(candidate.raw_capture_id),
        "record_key": candidate.record_key,
        "state": candidate.state.value,
        "candidate_payload": dict(candidate.candidate_payload),
        "normalized_candidate": candidate.fingerprint.audit_values(),
        "quality": candidate.quality.audit_values(),
        "ingestion_status": candidate.ingestion_status.value,
        "reason_codes": list(reason_codes),
        "matches": [
            {
                "id": str(match.id),
                "disposition": match.disposition.value,
                "target_staged_record_id": (
                    str(match.observation.target_staged_record_id)
                    if match.observation.target_staged_record_id is not None
                    else None
                ),
                "target_program_id": (
                    str(match.observation.target_program_id)
                    if match.observation.target_program_id is not None
                    else None
                ),
                "evidence": _match_evidence(candidate, match.observation),
            }
            for match in matches
        ],
    }


def _create_review_case(
    connection: Connection,
    candidate: StagedCandidate,
    *,
    reason_codes: Sequence[str],
    matches: Sequence[PersistedMatch],
    now: datetime,
) -> UUID:
    review_case_id = uuid4()
    connection.execute(
        insert(ReviewCase).values(
            id=review_case_id,
            staged_record_id=candidate.id,
            status=ReviewCaseStatus.OPEN,
            opened_snapshot=_case_snapshot(
                candidate,
                reason_codes=reason_codes,
                matches=matches,
            ),
            opened_at=now,
            updated_at=now,
        )
    )
    return review_case_id


def _add_deduplication_issue(
    connection: Connection,
    *,
    candidate: StagedCandidate,
    observations: Sequence[MatchObservation],
) -> None:
    if not observations:
        return
    if any(observation.conflicts for observation in observations):
        code = "deduplication_exact_identity_conflict"
        message = "An exact source identity has conflicting populated canonical fields."
    elif any(
        observation.level is DeduplicationMatchLevel.NORMALIZED_FIELDS
        for observation in observations
    ):
        code = "deduplication_possible_duplicate"
        message = "Normalized title, organizer, and application deadline match another candidate."
    else:
        code = "deduplication_exact_identity_review"
        message = "An exact source identity requires a manual decision before publication."
    connection.execute(
        postgresql_insert(DataQualityIssue)
        .values(
            id=uuid4(),
            staged_record_id=candidate.id,
            severity=DataQualitySeverity.WARNING,
            code=code,
            message=message,
        )
        .on_conflict_do_nothing(index_elements=("staged_record_id", "code"))
    )


def _update_staged_state(
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


def _case_state_snapshot(
    candidate: StagedCandidate,
    *,
    case_status: ReviewCaseStatus,
    staged_state: StagedRecordState,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "review_case_status": case_status.value,
        "staged_record_id": str(candidate.id),
        "staged_record_state": staged_state.value,
        "normalized_candidate": candidate.fingerprint.audit_values(),
        "quality": candidate.quality.audit_values(),
    }
    if extra:
        values.update(extra)
    return values


def _insert_review_action(
    connection: Connection,
    *,
    review_case_id: UUID,
    action: ReviewActionType,
    reason: str,
    actor: str,
    prior_values: Mapping[str, Any],
    result_values: Mapping[str, Any],
    deduplication_match_id: UUID | None = None,
    target_staged_record_id: UUID | None = None,
    target_program_id: UUID | None = None,
    review_decision_id: UUID | None = None,
    now: datetime,
) -> UUID:
    review_action_id = uuid4()
    connection.execute(
        insert(ReviewAction).values(
            id=review_action_id,
            review_case_id=review_case_id,
            action=action,
            reason=reason,
            actor=actor,
            deduplication_match_id=deduplication_match_id,
            target_staged_record_id=target_staged_record_id,
            target_program_id=target_program_id,
            review_decision_id=review_decision_id,
            prior_values=dict(prior_values),
            result_values=dict(result_values),
            created_at=now,
        )
    )
    return review_action_id


def _set_case_status(
    connection: Connection,
    *,
    review_case_id: UUID,
    status: ReviewCaseStatus,
    now: datetime,
) -> None:
    connection.execute(
        update(ReviewCase)
        .where(ReviewCase.id == review_case_id)
        .values(
            status=status,
            resolved_at=now if status is ReviewCaseStatus.RESOLVED else None,
            updated_at=now,
        )
    )


def _automatic_merge(
    connection: Connection,
    *,
    candidate: StagedCandidate,
    review_case_id: UUID,
    match: PersistedMatch,
    now: datetime,
) -> None:
    target_id = match.observation.target_staged_record_id
    if target_id is None:
        raise RuntimeError("automatic merge requires a staging target")
    prior = _case_state_snapshot(
        candidate,
        case_status=ReviewCaseStatus.OPEN,
        staged_state=StagedRecordState.REVIEW,
    )
    result = _case_state_snapshot(
        candidate,
        case_status=ReviewCaseStatus.RESOLVED,
        staged_state=StagedRecordState.REJECTED,
        extra={"merged_into_staged_record_id": str(target_id)},
    )
    _insert_review_action(
        connection,
        review_case_id=review_case_id,
        action=ReviewActionType.AUTO_MERGE,
        reason="Exact source identity and populated canonical fields match an earlier candidate.",
        actor="system",
        deduplication_match_id=match.id,
        target_staged_record_id=target_id,
        prior_values=prior,
        result_values=result,
        now=now,
    )
    _update_staged_state(
        connection,
        staged_record_id=candidate.id,
        state=StagedRecordState.REJECTED,
        now=now,
    )
    _set_case_status(
        connection,
        review_case_id=review_case_id,
        status=ReviewCaseStatus.RESOLVED,
        now=now,
    )


def evaluate_staged_record(
    connection: Connection,
    staged_record_id: UUID,
) -> ReviewEvaluation:
    """Classify one review-ready candidate and create its immutable match evidence.

    The caller owns the outer transaction. A savepoint keeps this operation
    atomic when it is composed with an import or a later operator action.
    """

    with connection.begin_nested():
        existing_case_id = _review_case_id(connection, staged_record_id)
        if existing_case_id is not None:
            return ReviewEvaluation(
                review_case_id=existing_case_id,
                staged_record_id=staged_record_id,
                match_ids=tuple(
                    connection.scalars(
                        select(DeduplicationMatch.id)
                        .where(DeduplicationMatch.candidate_staged_record_id == staged_record_id)
                        .order_by(DeduplicationMatch.created_at, DeduplicationMatch.id)
                    )
                ),
                auto_merged=connection.scalar(
                    select(ReviewAction.id)
                    .join(ReviewCase, ReviewCase.id == ReviewAction.review_case_id)
                    .where(
                        ReviewCase.id == existing_case_id,
                        ReviewAction.action == ReviewActionType.AUTO_MERGE,
                    )
                )
                is not None,
                reason_codes=(),
            )

        candidate = _load_staged_candidate(connection, staged_record_id, lock=True)
        if candidate.state is not StagedRecordState.REVIEW:
            raise ReviewPolicyError("only review-ready staged records can enter the review queue")

        observations = _find_matches(connection, candidate)
        high_confidence = [
            observation
            for observation in observations
            if _is_high_confidence_auto_merge(candidate, observation)
        ]
        auto_observation = (
            high_confidence[0]
            if len(observations) == 1 and len(high_confidence) == 1
            else None
        )
        persisted_matches = tuple(
            _persist_match(
                connection,
                candidate=candidate,
                observation=observation,
                disposition=(
                    DeduplicationMatchDisposition.AUTO_MERGED
                    if observation is auto_observation
                    else DeduplicationMatchDisposition.REVIEW_REQUIRED
                ),
            )
            for observation in observations
        )
        reason_codes = _reason_codes(candidate, observations, auto_observation)
        if auto_observation is None:
            _add_deduplication_issue(
                connection,
                candidate=candidate,
                observations=observations,
            )
            candidate = _load_staged_candidate(connection, staged_record_id, lock=True)
        now = _now()
        review_case_id = _create_review_case(
            connection,
            candidate,
            reason_codes=reason_codes,
            matches=persisted_matches,
            now=now,
        )
        if auto_observation is not None:
            matching_record = next(
                match
                for match in persisted_matches
                if match.observation is auto_observation
            )
            _automatic_merge(
                connection,
                candidate=candidate,
                review_case_id=review_case_id,
                match=matching_record,
                now=now,
            )
        return ReviewEvaluation(
            review_case_id=review_case_id,
            staged_record_id=staged_record_id,
            match_ids=tuple(match.id for match in persisted_matches),
            auto_merged=auto_observation is not None,
            reason_codes=reason_codes,
        )


def list_review_queue(connection: Connection, *, limit: int = 100) -> tuple[ReviewQueueItem, ...]:
    """Return unresolved review cases for a future internal moderation surface."""

    if limit < 1 or limit > 1_000:
        raise ValueError("limit must be between 1 and 1000")
    statement = (
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
        .order_by(ReviewCase.opened_at, ReviewCase.id)
        .limit(limit)
    )
    items: list[ReviewQueueItem] = []
    for row in connection.execute(statement).mappings():
        snapshot = row["opened_snapshot"]
        raw_reasons = snapshot.get("reason_codes", []) if isinstance(snapshot, Mapping) else []
        reasons = tuple(value for value in raw_reasons if isinstance(value, str))
        items.append(
            ReviewQueueItem(
                review_case_id=row["id"],
                staged_record_id=row["staged_record_id"],
                status=ReviewCaseStatus(row["status"]),
                opened_at=row["opened_at"],
                reason_codes=reasons,
            )
        )
    return tuple(items)


def _lock_review_case(
    connection: Connection,
    review_case_id: UUID,
) -> tuple[ReviewCaseStatus, StagedCandidate]:
    row = connection.execute(
        select(ReviewCase.staged_record_id, ReviewCase.status)
        .where(ReviewCase.id == review_case_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise ReviewPolicyError(f"unknown review case: {review_case_id}")
    status = ReviewCaseStatus(row.status)
    if status is ReviewCaseStatus.RESOLVED:
        raise ReviewPolicyError("review case is already resolved")
    candidate = _load_staged_candidate(connection, row.staged_record_id, lock=True)
    if candidate.state is not StagedRecordState.REVIEW:
        raise ReviewPolicyError("review case does not point to a review-ready staged record")
    return status, candidate


def _record_payload(candidate: StagedCandidate) -> Mapping[str, Any]:
    record = candidate.candidate_payload.get("record")
    return record if isinstance(record, Mapping) else candidate.candidate_payload


def _json_object(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewPolicyError(f"{field} must be an object")
    return deepcopy(dict(value))


def _latest_review_revision_record(
    connection: Connection,
    review_case_id: UUID,
) -> dict[str, Any] | None:
    row = connection.execute(
        select(ReviewRevision.effective_record)
        .where(ReviewRevision.review_case_id == review_case_id)
        .order_by(ReviewRevision.revision_number.desc(), ReviewRevision.id.desc())
        .limit(1)
    ).one_or_none()
    if row is None:
        return None
    return _json_object(row.effective_record, field="review revision effective_record")


def review_effective_record(
    connection: Connection,
    review_case_id: UUID,
    *,
    candidate: StagedCandidate | None = None,
) -> dict[str, Any]:
    """Return the immutable source record with the latest audited correction applied."""

    revised = _latest_review_revision_record(connection, review_case_id)
    if revised is not None:
        return revised
    if candidate is None:
        staged_record_id = connection.scalar(
            select(ReviewCase.staged_record_id).where(ReviewCase.id == review_case_id)
        )
        if staged_record_id is None:
            raise ReviewPolicyError(f"unknown review case: {review_case_id}")
        candidate = _load_staged_candidate(connection, staged_record_id)
    return _json_object(_record_payload(candidate), field="staged candidate record")


def _candidate_with_record(
    candidate: StagedCandidate,
    record: Mapping[str, Any],
) -> StagedCandidate:
    payload = {"record": deepcopy(dict(record))}
    return replace(
        candidate,
        candidate_payload=payload,
        fingerprint=staged_fingerprint(
            source_id=candidate.source_id,
            record_key=candidate.record_key,
            candidate_payload=payload,
        ),
    )


def _unresolved_quality_summary(connection: Connection, staged_record_id: UUID) -> QualitySummary:
    rows = connection.execute(
        select(DataQualityIssue.severity, DataQualityIssue.code)
        .outerjoin(
            ReviewIssueResolution,
            ReviewIssueResolution.data_quality_issue_id == DataQualityIssue.id,
        )
        .where(
            DataQualityIssue.staged_record_id == staged_record_id,
            ReviewIssueResolution.id.is_(None),
        )
        .order_by(DataQualityIssue.created_at, DataQualityIssue.id)
    )
    warnings: list[str] = []
    errors: list[str] = []
    for severity, code in rows:
        if severity is DataQualitySeverity.ERROR:
            errors.append(code)
        else:
            warnings.append(code)
    return QualitySummary(tuple(warnings), tuple(errors))


def _changed_record_paths(
    previous: object,
    current: object,
    *,
    prefix: str = "",
    limit: int = 100,
) -> list[str]:
    """Produce stable, bounded paths for the audit history without storing a second diff."""

    if previous == current:
        return []
    if isinstance(previous, Mapping) and isinstance(current, Mapping):
        paths: list[str] = []
        for key in sorted(set(previous) | set(current)):
            if len(paths) >= limit:
                break
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            if key not in previous or key not in current:
                paths.append(next_prefix)
                continue
            paths.extend(
                _changed_record_paths(
                    previous[key],
                    current[key],
                    prefix=next_prefix,
                    limit=limit - len(paths),
                )
            )
        return paths[:limit]
    return [prefix or "record"]


def _manual_taxonomy_slug(*, namespace: str, name: str) -> str:
    digest = sha256(f"{namespace}\x00{name.casefold()}".encode("utf-8")).hexdigest()
    return f"manual-{digest[:16]}"


def _taxonomy_name_key(value: str) -> str:
    """Return a stable comparison key for human-entered taxonomy labels."""

    return re.sub(r"\s+", " ", unicode_normalize("NFKC", value)).strip().casefold()


def _taxonomy_entry_preference(entry: tuple[str, str]) -> tuple[bool, str, str]:
    """Prefer a named taxonomy slug over a fallback created by an operator."""

    slug, name = entry
    return (slug.startswith("manual-"), slug, name)


def _taxonomy_model(namespace: str) -> type[Theme] | type[Geography]:
    if namespace == "themes":
        return Theme
    if namespace == "geographies":
        return Geography
    raise ReviewPolicyError(f"unsupported taxonomy namespace: {namespace}")


def _existing_taxonomy_by_name(
    connection: Connection,
    *,
    namespace: str,
) -> dict[str, tuple[str, str]]:
    """Find the canonical stored entry for each normalized display name."""

    model = _taxonomy_model(namespace)
    entries: dict[str, tuple[str, str]] = {}
    for slug, name in connection.execute(select(model.slug, model.name)).all():
        key = _taxonomy_name_key(name)
        candidate = (slug, name)
        current = entries.get(key)
        if current is None or _taxonomy_entry_preference(candidate) < _taxonomy_entry_preference(
            current
        ):
            entries[key] = candidate
    return entries


def _normalized_taxonomy_patch(
    connection: Connection,
    values: object,
    *,
    namespace: str,
) -> list[dict[str, str]]:
    if not isinstance(values, list):
        raise ReviewPolicyError(f"{namespace} taxonomy must be a list")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    existing_by_name = _existing_taxonomy_by_name(connection, namespace=namespace)
    for raw_value in values:
        value = _mapping(raw_value)
        name = _optional_text(value.get("name"), maximum=255)
        slug = _optional_text(value.get("slug"), maximum=100)
        if name is None:
            raise ReviewPolicyError(f"{namespace} taxonomy entries require a name")
        if slug is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            raise ReviewPolicyError(f"{namespace} taxonomy slug is invalid")
        canonical = existing_by_name.get(_taxonomy_name_key(name))
        if canonical is not None:
            slug, name = canonical
        elif slug is None:
            slug = _manual_taxonomy_slug(namespace=namespace, name=name)
        if slug not in seen:
            normalized.append({"slug": slug, "name": name})
            seen.add(slug)
    return normalized


def _merge_mapping_patch(
    target: dict[str, Any],
    key: str,
    value: object,
) -> None:
    if value is None:
        target[key] = {}
        return
    if not isinstance(value, Mapping):
        raise ReviewPolicyError(f"{key} patch must be an object")
    merged = dict(_mapping(target.get(key)))
    merged.update(deepcopy(dict(value)))
    target[key] = merged


def _apply_review_record_patch(
    connection: Connection,
    previous_record: Mapping[str, Any],
    patch: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply only the bounded, public-canonical correction surface to a source record."""

    record = _json_object(previous_record, field="review record")
    for field in ("title", "deadline_on", "funding"):
        if field in patch:
            record[field] = deepcopy(patch[field])

    payload = dict(_mapping(record.get("payload")))
    for field in ("summary", "source_published_on", "source_status"):
        if field in patch:
            payload[field] = deepcopy(patch[field])

    for field in ("application", "eligibility"):
        if field in patch:
            _merge_mapping_patch(payload, field, patch[field])

    if "taxonomy" in patch:
        taxonomy_patch = patch["taxonomy"]
        if taxonomy_patch is None:
            payload["taxonomy"] = {"themes": [], "geographies": []}
        elif isinstance(taxonomy_patch, Mapping):
            taxonomy = dict(_mapping(payload.get("taxonomy")))
            for key in ("themes", "geographies"):
                if key in taxonomy_patch:
                    taxonomy[key] = _normalized_taxonomy_patch(
                        connection,
                        taxonomy_patch[key],
                        namespace=key,
                    )
            payload["taxonomy"] = taxonomy
        else:
            raise ReviewPolicyError("taxonomy patch must be an object")

    if "funding_amounts" in patch:
        funding = dict(_mapping(payload.get("funding")))
        raw_amounts = patch["funding_amounts"]
        if raw_amounts is None:
            funding["amounts"] = []
        elif isinstance(raw_amounts, list):
            amounts: list[dict[str, Any]] = []
            for raw_amount in raw_amounts:
                amount = _mapping(raw_amount)
                scope = _funding_scope(amount.get("scope"))
                value = amount.get("value")
                if scope is None or not isinstance(value, Mapping):
                    raise ReviewPolicyError("funding amount must include a valid scope and value")
                try:
                    funding_value = FundingInput.model_validate(value)
                except ValueError as error:
                    raise ReviewPolicyError("funding amount values are invalid") from error
                amounts.append(
                    {
                        "scope": scope.value,
                        "label": _optional_text(amount.get("label"), maximum=500),
                        "value": funding_value.model_dump(mode="json", exclude_none=True),
                        "evidence": _optional_text(amount.get("evidence"), maximum=2_000),
                    }
                )
            funding["amounts"] = amounts
        else:
            raise ReviewPolicyError("funding_amounts patch must be a list")
        payload["funding"] = funding

    if "timeline" in patch:
        raw_timeline = patch["timeline"]
        if raw_timeline is None:
            payload["timeline"] = []
        elif isinstance(raw_timeline, list):
            events: list[dict[str, Any]] = []
            for raw_event in raw_timeline:
                event = _mapping(raw_event)
                label = _optional_text(event.get("label"), maximum=500)
                start_on = _optional_date(event.get("start_on"))
                end_on = _optional_date(event.get("end_on"))
                if label is None or (start_on is None and end_on is None):
                    raise ReviewPolicyError("timeline events require a label and at least one date")
                if start_on is not None and end_on is not None and start_on > end_on:
                    raise ReviewPolicyError("timeline event dates are out of order")
                events.append(
                    {
                        "kind": _timeline_kind(event.get("kind")).value,
                        "label": label,
                        "start_on": start_on.isoformat() if start_on is not None else None,
                        "end_on": end_on.isoformat() if end_on is not None else None,
                        "evidence": _optional_text(event.get("evidence"), maximum=2_000),
                    }
                )
            payload["timeline"] = events
        else:
            raise ReviewPolicyError("timeline patch must be a list")

    if "resources" in patch:
        raw_resources = patch["resources"]
        if raw_resources is None:
            payload["artifacts"] = []
        elif isinstance(raw_resources, list):
            resources: list[dict[str, Any]] = []
            for raw_resource in raw_resources:
                resource = _mapping(raw_resource)
                resource_url = _optional_http_url(resource.get("url"))
                kind = _optional_text(resource.get("kind"), maximum=32)
                if resource_url is None or kind is None:
                    raise ReviewPolicyError("resources require a valid URL and kind")
                resources.append(
                    {
                        "kind": kind,
                        "url": resource_url,
                        "label": _optional_text(resource.get("label"), maximum=500),
                        "section_title": _optional_text(resource.get("section_title"), maximum=500),
                        "section_category": _optional_text(
                            resource.get("section_category"),
                            maximum=64,
                        ),
                        "capture": {
                            "content_format": _optional_text(
                                resource.get("content_format"),
                                maximum=100,
                            )
                        },
                    }
                )
            payload["artifacts"] = resources
        else:
            raise ReviewPolicyError("resources patch must be a list")

    if "content_blocks" in patch:
        raw_blocks = patch["content_blocks"]
        if raw_blocks is None:
            blocks: list[dict[str, Any]] = []
        elif isinstance(raw_blocks, list):
            blocks = []
            for raw_block in raw_blocks:
                block = _mapping(raw_block)
                heading = _optional_text(block.get("heading"), maximum=500)
                category = _optional_text(block.get("category"), maximum=64)
                content = _optional_text(block.get("text"))
                if heading is None or category is None or content is None:
                    raise ReviewPolicyError("content blocks require heading, category, and text")
                blocks.append(
                    {
                        "heading": heading,
                        "category": category,
                        "text": content,
                        "links": [],
                    }
                )
        else:
            raise ReviewPolicyError("content_blocks patch must be a list")
        inventory = dict(_mapping(payload.get("content_inventory")))
        inventory["blocks"] = blocks
        inventory["unclassified_block_count"] = sum(
            block["category"] == "unclassified" for block in blocks
        )
        payload["content_inventory"] = inventory
        payload["sections"] = {block["heading"]: block["text"] for block in blocks}

    application = _mapping(payload.get("application"))
    start_on = _optional_date(application.get("start_on"))
    end_on = _optional_date(application.get("end_on"))
    if start_on is not None and end_on is not None and start_on > end_on:
        raise ReviewPolicyError("application dates are out of order")
    if "application" in patch and isinstance(patch["application"], Mapping):
        application_patch = patch["application"]
        if "end_on" in application_patch and "deadline_on" not in patch:
            record["deadline_on"] = application.get("end_on")

    record["payload"] = payload
    return record


def _deduplication_snapshot(
    connection: Connection,
    candidate: StagedCandidate,
) -> dict[str, Any]:
    observations = _find_matches(connection, candidate)
    return {
        "match_count": len(observations),
        "matches": [
            {
                "target_staged_record_id": str(observation.target_staged_record_id)
                if observation.target_staged_record_id is not None
                else None,
                "target_program_id": str(observation.target_program_id)
                if observation.target_program_id is not None
                else None,
                "match_level": observation.level.value,
                "conflicting_fields": list(observation.conflicts),
            }
            for observation in observations
        ],
    }


def save_review_revision(
    connection: Connection,
    review_case_id: UUID,
    *,
    patch: Mapping[str, Any],
    resolved_issue_ids: Sequence[UUID],
    reason: str,
    actor: str,
) -> ReviewRevisionResult:
    """Save an operator correction without mutating the staged source record."""

    with connection.begin_nested():
        case_status, candidate = _lock_review_case(connection, review_case_id)
        normalized_reason = _nonblank(reason, field="reason")
        normalized_actor = _nonblank(actor, field="actor")
        previous_record = review_effective_record(
            connection,
            review_case_id,
            candidate=candidate,
        )
        effective_record = _apply_review_record_patch(connection, previous_record, patch)
        changed_fields = tuple(_changed_record_paths(previous_record, effective_record))
        requested_issue_ids = tuple(dict.fromkeys(resolved_issue_ids))
        if not changed_fields and not requested_issue_ids:
            raise ReviewPolicyError("a correction must change a field or resolve a quality issue")

        if requested_issue_ids:
            issue_rows = connection.execute(
                select(
                    DataQualityIssue.id,
                    ReviewIssueResolution.id.label("resolution_id"),
                )
                .outerjoin(
                    ReviewIssueResolution,
                    ReviewIssueResolution.data_quality_issue_id == DataQualityIssue.id,
                )
                .where(
                    DataQualityIssue.staged_record_id == candidate.id,
                    DataQualityIssue.id.in_(requested_issue_ids),
                )
            ).mappings().all()
            found_ids = {row["id"] for row in issue_rows}
            if found_ids != set(requested_issue_ids):
                raise ReviewPolicyError("quality issues must belong to this review case")
            if any(row["resolution_id"] is not None for row in issue_rows):
                raise ReviewPolicyError("a selected quality issue is already resolved")

        now = _now()
        revision_number = (
            connection.scalar(
                select(func.coalesce(func.max(ReviewRevision.revision_number), 0) + 1).where(
                    ReviewRevision.review_case_id == review_case_id
                )
            )
            or 1
        )
        revision_id = uuid4()
        revised_candidate = _candidate_with_record(candidate, effective_record)
        deduplication_snapshot = _deduplication_snapshot(connection, revised_candidate)
        connection.execute(
            insert(ReviewRevision).values(
                id=revision_id,
                review_case_id=review_case_id,
                staged_record_id=candidate.id,
                revision_number=revision_number,
                effective_record=effective_record,
                changed_fields=list(changed_fields),
                deduplication_snapshot=deduplication_snapshot,
                reason=normalized_reason,
                actor=normalized_actor,
                created_at=now,
            )
        )
        for issue_id in requested_issue_ids:
            connection.execute(
                insert(ReviewIssueResolution).values(
                    id=uuid4(),
                    review_revision_id=revision_id,
                    data_quality_issue_id=issue_id,
                    reason=normalized_reason,
                    actor=normalized_actor,
                    created_at=now,
                )
            )
        if case_status is ReviewCaseStatus.NEEDS_CLARIFICATION:
            _set_case_status(
                connection,
                review_case_id=review_case_id,
                status=ReviewCaseStatus.OPEN,
                now=now,
            )
        else:
            connection.execute(
                update(ReviewCase)
                .where(ReviewCase.id == review_case_id)
                .values(updated_at=now)
            )
        return ReviewRevisionResult(
            review_case_id=review_case_id,
            staged_record_id=candidate.id,
            review_revision_id=revision_id,
            revision_number=revision_number,
            changed_fields=changed_fields,
            resolved_issue_ids=requested_issue_ids,
        )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: object, *, maximum: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:maximum] if maximum is not None else normalized


def _optional_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _optional_http_url(value: object) -> str | None:
    normalized = _optional_text(value, maximum=2_048)
    if normalized is None:
        return None
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return normalized


def _source_status(value: object) -> ProgramSourceStatus:
    try:
        return ProgramSourceStatus(value) if isinstance(value, str) else ProgramSourceStatus.UNKNOWN
    except ValueError:
        return ProgramSourceStatus.UNKNOWN


def _access_mode(value: object) -> ProgramAccessMode:
    try:
        return ProgramAccessMode(value) if isinstance(value, str) else ProgramAccessMode.UNKNOWN
    except ValueError:
        return ProgramAccessMode.UNKNOWN


def _timeline_kind(value: object) -> ProgramTimelineEventKind:
    try:
        return ProgramTimelineEventKind(value) if isinstance(value, str) else ProgramTimelineEventKind.OTHER
    except ValueError:
        return ProgramTimelineEventKind.OTHER


def _funding_scope(value: object) -> ProgramFundingScope | None:
    try:
        return ProgramFundingScope(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _resource_kind(value: object, section: str | None) -> ProgramResourceKind | None:
    if value == "application":
        return ProgramResourceKind.APPLICATION
    if value == "result":
        return ProgramResourceKind.RESULT
    if value == "detail":
        return ProgramResourceKind.DETAIL
    if value == "document":
        if section is not None and "программ" in section.casefold():
            return ProgramResourceKind.PROGRAM_DOCUMENT
        return ProgramResourceKind.COMPETITION_DOCUMENT
    if value == "reference":
        return ProgramResourceKind.REFERENCE
    return None


def _artifact_winner_group_keys(raw_resources: object) -> frozenset[str]:
    if not isinstance(raw_resources, list):
        return frozenset()
    keys: set[str] = set()
    for raw_resource in raw_resources:
        resource = _mapping(raw_resource)
        title = _optional_text(resource.get("label"), maximum=500)
        group_key = winner_resource_group_key(title)
        if group_key is None:
            continue
        if is_winner_resource(
            title=title,
            source_section=_optional_text(resource.get("section_title"), maximum=500),
            url=_optional_http_url(resource.get("url")),
        ):
            keys.add(group_key)
    return frozenset(keys)


def _insert_program_details(
    connection: Connection,
    *,
    program_id: UUID,
    payload: Mapping[str, Any],
    now: datetime,
) -> Mapping[str, Any]:
    application = _mapping(payload.get("application"))
    eligibility = _mapping(payload.get("eligibility"))
    source_last_modified_at = _optional_text(payload.get("source_last_modified_at"), maximum=100)
    source_title = _optional_text(payload.get("source_title"), maximum=500)
    content_inventory = _mapping(payload.get("content_inventory"))
    blocks = content_inventory.get("blocks")
    source_metadata: dict[str, Any] = {}
    if source_last_modified_at is not None:
        source_metadata["source_last_modified_at"] = source_last_modified_at
    if source_title is not None:
        source_metadata["source_title"] = source_title
    if isinstance(blocks, list):
        source_metadata["content_block_count"] = len(blocks)
    connection.execute(
        insert(ProgramDetails).values(
            program_id=program_id,
            summary=_optional_text(payload.get("summary")),
            eligibility_summary=_optional_text(eligibility.get("summary")),
            eligibility_geography_note=_optional_text(eligibility.get("geography_note")),
            source_published_on=_optional_date(payload.get("source_published_on")),
            source_status=_source_status(payload.get("source_status")),
            access_mode=_access_mode(eligibility.get("access_mode")),
            application_url=_optional_http_url(application.get("url")),
            application_start_on=_optional_date(application.get("start_on")),
            application_end_on=_optional_date(application.get("end_on")),
            source_metadata=source_metadata,
            updated_at=now,
        )
    )
    return application


def _insert_timeline_events(
    connection: Connection,
    *,
    program_id: UUID,
    payload: Mapping[str, Any],
    application: Mapping[str, Any],
) -> None:
    raw_events = payload.get("timeline")
    position = 0
    seen: set[tuple[str, date | None, date | None]] = set()
    if isinstance(raw_events, list):
        for raw_event in raw_events:
            event = _mapping(raw_event)
            label = _optional_text(event.get("label"), maximum=500)
            start_on = _optional_date(event.get("start_on"))
            end_on = _optional_date(event.get("end_on"))
            if label is None or (start_on is None and end_on is None):
                continue
            if start_on is not None and end_on is not None and start_on > end_on:
                continue
            key = (label.casefold(), start_on, end_on)
            if key in seen:
                continue
            seen.add(key)
            connection.execute(
                insert(ProgramTimelineEvent).values(
                    id=uuid4(),
                    program_id=program_id,
                    event_kind=_timeline_kind(event.get("kind")),
                    label=label,
                    start_on=start_on,
                    end_on=end_on,
                    evidence=_optional_text(event.get("evidence"), maximum=2_000),
                    position=position,
                )
            )
            position += 1
    if position:
        return
    start_on = _optional_date(application.get("start_on"))
    end_on = _optional_date(application.get("end_on"))
    if start_on is None and end_on is None:
        return
    connection.execute(
        insert(ProgramTimelineEvent).values(
            id=uuid4(),
            program_id=program_id,
            event_kind=ProgramTimelineEventKind.APPLICATION,
            label="Приём заявок",
            start_on=start_on,
            end_on=end_on,
            evidence=None,
            position=0,
        )
    )


def _insert_scoped_funding(
    connection: Connection,
    *,
    program_id: UUID,
    payload: Mapping[str, Any],
    fallback_funding: FundingInput | None,
) -> None:
    funding_payload = _mapping(payload.get("funding"))
    raw_amounts = funding_payload.get("amounts")
    position = 0
    seen: set[tuple[ProgramFundingScope, tuple[tuple[str, object], ...], str | None]] = set()
    if isinstance(raw_amounts, list):
        for raw_amount in raw_amounts:
            amount = _mapping(raw_amount)
            scope = _funding_scope(amount.get("scope"))
            value = amount.get("value")
            if scope is None or not isinstance(value, Mapping):
                continue
            try:
                funding = FundingInput.model_validate(value)
            except ValueError:
                continue
            label = _optional_text(amount.get("label"), maximum=500)
            fingerprint = (
                scope,
                tuple(sorted(funding.model_dump(mode="json", exclude_none=True).items())),
                label,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            connection.execute(
                insert(ProgramFundingAmount).values(
                    id=uuid4(),
                    program_id=program_id,
                    scope=scope,
                    label=label,
                    **funding.model_dump(),
                    evidence=_optional_text(amount.get("evidence"), maximum=2_000),
                    position=position,
                )
            )
            position += 1
    if position or fallback_funding is None:
        return
    connection.execute(
        insert(ProgramFundingAmount).values(
            id=uuid4(),
            program_id=program_id,
            scope=ProgramFundingScope.PER_PROGRAM,
            label="Финансирование программы",
            **fallback_funding.model_dump(),
            evidence=None,
            position=0,
        )
    )


def _taxonomy_entries(payload: Mapping[str, Any], key: str) -> list[tuple[str, str]]:
    taxonomy = _mapping(payload.get("taxonomy"))
    raw_values = taxonomy.get(key)
    entries: list[tuple[str, str]] = []
    if not isinstance(raw_values, list):
        return entries
    for raw_value in raw_values:
        value = _mapping(raw_value)
        slug = _optional_text(value.get("slug"), maximum=100)
        name = _optional_text(value.get("name"), maximum=255)
        if slug is None or name is None or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            continue
        entry = (slug, name)
        if entry not in entries:
            entries.append(entry)
    return entries


def _canonical_taxonomy_entries(
    connection: Connection,
    *,
    namespace: str,
    entries: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Resolve matching source labels to the one public taxonomy entry."""

    existing_by_name = _existing_taxonomy_by_name(connection, namespace=namespace)
    selected_by_name: dict[str, tuple[str, str]] = {}
    for entry in entries:
        key = _taxonomy_name_key(entry[1])
        current = selected_by_name.get(key)
        if current is None or _taxonomy_entry_preference(entry) < _taxonomy_entry_preference(
            current
        ):
            selected_by_name[key] = entry

    canonical: list[tuple[str, str]] = []
    seen_slugs: set[str] = set()
    for key, entry in selected_by_name.items():
        resolved = existing_by_name.get(key, entry)
        if resolved[0] not in seen_slugs:
            canonical.append(resolved)
            seen_slugs.add(resolved[0])
    return canonical


def _taxonomy_id_by_name(
    connection: Connection,
    *,
    namespace: str,
    slug: str,
    name: str,
) -> UUID | None:
    """Resolve a row after an insert race or a normalized-name conflict."""

    model = _taxonomy_model(namespace)
    identifier = connection.scalar(select(model.id).where(model.slug == slug))
    if identifier is not None:
        return identifier
    name_key = _taxonomy_name_key(name)
    for identifier, stored_name in connection.execute(select(model.id, model.name)).all():
        if _taxonomy_name_key(stored_name) == name_key:
            return identifier
    return None


def _link_taxonomy(
    connection: Connection,
    *,
    program_id: UUID,
    payload: Mapping[str, Any],
) -> None:
    for slug, name in _canonical_taxonomy_entries(
        connection,
        namespace="themes",
        entries=_taxonomy_entries(payload, "themes"),
    ):
        connection.execute(
            postgresql_insert(Theme)
            .values(id=uuid4(), slug=slug, name=name)
            .on_conflict_do_nothing()
        )
        theme_id = _taxonomy_id_by_name(
            connection,
            namespace="themes",
            slug=slug,
            name=name,
        )
        if theme_id is not None:
            connection.execute(
                postgresql_insert(ProgramTheme)
                .values(program_id=program_id, theme_id=theme_id)
                .on_conflict_do_nothing(index_elements=("program_id", "theme_id"))
            )
    for slug, name in _canonical_taxonomy_entries(
        connection,
        namespace="geographies",
        entries=_taxonomy_entries(payload, "geographies"),
    ):
        connection.execute(
            postgresql_insert(Geography)
            .values(id=uuid4(), slug=slug, name=name)
            .on_conflict_do_nothing()
        )
        geography_id = _taxonomy_id_by_name(
            connection,
            namespace="geographies",
            slug=slug,
            name=name,
        )
        if geography_id is not None:
            connection.execute(
                postgresql_insert(ProgramGeography)
                .values(program_id=program_id, geography_id=geography_id)
                .on_conflict_do_nothing(index_elements=("program_id", "geography_id"))
            )


def _insert_resources(
    connection: Connection,
    *,
    program_id: UUID,
    payload: Mapping[str, Any],
    application: Mapping[str, Any],
) -> None:
    raw_resources = payload.get("artifacts")
    winner_group_keys = _artifact_winner_group_keys(raw_resources)
    position = 0
    seen_urls: set[str] = set()

    def insert_resource(
        *,
        raw_kind: object,
        url: object,
        title: object,
        section: object,
        content_format: object,
        section_category: object = None,
    ) -> None:
        nonlocal position
        source_section = _optional_text(section, maximum=500)
        resource_kind = _resource_kind(raw_kind, source_section)
        resource_url = _optional_http_url(url)
        if resource_kind is None or resource_url is None or resource_url in seen_urls:
            return
        resource_title = _optional_text(title, maximum=500)
        group_has_winner_evidence = winner_resource_group_key(resource_title) in winner_group_keys
        resource_kind = public_resource_kind(
            resource_kind,
            title=resource_title,
            source_section=source_section,
            url=resource_url,
            group_has_winner_evidence=group_has_winner_evidence,
        )
        if not is_public_resource(
            kind=resource_kind,
            title=resource_title,
            source_section=source_section,
            section_category=_optional_text(section_category, maximum=64),
            url=resource_url,
            group_has_winner_evidence=group_has_winner_evidence,
        ):
            return
        seen_urls.add(resource_url)
        connection.execute(
            insert(ProgramResource).values(
                id=uuid4(),
                program_id=program_id,
                resource_kind=resource_kind,
                title=resource_title,
                url=resource_url,
                source_section=source_section,
                content_format=_optional_text(content_format, maximum=100),
                position=position,
            )
        )
        position += 1

    if isinstance(raw_resources, list):
        for raw_resource in raw_resources:
            resource = _mapping(raw_resource)
            capture = _mapping(resource.get("capture"))
            insert_resource(
                raw_kind=resource.get("kind"),
                url=resource.get("url"),
                title=resource.get("label"),
                section=resource.get("section_title"),
                content_format=capture.get("content_format"),
                section_category=resource.get("section_category"),
            )
    insert_resource(
        raw_kind="application",
        url=application.get("url"),
        title="Подать заявку",
        section="Подача заявки",
        content_format=None,
        section_category="application",
    )


_CONTACT_TEXT_PATTERN = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}|(?:\+?\d[\d()\s-]{6,}\d)",
    re.UNICODE,
)


def _insert_content_sections(
    connection: Connection,
    *,
    program_id: UUID,
    payload: Mapping[str, Any],
) -> None:
    content_inventory = _mapping(payload.get("content_inventory"))
    raw_blocks = content_inventory.get("blocks")
    if not isinstance(raw_blocks, list):
        return
    position = 0
    for raw_block in raw_blocks:
        block = _mapping(raw_block)
        category = _optional_text(block.get("category"), maximum=64)
        heading = _optional_text(block.get("heading"), maximum=500)
        content = _optional_text(block.get("text"))
        if (
            category is None
            or heading is None
            or content is None
            or _CONTACT_TEXT_PATTERN.search(content)
            or not is_public_content_section(
                category=category,
                heading=heading,
                content=content,
            )
        ):
            continue
        connection.execute(
            insert(ProgramContentSection).values(
                id=uuid4(),
                program_id=program_id,
                heading=heading,
                category=category,
                content=content,
                is_public=True,
                position=position,
            )
        )
        position += 1


def _insert_private_contacts(
    connection: Connection,
    *,
    program_id: UUID,
    payload: Mapping[str, Any],
) -> None:
    raw_contacts = payload.get("contacts")
    if not isinstance(raw_contacts, list):
        return
    position = 0
    for raw_contact in raw_contacts:
        contact = _mapping(raw_contact)
        name = _optional_text(contact.get("name"), maximum=255)
        if name is None:
            continue
        connection.execute(
            insert(ProgramContact).values(
                id=uuid4(),
                program_id=program_id,
                name=name,
                role=_optional_text(contact.get("role"), maximum=255),
                email=_optional_text(contact.get("email"), maximum=320),
                phone=_optional_text(contact.get("phone"), maximum=64),
                source_evidence=_optional_text(contact.get("evidence"), maximum=2_000),
                position=position,
                is_public=False,
            )
        )
        position += 1


def _preview_funding(value: object) -> FundingInput | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return FundingInput.model_validate(value)
    except ValueError:
        return None


def _preview_timeline(
    payload: Mapping[str, Any],
    application: Mapping[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, date | None, date | None]] = set()
    raw_events = payload.get("timeline")
    if isinstance(raw_events, list):
        for raw_event in raw_events:
            event = _mapping(raw_event)
            label = _optional_text(event.get("label"), maximum=500)
            start_on = _optional_date(event.get("start_on"))
            end_on = _optional_date(event.get("end_on"))
            if label is None or (start_on is None and end_on is None):
                continue
            if start_on is not None and end_on is not None and start_on > end_on:
                continue
            key = (label.casefold(), start_on, end_on)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "kind": _timeline_kind(event.get("kind")).value,
                    "label": label,
                    "start_on": start_on,
                    "end_on": end_on,
                }
            )
    if events:
        return events
    start_on = _optional_date(application.get("start_on"))
    end_on = _optional_date(application.get("end_on"))
    if start_on is None and end_on is None:
        return []
    return [
        {
            "kind": ProgramTimelineEventKind.APPLICATION.value,
            "label": "Приём заявок",
            "start_on": start_on,
            "end_on": end_on,
        }
    ]


def _preview_funding_amounts(
    payload: Mapping[str, Any],
    fallback_funding: FundingInput | None,
) -> list[dict[str, Any]]:
    funding_payload = _mapping(payload.get("funding"))
    raw_amounts = funding_payload.get("amounts")
    amounts: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[tuple[str, object], ...], str | None]] = set()
    if isinstance(raw_amounts, list):
        for raw_amount in raw_amounts:
            amount = _mapping(raw_amount)
            scope = _funding_scope(amount.get("scope"))
            value = _preview_funding(amount.get("value"))
            if scope is None or value is None:
                continue
            label = _optional_text(amount.get("label"), maximum=500)
            fingerprint = (
                scope.value,
                tuple(sorted(value.model_dump(mode="json", exclude_none=True).items())),
                label,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            amounts.append(
                {
                    "scope": scope.value,
                    "label": label,
                    **value.model_dump(mode="json"),
                }
            )
    if amounts or fallback_funding is None:
        return amounts
    return [
        {
            "scope": ProgramFundingScope.PER_PROGRAM.value,
            "label": "Финансирование программы",
            **fallback_funding.model_dump(mode="json"),
        }
    ]


def _preview_resources(
    payload: Mapping[str, Any],
    application: Mapping[str, Any],
) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    raw_resources = payload.get("artifacts")
    winner_group_keys = _artifact_winner_group_keys(raw_resources)

    def append_resource(
        *,
        raw_kind: object,
        url: object,
        title: object,
        section: object,
        content_format: object,
        section_category: object = None,
    ) -> None:
        resource_kind = _resource_kind(raw_kind, _optional_text(section, maximum=500))
        resource_url = _optional_http_url(url)
        resource_title = _optional_text(title, maximum=500)
        source_section = _optional_text(section, maximum=500)
        if resource_kind is None or resource_url is None or resource_url in seen_urls:
            return
        group_has_winner_evidence = winner_resource_group_key(resource_title) in winner_group_keys
        resource_kind = public_resource_kind(
            resource_kind,
            title=resource_title,
            source_section=source_section,
            url=resource_url,
            group_has_winner_evidence=group_has_winner_evidence,
        )
        if not is_public_resource(
            kind=resource_kind,
            title=resource_title,
            source_section=source_section,
            section_category=_optional_text(section_category, maximum=64),
            url=resource_url,
            group_has_winner_evidence=group_has_winner_evidence,
        ):
            return
        seen_urls.add(resource_url)
        resources.append(
            {
                "kind": resource_kind.value,
                "title": resource_title,
                "url": resource_url,
                "source_section": source_section,
            }
        )

    if isinstance(raw_resources, list):
        for raw_resource in raw_resources:
            resource = _mapping(raw_resource)
            capture = _mapping(resource.get("capture"))
            append_resource(
                raw_kind=resource.get("kind"),
                url=resource.get("url"),
                title=resource.get("label"),
                section=resource.get("section_title"),
                content_format=capture.get("content_format"),
                section_category=resource.get("section_category"),
            )
    append_resource(
        raw_kind="application",
        url=application.get("url"),
        title="Подать заявку",
        section="Подача заявки",
        content_format=None,
        section_category="application",
    )
    return resources


def _preview_content_sections(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    inventory = _mapping(payload.get("content_inventory"))
    raw_blocks = inventory.get("blocks")
    if not isinstance(raw_blocks, list):
        return []
    sections: list[dict[str, str]] = []
    for raw_block in raw_blocks:
        block = _mapping(raw_block)
        category = _optional_text(block.get("category"), maximum=64)
        heading = _optional_text(block.get("heading"), maximum=500)
        content = _optional_text(block.get("text"))
        if (
            category is None
            or heading is None
            or content is None
            or _CONTACT_TEXT_PATTERN.search(content)
            or not is_public_content_section(category=category, heading=heading, content=content)
        ):
            continue
        sections.append({"heading": heading, "category": category, "content": content})
    return sections


def review_public_preview(
    connection: Connection,
    review_case_id: UUID,
) -> dict[str, Any]:
    """Project the current effective record through the same public acceptance rules."""

    row = connection.execute(
        select(ReviewCase.staged_record_id)
        .where(ReviewCase.id == review_case_id)
    ).one_or_none()
    if row is None:
        raise ReviewPolicyError(f"unknown review case: {review_case_id}")
    candidate = _load_staged_candidate(connection, row.staged_record_id)
    record = review_effective_record(connection, review_case_id, candidate=candidate)
    effective_candidate = _candidate_with_record(candidate, record)
    payload = _mapping(record.get("payload"))
    application = _mapping(payload.get("application"))
    eligibility = _mapping(payload.get("eligibility"))
    source_url = effective_candidate.fingerprint.source_url
    if source_url is None:
        raise ReviewPolicyError("review preview requires a valid canonical source URL")
    source = connection.execute(
        select(Source.id, Source.name, Source.canonical_url).where(Source.id == candidate.source_id)
    ).mappings().one_or_none()
    if source is None:
        raise ReviewPolicyError("review preview source is missing")

    raw_title = _optional_text(record.get("title"), maximum=500)
    title = public_program_title(raw_title or "Кандидат без названия", source_url=source_url)
    funding = _preview_funding(record.get("funding"))
    content_sections = _preview_content_sections(payload)
    access_mode = resolved_access_mode(
        _access_mode(eligibility.get("access_mode")),
        (
            _optional_text(payload.get("summary")),
            _optional_text(eligibility.get("summary")),
            _optional_text(eligibility.get("geography_note")),
            *(section["content"] for section in content_sections),
        ),
    )
    geographies = [
        {"slug": slug, "name": name}
        for slug, name in _taxonomy_entries(payload, "geographies")
    ]
    if not geographies and has_russia_scope(
        (
            _optional_text(payload.get("summary")),
            _optional_text(eligibility.get("summary")),
            _optional_text(eligibility.get("geography_note")),
        )
    ):
        geographies = [{"slug": "russia", "name": "Россия"}]
    deadline_on = effective_candidate.fingerprint.deadline_on or _optional_date(
        application.get("end_on")
    )
    return {
        "title": title,
        "source": {
            "id": source["id"],
            "name": source["name"],
            "canonical_url": source["canonical_url"],
        },
        "source_url": source_url,
        "observed_at": candidate.received_at,
        "source_published_on": _optional_date(payload.get("source_published_on")),
        "summary": _optional_text(payload.get("summary")),
        "source_status": _source_status(payload.get("source_status")),
        "deadline_on": deadline_on,
        "funding": funding.model_dump(mode="json") if funding is not None else None,
        "geographies": geographies,
        "themes": [
            {"slug": slug, "name": name}
            for slug, name in _taxonomy_entries(payload, "themes")
        ],
        "eligibility_summary": _optional_text(eligibility.get("summary")),
        "eligibility_geography_note": _optional_text(eligibility.get("geography_note")),
        "access_mode": access_mode,
        "application_url": _optional_http_url(application.get("url")),
        "application_start_on": _optional_date(application.get("start_on")),
        "application_end_on": _optional_date(application.get("end_on")),
        "funding_amounts": _preview_funding_amounts(payload, funding),
        "timeline": _preview_timeline(payload, application),
        "resources": _preview_resources(payload, application),
        "content_sections": content_sections,
    }


def _create_draft_program_from_candidate(
    connection: Connection,
    *,
    candidate: StagedCandidate,
    now: datetime,
) -> UUID:
    if candidate.ingestion_status is not IngestionRunStatus.COMPLETED:
        raise ReviewPolicyError("only candidates from a completed ingestion run can be accepted")
    record = _record_payload(candidate)
    payload = _mapping(record.get("payload"))
    raw_title = record.get("title")
    if not isinstance(raw_title, str) or not raw_title.strip():
        raise ReviewPolicyError("accepted candidates require a title")
    source_url = candidate.fingerprint.source_url
    if source_url is None:
        raise ReviewPolicyError("accepted candidates require a valid canonical source URL")
    title = public_program_title(raw_title, source_url=source_url)

    funding: FundingInput | None = None
    raw_funding = record.get("funding")
    if raw_funding is not None:
        if not isinstance(raw_funding, Mapping):
            raise ReviewPolicyError("candidate funding must be an object")
        try:
            funding = FundingInput.model_validate(raw_funding)
        except ValueError as error:
            raise ReviewPolicyError("candidate funding cannot be published") from error

    program_id = uuid4()
    connection.execute(
        insert(Program).values(
            id=program_id,
            title=title,
            publication_status=PublicationStatus.DRAFT,
            published_at=None,
            publication_review_decision_id=None,
            primary_source_id=candidate.source_id,
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        insert(ProgramSource).values(
            program_id=program_id,
            source_id=candidate.source_id,
            source_url=source_url,
            observed_at=candidate.received_at,
        )
    )
    application = _insert_program_details(
        connection,
        program_id=program_id,
        payload=payload,
        now=now,
    )
    _insert_timeline_events(
        connection,
        program_id=program_id,
        payload=payload,
        application=application,
    )
    deadline_on = candidate.fingerprint.deadline_on or _optional_date(application.get("end_on"))
    if deadline_on is not None:
        connection.execute(
            insert(ProgramDeadline).values(
                program_id=program_id,
                deadline_on=deadline_on,
            )
        )
    if funding is not None:
        connection.execute(
            insert(ProgramFunding).values(
                program_id=program_id,
                **funding.model_dump(),
            )
        )
    _insert_scoped_funding(
        connection,
        program_id=program_id,
        payload=payload,
        fallback_funding=funding,
    )
    _link_taxonomy(connection, program_id=program_id, payload=payload)
    _insert_resources(
        connection,
        program_id=program_id,
        payload=payload,
        application=application,
    )
    _insert_content_sections(connection, program_id=program_id, payload=payload)
    _insert_private_contacts(connection, program_id=program_id, payload=payload)
    return program_id


def accept_review_case(
    connection: Connection,
    review_case_id: UUID,
    *,
    reason: str,
    actor: str = "operator",
) -> ReviewActionResult:
    """Accept a distinct candidate and publish a canonical Program with provenance."""

    with connection.begin_nested():
        status, candidate = _lock_review_case(connection, review_case_id)
        effective_record = review_effective_record(
            connection,
            review_case_id,
            candidate=candidate,
        )
        candidate = _candidate_with_record(candidate, effective_record)
        if _unresolved_quality_summary(connection, candidate.id).blocks_publication:
            raise ReviewPolicyError("quality errors must be resolved before acceptance")
        now = _now()
        decision_id = uuid4()
        connection.execute(
            insert(ReviewDecision).values(
                id=decision_id,
                staged_record_id=candidate.id,
                decision=ReviewDecisionOutcome.PUBLISH,
                reason=_nonblank(reason, field="reason"),
                decided_at=now,
            )
        )
        program_id = _create_draft_program_from_candidate(
            connection,
            candidate=candidate,
            now=now,
        )
        action_id = _insert_review_action(
            connection,
            review_case_id=review_case_id,
            action=ReviewActionType.ACCEPT,
            reason=_nonblank(reason, field="reason"),
            actor=_nonblank(actor, field="actor"),
            review_decision_id=decision_id,
            prior_values=_case_state_snapshot(
                candidate,
                case_status=status,
                staged_state=StagedRecordState.REVIEW,
            ),
            result_values=_case_state_snapshot(
                candidate,
                case_status=ReviewCaseStatus.RESOLVED,
                staged_state=StagedRecordState.PUBLISHED,
                extra={"program_id": str(program_id), "review_decision_id": str(decision_id)},
            ),
            now=now,
        )
        _update_staged_state(
            connection,
            staged_record_id=candidate.id,
            state=StagedRecordState.PUBLISHED,
            now=now,
        )
        connection.execute(
            update(Program)
            .where(Program.id == program_id)
            .values(
                publication_status=PublicationStatus.PUBLISHED,
                published_at=now,
                publication_review_decision_id=decision_id,
                updated_at=now,
            )
        )
        _set_case_status(
            connection,
            review_case_id=review_case_id,
            status=ReviewCaseStatus.RESOLVED,
            now=now,
        )
        return ReviewActionResult(
            review_case_id=review_case_id,
            review_action_id=action_id,
            staged_record_id=candidate.id,
            program_id=program_id,
            review_decision_id=decision_id,
        )


def reject_review_case(
    connection: Connection,
    review_case_id: UUID,
    *,
    reason: str,
    actor: str = "operator",
) -> ReviewActionResult:
    """Reject one candidate while retaining its raw, staging, and decision history."""

    with connection.begin_nested():
        status, candidate = _lock_review_case(connection, review_case_id)
        now = _now()
        decision_id = uuid4()
        normalized_reason = _nonblank(reason, field="reason")
        connection.execute(
            insert(ReviewDecision).values(
                id=decision_id,
                staged_record_id=candidate.id,
                decision=ReviewDecisionOutcome.REJECT,
                reason=normalized_reason,
                decided_at=now,
            )
        )
        action_id = _insert_review_action(
            connection,
            review_case_id=review_case_id,
            action=ReviewActionType.REJECT,
            reason=normalized_reason,
            actor=_nonblank(actor, field="actor"),
            review_decision_id=decision_id,
            prior_values=_case_state_snapshot(
                candidate,
                case_status=status,
                staged_state=StagedRecordState.REVIEW,
            ),
            result_values=_case_state_snapshot(
                candidate,
                case_status=ReviewCaseStatus.RESOLVED,
                staged_state=StagedRecordState.REJECTED,
                extra={"review_decision_id": str(decision_id)},
            ),
            now=now,
        )
        _update_staged_state(
            connection,
            staged_record_id=candidate.id,
            state=StagedRecordState.REJECTED,
            now=now,
        )
        _set_case_status(
            connection,
            review_case_id=review_case_id,
            status=ReviewCaseStatus.RESOLVED,
            now=now,
        )
        return ReviewActionResult(
            review_case_id=review_case_id,
            review_action_id=action_id,
            staged_record_id=candidate.id,
            review_decision_id=decision_id,
        )


def request_clarification(
    connection: Connection,
    review_case_id: UUID,
    *,
    reason: str,
    actor: str = "operator",
) -> ReviewActionResult:
    """Keep a candidate non-public while recording the requested clarification."""

    with connection.begin_nested():
        status, candidate = _lock_review_case(connection, review_case_id)
        if status is ReviewCaseStatus.NEEDS_CLARIFICATION:
            raise ReviewPolicyError("review case already needs clarification")
        now = _now()
        normalized_reason = _nonblank(reason, field="reason")
        action_id = _insert_review_action(
            connection,
            review_case_id=review_case_id,
            action=ReviewActionType.NEEDS_CLARIFICATION,
            reason=normalized_reason,
            actor=_nonblank(actor, field="actor"),
            prior_values=_case_state_snapshot(
                candidate,
                case_status=status,
                staged_state=StagedRecordState.REVIEW,
            ),
            result_values=_case_state_snapshot(
                candidate,
                case_status=ReviewCaseStatus.NEEDS_CLARIFICATION,
                staged_state=StagedRecordState.REVIEW,
            ),
            now=now,
        )
        _set_case_status(
            connection,
            review_case_id=review_case_id,
            status=ReviewCaseStatus.NEEDS_CLARIFICATION,
            now=now,
        )
        return ReviewActionResult(
            review_case_id=review_case_id,
            review_action_id=action_id,
            staged_record_id=candidate.id,
        )


def _load_merge_match(
    connection: Connection,
    *,
    candidate_id: UUID,
    deduplication_match_id: UUID,
) -> tuple[UUID | None, UUID | None]:
    row = connection.execute(
        select(
            DeduplicationMatch.candidate_staged_record_id,
            DeduplicationMatch.target_staged_record_id,
            DeduplicationMatch.target_program_id,
            DeduplicationMatch.disposition,
        )
        .where(DeduplicationMatch.id == deduplication_match_id)
        .with_for_update()
    ).one_or_none()
    if row is None or row.candidate_staged_record_id != candidate_id:
        raise ReviewPolicyError("merge target does not belong to this review case")
    if row.disposition is not DeduplicationMatchDisposition.REVIEW_REQUIRED:
        raise ReviewPolicyError("only manual-review matches can be merged by an operator")
    if row.target_staged_record_id is not None:
        target_state = connection.scalar(
            select(StagedRecord.state)
            .where(StagedRecord.id == row.target_staged_record_id)
            .with_for_update()
        )
        if target_state is not StagedRecordState.REVIEW:
            raise ReviewPolicyError("a staging merge target must remain review-ready")
    elif row.target_program_id is not None:
        exists = connection.scalar(
            select(Program.id).where(Program.id == row.target_program_id).with_for_update()
        )
        if exists is None:
            raise ReviewPolicyError("the canonical merge target no longer exists")
    else:
        raise ReviewPolicyError("merge target is incomplete")
    return row.target_staged_record_id, row.target_program_id


def merge_review_case(
    connection: Connection,
    review_case_id: UUID,
    *,
    deduplication_match_id: UUID,
    reason: str,
    actor: str = "operator",
) -> ReviewActionResult:
    """Resolve a candidate as a duplicate without deleting either side of the match."""

    with connection.begin_nested():
        status, candidate = _lock_review_case(connection, review_case_id)
        target_staged_record_id, target_program_id = _load_merge_match(
            connection,
            candidate_id=candidate.id,
            deduplication_match_id=deduplication_match_id,
        )
        now = _now()
        normalized_reason = _nonblank(reason, field="reason")
        result_extra = {
            "merged_into_staged_record_id": (
                str(target_staged_record_id) if target_staged_record_id is not None else None
            ),
            "merged_into_program_id": (
                str(target_program_id) if target_program_id is not None else None
            ),
        }
        action_id = _insert_review_action(
            connection,
            review_case_id=review_case_id,
            action=ReviewActionType.MERGE,
            reason=normalized_reason,
            actor=_nonblank(actor, field="actor"),
            deduplication_match_id=deduplication_match_id,
            target_staged_record_id=target_staged_record_id,
            target_program_id=target_program_id,
            prior_values=_case_state_snapshot(
                candidate,
                case_status=status,
                staged_state=StagedRecordState.REVIEW,
            ),
            result_values=_case_state_snapshot(
                candidate,
                case_status=ReviewCaseStatus.RESOLVED,
                staged_state=StagedRecordState.REJECTED,
                extra=result_extra,
            ),
            now=now,
        )
        _update_staged_state(
            connection,
            staged_record_id=candidate.id,
            state=StagedRecordState.REJECTED,
            now=now,
        )
        _set_case_status(
            connection,
            review_case_id=review_case_id,
            status=ReviewCaseStatus.RESOLVED,
            now=now,
        )
        return ReviewActionResult(
            review_case_id=review_case_id,
            review_action_id=action_id,
            staged_record_id=candidate.id,
        )

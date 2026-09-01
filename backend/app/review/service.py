from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
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
    Program,
    ProgramDeadline,
    ProgramFunding,
    ProgramSource,
    PublicationStatus,
    RawCapture,
    ReviewAction,
    ReviewActionType,
    ReviewCase,
    ReviewCaseStatus,
    ReviewDecision,
    ReviewDecisionOutcome,
    StagedRecord,
    StagedRecordState,
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


def _create_draft_program_from_candidate(
    connection: Connection,
    *,
    candidate: StagedCandidate,
    now: datetime,
) -> UUID:
    if candidate.ingestion_status is not IngestionRunStatus.COMPLETED:
        raise ReviewPolicyError("only candidates from a completed ingestion run can be accepted")
    record = _record_payload(candidate)
    raw_title = record.get("title")
    if not isinstance(raw_title, str) or not raw_title.strip():
        raise ReviewPolicyError("accepted candidates require a title")
    source_url = candidate.fingerprint.source_url
    if source_url is None:
        raise ReviewPolicyError("accepted candidates require a valid canonical source URL")

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
            title=raw_title.strip(),
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
    if candidate.fingerprint.deadline_on is not None:
        connection.execute(
            insert(ProgramDeadline).values(
                program_id=program_id,
                deadline_on=candidate.fingerprint.deadline_on,
            )
        )
    if funding is not None:
        connection.execute(
            insert(ProgramFunding).values(
                program_id=program_id,
                **funding.model_dump(),
            )
        )
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
        if candidate.quality.blocks_publication:
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

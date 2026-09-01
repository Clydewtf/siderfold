from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, text, update
from sqlalchemy.engine import Connection

from app.domain.models import (
    OperatorOperation,
    Program,
    ProgramPublicationAction,
    PublicationStatus,
    ReviewCase,
    ReviewCaseStatus,
    ReviewDecision,
    ReviewDecisionOutcome,
)
from app.review.service import ReviewPolicyError


class IdempotencyKeyConflict(ReviewPolicyError):
    """Raised when one idempotency key is reused for a different operation."""


@dataclass(frozen=True)
class OperatorAuditLink:
    review_action_id: UUID | None = None
    discovery_review_action_id: UUID | None = None
    program_publication_action_id: UUID | None = None

    def __post_init__(self) -> None:
        if sum(
            value is not None
            for value in (
                self.review_action_id,
                self.discovery_review_action_id,
                self.program_publication_action_id,
            )
        ) != 1:
            raise ValueError("an operator operation must link to exactly one audit action")


@dataclass(frozen=True)
class OperatorOperationOutcome:
    result_payload: Mapping[str, Any]
    audit_link: OperatorAuditLink


@dataclass(frozen=True)
class OperatorOperationResult:
    operation_id: UUID
    replayed: bool
    result_payload: Mapping[str, Any]
    audit_link: OperatorAuditLink


@dataclass(frozen=True)
class ProgramRepublishResult:
    program_id: UUID
    review_case_id: UUID
    review_decision_id: UUID
    publication_action_id: UUID
    published_at: datetime


@dataclass(frozen=True)
class ProgramArchiveResult:
    program_id: UUID
    review_case_id: UUID
    review_decision_id: UUID
    publication_action_id: UUID
    archived_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _nonblank(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ReviewPolicyError(f"{field} must not be blank")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_fingerprint(
    *,
    action: str,
    target_type: str,
    target_id: UUID,
    request_payload: Mapping[str, Any],
) -> str:
    payload = {
        "action": action,
        "target_id": str(target_id),
        "target_type": target_type,
        "request": request_payload,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _advisory_lock_key(actor: str, idempotency_key: str) -> int:
    digest = sha256(f"{actor}\x00{idempotency_key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def execute_idempotent_operator_operation(
    connection: Connection,
    *,
    actor: str,
    idempotency_key: str,
    action: str,
    target_type: str,
    target_id: UUID,
    request_payload: Mapping[str, Any],
    execute: Callable[[], OperatorOperationOutcome],
) -> OperatorOperationResult:
    """Run one operator action once and retain its stable result for safe retries."""

    actor = _nonblank(actor, field="actor")
    idempotency_key = _nonblank(idempotency_key, field="idempotency_key")
    action = _nonblank(action, field="action")
    target_type = _nonblank(target_type, field="target_type")
    fingerprint = _request_fingerprint(
        action=action,
        target_type=target_type,
        target_id=target_id,
        request_payload=request_payload,
    )

    connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _advisory_lock_key(actor, idempotency_key)},
    )
    existing = connection.execute(
        select(
            OperatorOperation.id,
            OperatorOperation.action,
            OperatorOperation.target_type,
            OperatorOperation.target_id,
            OperatorOperation.request_fingerprint,
            OperatorOperation.result_payload,
            OperatorOperation.review_action_id,
            OperatorOperation.discovery_review_action_id,
            OperatorOperation.program_publication_action_id,
        ).where(
            OperatorOperation.actor == actor,
            OperatorOperation.idempotency_key == idempotency_key,
        )
    ).mappings().one_or_none()
    if existing is not None:
        if (
            existing["action"] != action
            or existing["target_type"] != target_type
            or existing["target_id"] != target_id
            or existing["request_fingerprint"] != fingerprint
        ):
            raise IdempotencyKeyConflict(
                "idempotency key was already used for a different operator operation"
            )
        payload = existing["result_payload"]
        if not isinstance(payload, Mapping):
            raise RuntimeError("stored operator operation result must be an object")
        return OperatorOperationResult(
            operation_id=existing["id"],
            replayed=True,
            result_payload=dict(payload),
            audit_link=OperatorAuditLink(
                review_action_id=existing["review_action_id"],
                discovery_review_action_id=existing["discovery_review_action_id"],
                program_publication_action_id=existing["program_publication_action_id"],
            ),
        )

    outcome = execute()
    operation_id = uuid4()
    result_payload = dict(outcome.result_payload)
    connection.execute(
        insert(OperatorOperation).values(
            id=operation_id,
            actor=actor,
            idempotency_key=idempotency_key,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_fingerprint=fingerprint,
            result_payload=result_payload,
            review_action_id=outcome.audit_link.review_action_id,
            discovery_review_action_id=outcome.audit_link.discovery_review_action_id,
            program_publication_action_id=outcome.audit_link.program_publication_action_id,
        )
    )
    return OperatorOperationResult(
        operation_id=operation_id,
        replayed=False,
        result_payload=result_payload,
        audit_link=outcome.audit_link,
    )


def republish_program(
    connection: Connection,
    program_id: UUID,
    *,
    reason: str,
    actor: str,
) -> ProgramRepublishResult:
    """Restore an archived program using the immutable decision that first published it."""

    normalized_reason = _nonblank(reason, field="reason")
    normalized_actor = _nonblank(actor, field="actor")
    with connection.begin_nested():
        row = connection.execute(
            select(
                Program.id,
                Program.publication_status,
                Program.published_at,
                Program.publication_review_decision_id,
                ReviewDecision.staged_record_id,
                ReviewDecision.decision,
                ReviewCase.id.label("review_case_id"),
                ReviewCase.status.label("review_case_status"),
            )
            .select_from(Program)
            .join(
                ReviewDecision,
                ReviewDecision.id == Program.publication_review_decision_id,
            )
            .join(ReviewCase, ReviewCase.staged_record_id == ReviewDecision.staged_record_id)
            .where(Program.id == program_id)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise ReviewPolicyError("program does not have a publish review history")
        if PublicationStatus(row["publication_status"]) is not PublicationStatus.ARCHIVED:
            raise ReviewPolicyError("only archived programs can be republished")
        if ReviewDecisionOutcome(row["decision"]) is not ReviewDecisionOutcome.PUBLISH:
            raise ReviewPolicyError("program is not backed by a publish decision")
        if ReviewCaseStatus(row["review_case_status"]) is not ReviewCaseStatus.RESOLVED:
            raise ReviewPolicyError("publish review case must be resolved before republishing")

        now = _now()
        publication_action_id = uuid4()
        connection.execute(
            insert(ProgramPublicationAction).values(
                id=publication_action_id,
                program_id=program_id,
                review_case_id=row["review_case_id"],
                publication_review_decision_id=row["publication_review_decision_id"],
                action="republish",
                reason=normalized_reason,
                actor=normalized_actor,
                prior_values={
                    "publication_status": PublicationStatus.ARCHIVED.value,
                    "published_at": row["published_at"].isoformat()
                    if row["published_at"] is not None
                    else None,
                },
                result_values={
                    "publication_status": PublicationStatus.PUBLISHED.value,
                    "published_at": now.isoformat(),
                },
                created_at=now,
            )
        )
        connection.execute(
            update(Program)
            .where(Program.id == program_id)
            .values(
                publication_status=PublicationStatus.PUBLISHED,
                published_at=now,
                updated_at=now,
            )
        )
        return ProgramRepublishResult(
            program_id=program_id,
            review_case_id=row["review_case_id"],
            review_decision_id=row["publication_review_decision_id"],
            publication_action_id=publication_action_id,
            published_at=now,
        )


def archive_program(
    connection: Connection,
    program_id: UUID,
    *,
    reason: str,
    actor: str,
) -> ProgramArchiveResult:
    """Hide a published program while preserving the review evidence that published it."""

    normalized_reason = _nonblank(reason, field="reason")
    normalized_actor = _nonblank(actor, field="actor")
    with connection.begin_nested():
        row = connection.execute(
            select(
                Program.id,
                Program.publication_status,
                Program.published_at,
                Program.publication_review_decision_id,
                ReviewDecision.staged_record_id,
                ReviewDecision.decision,
                ReviewCase.id.label("review_case_id"),
                ReviewCase.status.label("review_case_status"),
            )
            .select_from(Program)
            .join(
                ReviewDecision,
                ReviewDecision.id == Program.publication_review_decision_id,
            )
            .join(ReviewCase, ReviewCase.staged_record_id == ReviewDecision.staged_record_id)
            .where(Program.id == program_id)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise ReviewPolicyError("program does not have a publish review history")
        if PublicationStatus(row["publication_status"]) is not PublicationStatus.PUBLISHED:
            raise ReviewPolicyError("only published programs can be archived")
        if ReviewDecisionOutcome(row["decision"]) is not ReviewDecisionOutcome.PUBLISH:
            raise ReviewPolicyError("program is not backed by a publish decision")
        if ReviewCaseStatus(row["review_case_status"]) is not ReviewCaseStatus.RESOLVED:
            raise ReviewPolicyError("publish review case must be resolved before archiving")

        now = _now()
        publication_action_id = uuid4()
        connection.execute(
            insert(ProgramPublicationAction).values(
                id=publication_action_id,
                program_id=program_id,
                review_case_id=row["review_case_id"],
                publication_review_decision_id=row["publication_review_decision_id"],
                action="archive",
                reason=normalized_reason,
                actor=normalized_actor,
                prior_values={
                    "publication_status": PublicationStatus.PUBLISHED.value,
                    "published_at": row["published_at"].isoformat()
                    if row["published_at"] is not None
                    else None,
                },
                result_values={
                    "publication_status": PublicationStatus.ARCHIVED.value,
                    "published_at": row["published_at"].isoformat()
                    if row["published_at"] is not None
                    else None,
                },
                created_at=now,
            )
        )
        connection.execute(
            update(Program)
            .where(Program.id == program_id)
            .values(
                publication_status=PublicationStatus.ARCHIVED,
                updated_at=now,
            )
        )
        return ProgramArchiveResult(
            program_id=program_id,
            review_case_id=row["review_case_id"],
            review_decision_id=row["publication_review_decision_id"],
            publication_action_id=publication_action_id,
            archived_at=now,
        )

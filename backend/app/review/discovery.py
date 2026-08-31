from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection

from app.domain.models import (
    DiscoveryReviewAction,
    DiscoveryReviewActionType,
    DiscoveryReviewCase,
    ReviewCaseStatus,
    TelegramDiscoveryMessage,
    TelegramDiscoveryRoute,
    TelegramDiscoveryUrl,
)
from app.sources.registry import (
    SourceRegistry,
    SourceRegistryStatus,
    is_url_allowed,
)


class DiscoveryReviewPolicyError(ValueError):
    """Raised when a discovery review action is not valid for its queue item."""


@dataclass(frozen=True)
class DiscoveryReviewQueueItem:
    review_case_id: UUID
    status: ReviewCaseStatus
    subject_type: Literal["message", "url"]
    subject_reference: str
    opened_at: datetime
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryReviewActionResult:
    review_case_id: UUID
    review_action_id: UUID
    status: ReviewCaseStatus
    target_source_key: str | None = None


@dataclass(frozen=True)
class _DiscoveryCase:
    id: UUID
    status: ReviewCaseStatus
    telegram_discovery_message_id: UUID | None
    telegram_discovery_url_id: UUID | None
    opened_snapshot: Mapping[str, object]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _nonblank(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DiscoveryReviewPolicyError(f"{field} must not be blank")
    return normalized


def _get_or_create_case(
    connection: Connection,
    *,
    values: dict[str, object],
    subject_column: str,
    subject_id: UUID,
) -> UUID:
    case_id = connection.scalar(
        postgresql_insert(DiscoveryReviewCase)
        .values(id=uuid4(), **values)
        .on_conflict_do_nothing(index_elements=(subject_column,))
        .returning(DiscoveryReviewCase.id)
    )
    if case_id is not None:
        return case_id

    existing_case_id = connection.scalar(
        select(DiscoveryReviewCase.id).where(
            getattr(DiscoveryReviewCase, subject_column) == subject_id
        )
    )
    if existing_case_id is None:
        raise RuntimeError("discovery review case was not persisted after a unique conflict")
    return existing_case_id


def ensure_discovery_review_case_for_message(
    connection: Connection,
    *,
    telegram_discovery_message_id: UUID,
    message_id: int,
    message_url: str,
    reason_codes: tuple[str, ...],
    opened_at: datetime,
) -> UUID:
    """Queue a message only when it has no reliable external URL to inspect."""

    return _get_or_create_case(
        connection,
        subject_column="telegram_discovery_message_id",
        subject_id=telegram_discovery_message_id,
        values={
            "telegram_discovery_message_id": telegram_discovery_message_id,
            "status": ReviewCaseStatus.OPEN,
            "opened_snapshot": {
                "subject_type": "message",
                "message_id": message_id,
                "message_url": message_url,
                "reason_codes": list(dict.fromkeys(reason_codes)),
            },
            "opened_at": opened_at,
            "updated_at": opened_at,
        },
    )


def ensure_discovery_review_case_for_url(
    connection: Connection,
    *,
    telegram_discovery_url_id: UUID,
    normalized_url: str,
    reason_code: str,
    opened_at: datetime,
) -> UUID:
    """Queue one unknown or ambiguous external URL once, independent of reposts."""

    return _get_or_create_case(
        connection,
        subject_column="telegram_discovery_url_id",
        subject_id=telegram_discovery_url_id,
        values={
            "telegram_discovery_url_id": telegram_discovery_url_id,
            "status": ReviewCaseStatus.OPEN,
            "opened_snapshot": {
                "subject_type": "url",
                "normalized_url": normalized_url,
                "reason_codes": [reason_code],
            },
            "opened_at": opened_at,
            "updated_at": opened_at,
        },
    )


def list_discovery_review_queue(
    connection: Connection,
    *,
    limit: int = 100,
) -> tuple[DiscoveryReviewQueueItem, ...]:
    """Return unresolved source-discovery signals for a future internal interface."""

    if limit < 1 or limit > 1_000:
        raise ValueError("limit must be between 1 and 1000")
    statement = (
        select(
            DiscoveryReviewCase.id,
            DiscoveryReviewCase.status,
            DiscoveryReviewCase.opened_at,
            DiscoveryReviewCase.opened_snapshot,
            DiscoveryReviewCase.telegram_discovery_message_id,
            DiscoveryReviewCase.telegram_discovery_url_id,
            TelegramDiscoveryMessage.message_id,
            TelegramDiscoveryMessage.message_url,
            TelegramDiscoveryUrl.normalized_url,
        )
        .outerjoin(
            TelegramDiscoveryMessage,
            TelegramDiscoveryMessage.id
            == DiscoveryReviewCase.telegram_discovery_message_id,
        )
        .outerjoin(
            TelegramDiscoveryUrl,
            TelegramDiscoveryUrl.id == DiscoveryReviewCase.telegram_discovery_url_id,
        )
        .where(
            DiscoveryReviewCase.status.in_(
                (ReviewCaseStatus.OPEN, ReviewCaseStatus.NEEDS_CLARIFICATION)
            )
        )
        .order_by(DiscoveryReviewCase.opened_at, DiscoveryReviewCase.id)
        .limit(limit)
    )
    items: list[DiscoveryReviewQueueItem] = []
    for row in connection.execute(statement).mappings():
        snapshot = row["opened_snapshot"]
        raw_reasons = snapshot.get("reason_codes", []) if isinstance(snapshot, Mapping) else []
        reasons = tuple(value for value in raw_reasons if isinstance(value, str))
        if row["telegram_discovery_url_id"] is not None:
            subject_type: Literal["message", "url"] = "url"
            subject_reference = row["normalized_url"]
        else:
            subject_type = "message"
            subject_reference = f"{row['message_id']} {row['message_url']}"
        items.append(
            DiscoveryReviewQueueItem(
                review_case_id=row["id"],
                status=ReviewCaseStatus(row["status"]),
                subject_type=subject_type,
                subject_reference=subject_reference,
                opened_at=row["opened_at"],
                reason_codes=reasons,
            )
        )
    return tuple(items)


def _load_case_for_action(
    connection: Connection,
    *,
    review_case_id: UUID,
) -> _DiscoveryCase:
    row = connection.execute(
        select(
            DiscoveryReviewCase.id,
            DiscoveryReviewCase.status,
            DiscoveryReviewCase.telegram_discovery_message_id,
            DiscoveryReviewCase.telegram_discovery_url_id,
            DiscoveryReviewCase.opened_snapshot,
        )
        .where(DiscoveryReviewCase.id == review_case_id)
        .with_for_update()
    ).mappings().one_or_none()
    if row is None:
        raise DiscoveryReviewPolicyError(f"unknown discovery review case: {review_case_id}")
    status = ReviewCaseStatus(row["status"])
    if status is ReviewCaseStatus.RESOLVED:
        raise DiscoveryReviewPolicyError("discovery review case is already resolved")
    snapshot = row["opened_snapshot"]
    if not isinstance(snapshot, Mapping):
        raise DiscoveryReviewPolicyError("discovery review opening snapshot must be an object")
    return _DiscoveryCase(
        id=row["id"],
        status=status,
        telegram_discovery_message_id=row["telegram_discovery_message_id"],
        telegram_discovery_url_id=row["telegram_discovery_url_id"],
        opened_snapshot=snapshot,
    )


def _insert_action(
    connection: Connection,
    *,
    review_case_id: UUID,
    action: DiscoveryReviewActionType,
    reason: str,
    actor: str,
    target_source_key: str | None,
    prior_values: dict[str, object],
    result_values: dict[str, object],
    now: datetime,
) -> UUID:
    action_id = uuid4()
    connection.execute(
        postgresql_insert(DiscoveryReviewAction).values(
            id=action_id,
            discovery_review_case_id=review_case_id,
            action=action,
            reason=reason,
            actor=actor,
            target_source_key=target_source_key,
            prior_values=prior_values,
            result_values=result_values,
            created_at=now,
        )
    )
    return action_id


def _set_case_status(
    connection: Connection,
    *,
    review_case_id: UUID,
    status: ReviewCaseStatus,
    now: datetime,
) -> None:
    connection.execute(
        update(DiscoveryReviewCase)
        .where(DiscoveryReviewCase.id == review_case_id)
        .values(
            status=status,
            resolved_at=now if status is ReviewCaseStatus.RESOLVED else None,
            updated_at=now,
        )
    )


def link_discovery_case_to_registered_source(
    connection: Connection,
    *,
    review_case_id: UUID,
    registry: SourceRegistry,
    source_key: str,
    actor: str,
    reason: str,
) -> DiscoveryReviewActionResult:
    """Resolve a URL case by linking it to an active allowlisted source adapter."""

    actor = _nonblank(actor, field="actor")
    reason = _nonblank(reason, field="reason")
    source_key = _nonblank(source_key, field="source_key")
    case = _load_case_for_action(connection, review_case_id=review_case_id)
    if case.telegram_discovery_url_id is None:
        raise DiscoveryReviewPolicyError("only an external URL can be linked to a source adapter")

    definition = registry.get(source_key)
    if (
        definition.status is not SourceRegistryStatus.ACTIVE
        or definition.adapter_name == "telegram-discovery"
    ):
        raise DiscoveryReviewPolicyError("target source must have an active primary-source adapter")

    url_row = connection.execute(
        select(
            TelegramDiscoveryUrl.normalized_url,
            TelegramDiscoveryUrl.route,
            TelegramDiscoveryUrl.target_source_key,
            TelegramDiscoveryUrl.manual_review_reason,
        )
        .where(TelegramDiscoveryUrl.id == case.telegram_discovery_url_id)
        .with_for_update()
    ).mappings().one_or_none()
    if url_row is None:
        raise DiscoveryReviewPolicyError("discovery URL no longer exists")
    normalized_url = url_row["normalized_url"]
    if not is_url_allowed(normalized_url, definition):
        raise DiscoveryReviewPolicyError(
            "target source allowlist does not permit this discovery URL"
        )

    now = _now()
    prior_values = {
        "route": TelegramDiscoveryRoute(url_row["route"]).value,
        "target_source_key": url_row["target_source_key"],
        "manual_review_reason": url_row["manual_review_reason"],
    }
    result_values = {
        "route": TelegramDiscoveryRoute.SOURCE_ADAPTER.value,
        "target_source_key": source_key,
        "manual_review_reason": None,
    }
    action_id = _insert_action(
        connection,
        review_case_id=case.id,
        action=DiscoveryReviewActionType.LINK_TO_REGISTERED_SOURCE,
        reason=reason,
        actor=actor,
        target_source_key=source_key,
        prior_values=prior_values,
        result_values=result_values,
        now=now,
    )
    connection.execute(
        update(TelegramDiscoveryUrl)
        .where(TelegramDiscoveryUrl.id == case.telegram_discovery_url_id)
        .values(**result_values)
    )
    _set_case_status(
        connection,
        review_case_id=case.id,
        status=ReviewCaseStatus.RESOLVED,
        now=now,
    )
    return DiscoveryReviewActionResult(
        review_case_id=case.id,
        review_action_id=action_id,
        status=ReviewCaseStatus.RESOLVED,
        target_source_key=source_key,
    )


def reject_discovery_case(
    connection: Connection,
    *,
    review_case_id: UUID,
    actor: str,
    reason: str,
) -> DiscoveryReviewActionResult:
    """Resolve a discovery signal as not worth routing to a primary source."""

    actor = _nonblank(actor, field="actor")
    reason = _nonblank(reason, field="reason")
    case = _load_case_for_action(connection, review_case_id=review_case_id)
    now = _now()
    action_id = _insert_action(
        connection,
        review_case_id=case.id,
        action=DiscoveryReviewActionType.REJECT,
        reason=reason,
        actor=actor,
        target_source_key=None,
        prior_values={"status": case.status.value},
        result_values={"status": ReviewCaseStatus.RESOLVED.value},
        now=now,
    )
    _set_case_status(
        connection,
        review_case_id=case.id,
        status=ReviewCaseStatus.RESOLVED,
        now=now,
    )
    return DiscoveryReviewActionResult(
        review_case_id=case.id,
        review_action_id=action_id,
        status=ReviewCaseStatus.RESOLVED,
    )


def request_discovery_clarification(
    connection: Connection,
    *,
    review_case_id: UUID,
    actor: str,
    reason: str,
) -> DiscoveryReviewActionResult:
    """Keep a discovery signal visible while its source needs further verification."""

    actor = _nonblank(actor, field="actor")
    reason = _nonblank(reason, field="reason")
    case = _load_case_for_action(connection, review_case_id=review_case_id)
    if case.status is ReviewCaseStatus.NEEDS_CLARIFICATION:
        raise DiscoveryReviewPolicyError("discovery review case already needs clarification")
    now = _now()
    action_id = _insert_action(
        connection,
        review_case_id=case.id,
        action=DiscoveryReviewActionType.NEEDS_CLARIFICATION,
        reason=reason,
        actor=actor,
        target_source_key=None,
        prior_values={"status": case.status.value},
        result_values={"status": ReviewCaseStatus.NEEDS_CLARIFICATION.value},
        now=now,
    )
    _set_case_status(
        connection,
        review_case_id=case.id,
        status=ReviewCaseStatus.NEEDS_CLARIFICATION,
        now=now,
    )
    return DiscoveryReviewActionResult(
        review_case_id=case.id,
        review_action_id=action_id,
        status=ReviewCaseStatus.NEEDS_CLARIFICATION,
    )

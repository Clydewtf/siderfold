from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from app.sources.registry import normalize_url


_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"}
_UNKNOWN_FUNDING_KINDS = {"unknown", "not_stated"}


def normalize_deduplication_url(value: str) -> str | None:
    """Return a stable comparison form without fragments or tracking query keys."""

    try:
        normalized = normalize_url(value)
    except ValueError:
        return None
    parsed = urlsplit(normalized)
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (
                key,
                item,
            )
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in _TRACKING_QUERY_KEYS
            and not key.casefold().startswith("utm_")
        ),
        doseq=True,
    )
    return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def normalize_text(value: object) -> str | None:
    """Normalize human-readable fields without guessing transliterations or synonyms."""

    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    normalized = re.sub(r"[\W_]+", " ", normalized, flags=re.UNICODE)
    normalized = " ".join(normalized.split())
    return normalized or None


def normalize_external_id(value: object) -> str | None:
    """Normalize a source-scoped external identifier or a URL-shaped record key."""

    if not isinstance(value, str):
        return None
    stripped = unicodedata.normalize("NFKC", value).strip()
    if not stripped:
        return None
    if stripped.casefold().startswith(("http://", "https://")):
        return normalize_deduplication_url(stripped)
    return " ".join(stripped.casefold().split())


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_decimal(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return format(parsed.normalize(), "f")


def _funding_signature(value: object) -> tuple[str, str | None, str | None, str | None, str | None] | None:
    if not isinstance(value, Mapping):
        return None
    kind = value.get("value_kind")
    if not isinstance(kind, str) or kind in _UNKNOWN_FUNDING_KINDS:
        return None
    currency = value.get("currency_code")
    normalized_currency = currency.upper() if isinstance(currency, str) and currency else None
    return (
        kind,
        normalized_currency,
        _normalize_decimal(value.get("exact_amount")),
        _normalize_decimal(value.get("min_amount")),
        _normalize_decimal(value.get("max_amount")),
    )


def _record_mapping(candidate_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    record = candidate_payload.get("record")
    return record if isinstance(record, Mapping) else candidate_payload


def _organizer(record: Mapping[str, Any]) -> object:
    value = record.get("organizer")
    if value is not None:
        return value
    payload = record.get("payload")
    return payload.get("organizer") if isinstance(payload, Mapping) else None


def _external_id(record: Mapping[str, Any], record_key: str) -> object:
    for container in (record, record.get("payload")):
        if isinstance(container, Mapping) and container.get("external_id") is not None:
            return container["external_id"]
    return record_key


def _origin_urls(record: Mapping[str, Any]) -> tuple[str, ...]:
    payload = record.get("payload")
    raw_urls = payload.get("origin_urls") if isinstance(payload, Mapping) else None
    if not isinstance(raw_urls, (list, tuple)):
        return ()
    normalized = {
        candidate
        for value in raw_urls
        if isinstance(value, str)
        and (candidate := normalize_deduplication_url(value)) is not None
    }
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class CandidateFingerprint:
    """Comparison values derived from one staging candidate or canonical program."""

    source_id: UUID
    record_key: str | None
    external_id: str | None
    source_url: str | None
    title: str | None
    organizer: str | None
    deadline_on: date | None
    funding: tuple[str, str | None, str | None, str | None, str | None] | None
    origin_urls: tuple[str, ...] = ()

    def audit_values(self) -> dict[str, Any]:
        return {
            "source_id": str(self.source_id),
            "record_key": self.record_key,
            "external_id": self.external_id,
            "source_url": self.source_url,
            "title": self.title,
            "organizer": self.organizer,
            "deadline_on": self.deadline_on.isoformat() if self.deadline_on else None,
            "funding": list(self.funding) if self.funding is not None else None,
            "origin_urls": list(self.origin_urls),
        }


def staged_fingerprint(
    *,
    source_id: UUID,
    record_key: str,
    candidate_payload: Mapping[str, Any],
) -> CandidateFingerprint:
    record = _record_mapping(candidate_payload)
    source_url = normalize_deduplication_url(record.get("record_url", ""))
    return CandidateFingerprint(
        source_id=source_id,
        record_key=record_key,
        external_id=normalize_external_id(_external_id(record, record_key)),
        source_url=source_url,
        title=normalize_text(record.get("title")),
        organizer=normalize_text(_organizer(record)),
        deadline_on=_parse_date(record.get("deadline_on")),
        funding=_funding_signature(record.get("funding")),
        origin_urls=_origin_urls(record),
    )


def program_fingerprint(
    *,
    source_id: UUID,
    title: str,
    source_url: str,
    deadline_on: date | None,
    funding: Mapping[str, Any] | None,
) -> CandidateFingerprint:
    return CandidateFingerprint(
        source_id=source_id,
        record_key=None,
        external_id=None,
        source_url=normalize_deduplication_url(source_url),
        title=normalize_text(title),
        organizer=None,
        deadline_on=deadline_on,
        funding=_funding_signature(funding),
        origin_urls=(),
    )


def exact_origin_url_match(
    candidate: CandidateFingerprint,
    target: CandidateFingerprint,
) -> str | None:
    """Return an explicitly declared primary URL shared across source identities."""

    if candidate.source_id == target.source_id:
        return None
    candidate_origins = set(candidate.origin_urls)
    target_origins = set(target.origin_urls)
    if target.source_url is not None and target.source_url in candidate_origins:
        return target.source_url
    if candidate.source_url is not None and candidate.source_url in target_origins:
        return candidate.source_url
    return None


def conflicting_fields(
    left: CandidateFingerprint,
    right: CandidateFingerprint,
) -> tuple[str, ...]:
    """List populated canonical fields that disagree after deterministic normalization."""

    comparisons = (
        ("title", left.title, right.title),
        ("organizer", left.organizer, right.organizer),
        ("deadline_on", left.deadline_on, right.deadline_on),
        ("funding", left.funding, right.funding),
    )
    return tuple(
        field
        for field, left_value, right_value in comparisons
        if left_value is not None and right_value is not None and left_value != right_value
    )


def normalized_fields_match(
    left: CandidateFingerprint,
    right: CandidateFingerprint,
) -> bool:
    """Return the conservative manual-review match on title, organizer, and date."""

    return (
        left.title is not None
        and left.organizer is not None
        and left.deadline_on is not None
        and left.title == right.title
        and left.organizer == right.organizer
        and left.deadline_on == right.deadline_on
    )

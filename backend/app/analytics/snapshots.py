from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection

from app.analytics.baseline import BaselineMetricsError, calculate_baseline_metrics
from app.analytics.regional import (
    RegionalIndicatorsError,
    calculate_regional_indicators,
)
from app.domain.models import (
    AnalyticsSnapshot,
    DataQualityIssue,
    DiscoveryReviewCase,
    Geography,
    IngestionRun,
    Program,
    ProgramDeadline,
    ProgramFunding,
    ProgramGeography,
    ProgramSource,
    ProgramTheme,
    PublicationStatus,
    RawCapture,
    ReviewCase,
    ReviewCaseStatus,
    Source,
    SourceExecutionRun,
    SourceExecutionStatus,
    StagedRecord,
    TelegramDiscoveryMessage,
    TelegramDiscoveryMessageUrl,
    Theme,
)
from app.sources.registry import (
    SourceAccessMethod,
    SourceDefinition,
    SourceRegistry,
    SourceRegistryStatus,
    normalize_url,
)


SNAPSHOT_SCOPE = "published_catalog_quality"
CALCULATION_VERSION = "catalog-quality/v3"
INPUT_MANIFEST_V2_VERSION = "catalog-quality-input/v2"
INPUT_MANIFEST_VERSION = "catalog-quality-input/v3"
SUPPORTED_INPUT_MANIFEST_VERSIONS = frozenset(
    {INPUT_MANIFEST_V2_VERSION, INPUT_MANIFEST_VERSION}
)
FRESHNESS_WINDOW_DAYS = 30
FASIE_SOURCE_KEY = "fasie-competitions"
TELEGRAM_SOURCE_KEY = "telegram-cptgrantov-discovery"
PROGRAM_SOURCE_KEYS = frozenset({"potanin-competitions", "timchenko-competitions"})
RESEARCH_SOURCE_KEYS = PROGRAM_SOURCE_KEYS | {TELEGRAM_SOURCE_KEY}

SNAPSHOT_LIMITATIONS = (
    "Метрики отражают только зафиксированный набор подключённых источников и не описывают весь рынок возможностей.",
    "Полнота показывает наличие минимальных полей в опубликованной карточке, а не достоверность каждого внешнего факта.",
    "Давность измеряет возраст наблюдения первоисточника, а не гарантирует отсутствие изменений на его стороне.",
    "Финансовые квантили описывают только числовые записи отдельно по валюте и виду значения; они не корректируют scope выплат или смещение пропусков.",
    "Региональные и тематические индикаторы используют только явные замороженные связи; схема не хранит их уровень, происхождение или конфликтность.",
    "Нормированные доли taxonomy показывают представленность в каталоге платформы, а не долю рынка, населения, спроса или доступности.",
)


class AnalyticsSnapshotError(ValueError):
    """Raised when a quality snapshot cannot be built from a stable input set."""


@dataclass(frozen=True)
class AnalyticsSnapshotRecord:
    id: UUID
    scope: str
    calculation_version: str
    as_of: datetime
    freshness_window_days: int
    registry_fingerprint: str
    input_fingerprint: str
    source_scope: dict[str, Any]
    input_manifest: dict[str, Any]
    metrics: dict[str, Any]
    limitations: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class AnalyticsSnapshotResult:
    snapshot: AnalyticsSnapshotRecord
    created: bool

    def report(self) -> dict[str, Any]:
        return {
            "snapshot_id": str(self.snapshot.id),
            "created": self.created,
            "scope": self.snapshot.scope,
            "calculation_version": self.snapshot.calculation_version,
            "as_of": _timestamp(self.snapshot.as_of),
            "input_fingerprint": self.snapshot.input_fingerprint,
            "registry_fingerprint": self.snapshot.registry_fingerprint,
            "metrics": self.snapshot.metrics,
            "limitations": list(self.snapshot.limitations),
        }


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AnalyticsSnapshotError("snapshot timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def _as_utc(value: datetime | None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise AnalyticsSnapshotError("as_of must include a timezone")
    return resolved.astimezone(timezone.utc)


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_source_url(value: str) -> str | None:
    try:
        return normalize_url(value)
    except ValueError:
        return None


def _registry_scope(
    registry: SourceRegistry,
) -> tuple[dict[str, Any], dict[str, SourceDefinition], dict[str, SourceDefinition]]:
    all_sources: dict[str, SourceDefinition] = {}
    active_real_sources: dict[str, SourceDefinition] = {}
    active_entries: list[dict[str, str]] = []
    excluded_entries: list[dict[str, str]] = []

    for source_key, definition in sorted(registry.sources.items()):
        canonical_url = definition.canonical_url
        if canonical_url in all_sources:
            raise AnalyticsSnapshotError(
                f"multiple registry entries use canonical URL: {canonical_url}"
            )
        all_sources[canonical_url] = definition
        entry = {
            "source_key": source_key,
            "canonical_url": canonical_url,
            "access_method": definition.access_method.value,
            "status": definition.status.value,
            "schedule": definition.schedule,
            "adapter_name": definition.adapter_name,
            "adapter_version": definition.adapter_version,
        }
        if source_key == FASIE_SOURCE_KEY or definition.adapter_name == FASIE_SOURCE_KEY:
            excluded_entries.append({**entry, "reason": "research_protocol_exclusion"})
            continue
        if (
            definition.status is SourceRegistryStatus.ACTIVE
            and definition.access_method is not SourceAccessMethod.FIXTURE
            and source_key in RESEARCH_SOURCE_KEYS
        ):
            active_real_sources[canonical_url] = definition
            active_entries.append(entry)
            continue

        if (
            definition.status is SourceRegistryStatus.ACTIVE
            and definition.access_method is not SourceAccessMethod.FIXTURE
        ):
            excluded_entries.append({**entry, "reason": "research_protocol_exclusion"})
            continue

        reason = (
            "fixture_access"
            if definition.access_method is SourceAccessMethod.FIXTURE
            else "source_not_active"
        )
        excluded_entries.append({**entry, "reason": reason})

    return (
        {
            "registry_version": registry.version,
            "active_real_sources": active_entries,
            "program_sources": [
                entry
                for entry in active_entries
                if entry["source_key"] in PROGRAM_SOURCE_KEYS
            ],
            "excluded_sources": excluded_entries,
        },
        all_sources,
        active_real_sources,
    )


def _source_exclusion_reason(
    canonical_url: str,
    *,
    all_sources: Mapping[str, SourceDefinition],
    active_real_sources: Mapping[str, SourceDefinition],
) -> str | None:
    normalized = _normalized_source_url(canonical_url)
    if normalized is None:
        return "invalid_source_url"
    if normalized in active_real_sources:
        return None
    definition = all_sources.get(normalized)
    if definition is None:
        return "unregistered_source"
    if definition.access_method is SourceAccessMethod.FIXTURE:
        return "fixture_source"
    if (
        definition.source_key == FASIE_SOURCE_KEY
        or definition.adapter_name == FASIE_SOURCE_KEY
    ):
        return "research_protocol_exclusion"
    if definition.status is not SourceRegistryStatus.ACTIVE:
        return "inactive_source"
    if definition.source_key not in RESEARCH_SOURCE_KEYS:
        return "research_protocol_exclusion"
    return "inactive_source"


def _excluded_canonical_urls(
    all_sources: Mapping[str, SourceDefinition],
    *,
    include_telegram_operational: bool = False,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            canonical_url
            for canonical_url, definition in all_sources.items()
            if definition.source_key == FASIE_SOURCE_KEY
            or definition.adapter_name == FASIE_SOURCE_KEY
            or (
                definition.status is SourceRegistryStatus.ACTIVE
                and definition.access_method is not SourceAccessMethod.FIXTURE
                and definition.source_key not in (
                    RESEARCH_SOURCE_KEYS
                    if include_telegram_operational
                    else PROGRAM_SOURCE_KEYS
                )
            )
        )
    )


def _database_data_class(connection: Connection) -> str:
    """Distinguish isolated test databases from operational snapshots."""

    database_name = connection.execute(text("select current_database()")).scalar_one_or_none()
    if not isinstance(database_name, str) or not database_name:
        return "unknown"
    if database_name.endswith("_test"):
        return "test"
    return "real"


def _source_key(canonical_url: str, active_real_sources: Mapping[str, SourceDefinition]) -> str:
    normalized = _normalized_source_url(canonical_url)
    if normalized is None or normalized not in active_real_sources:
        raise AnalyticsSnapshotError("included source is not an active real registry source")
    return active_real_sources[normalized].source_key


def _counter_payload(counter: Counter[str]) -> dict[str, int]:
    return {key: int(counter[key]) for key in sorted(counter)}


def _collect_programs(
    connection: Connection,
    *,
    as_of: datetime,
    all_sources: Mapping[str, SourceDefinition],
    active_real_sources: Mapping[str, SourceDefinition],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    excluded_urls = _excluded_canonical_urls(all_sources)
    statement = (
        select(
            Program.id,
            Program.title,
            Program.publication_status,
            Program.published_at,
            Program.updated_at,
            Source.id.label("source_id"),
            Source.canonical_url.label("source_canonical_url"),
            ProgramSource.source_url,
            ProgramSource.observed_at,
            ProgramDeadline.deadline_on,
            ProgramFunding.value_kind.label("funding_value_kind"),
            ProgramFunding.currency_code.label("funding_currency_code"),
            ProgramFunding.exact_amount.label("funding_exact_amount"),
            ProgramFunding.min_amount.label("funding_min_amount"),
            ProgramFunding.max_amount.label("funding_max_amount"),
        )
        .select_from(Program)
        .join(
            ProgramSource,
            (ProgramSource.program_id == Program.id)
            & (ProgramSource.source_id == Program.primary_source_id),
        )
        .join(Source, Source.id == Program.primary_source_id)
        .outerjoin(ProgramDeadline, ProgramDeadline.program_id == Program.id)
        .outerjoin(ProgramFunding, ProgramFunding.program_id == Program.id)
        .order_by(Program.id)
    )
    if excluded_urls:
        statement = statement.where(Source.canonical_url.not_in(excluded_urls))
    rows = connection.execute(statement).mappings()
    exclusions: Counter[str] = Counter()
    programs: list[dict[str, Any]] = []
    for row in rows:
        if _enum_value(row["publication_status"]) != PublicationStatus.PUBLISHED.value:
            exclusions["not_published"] += 1
            continue
        published_at = row["published_at"]
        updated_at = row["updated_at"]
        observed_at = row["observed_at"]
        if published_at is None or published_at > as_of:
            exclusions["published_after_snapshot"] += 1
            continue
        if updated_at > as_of:
            exclusions["updated_after_snapshot"] += 1
            continue
        source_reason = _source_exclusion_reason(
            row["source_canonical_url"],
            all_sources=all_sources,
            active_real_sources=active_real_sources,
        )
        if source_reason is not None:
            exclusions[source_reason] += 1
            continue
        if observed_at > as_of:
            exclusions["observed_after_snapshot"] += 1
            continue
        programs.append(
            {
                "program_id": str(row["id"]),
                "source_id": str(row["source_id"]),
                "source_key": _source_key(row["source_canonical_url"], active_real_sources),
                "published_at": _timestamp(published_at),
                "updated_at": _timestamp(updated_at),
                "title_present": bool(row["title"].strip()),
                "source_url_present": bool(row["source_url"].strip()),
                "observed_at": _timestamp(observed_at),
                "deadline_on": row["deadline_on"].isoformat() if row["deadline_on"] else None,
                "deadline_present": row["deadline_on"] is not None,
                "funding_present": row["funding_value_kind"] is not None,
                "funding_value_kind": (
                    _enum_value(row["funding_value_kind"])
                    if row["funding_value_kind"] is not None
                    else None
                ),
                "funding_currency_code": row["funding_currency_code"],
                "funding_exact_amount": (
                    format(row["funding_exact_amount"], "f")
                    if row["funding_exact_amount"] is not None
                    else None
                ),
                "funding_min_amount": (
                    format(row["funding_min_amount"], "f")
                    if row["funding_min_amount"] is not None
                    else None
                ),
                "funding_max_amount": (
                    format(row["funding_max_amount"], "f")
                    if row["funding_max_amount"] is not None
                    else None
                ),
            }
        )
    return programs, _counter_payload(exclusions)


def _collect_taxonomy_associations(
    connection: Connection,
    *,
    program_ids: Sequence[str],
) -> dict[str, list[dict[str, str]]]:
    """Freeze explicit taxonomy links for the programs included in this snapshot."""

    if not program_ids:
        return {"geographies": [], "themes": []}
    ids = [UUID(program_id) for program_id in program_ids]
    geographies = [
        {
            "program_id": str(row["program_id"]),
            "taxonomy_id": str(row["geography_id"]),
            "slug": row["slug"],
            "name": row["name"],
        }
        for row in connection.execute(
            select(
                ProgramGeography.program_id,
                Geography.id.label("geography_id"),
                Geography.slug,
                Geography.name,
            )
            .select_from(ProgramGeography)
            .join(Geography, Geography.id == ProgramGeography.geography_id)
            .where(ProgramGeography.program_id.in_(ids))
            .order_by(ProgramGeography.program_id, Geography.slug, Geography.id)
        ).mappings()
    ]
    themes = [
        {
            "program_id": str(row["program_id"]),
            "taxonomy_id": str(row["theme_id"]),
            "slug": row["slug"],
            "name": row["name"],
        }
        for row in connection.execute(
            select(
                ProgramTheme.program_id,
                Theme.id.label("theme_id"),
                Theme.slug,
                Theme.name,
            )
            .select_from(ProgramTheme)
            .join(Theme, Theme.id == ProgramTheme.theme_id)
            .where(ProgramTheme.program_id.in_(ids))
            .order_by(ProgramTheme.program_id, Theme.slug, Theme.id)
        ).mappings()
    ]
    return {"geographies": geographies, "themes": themes}


def _reason_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    raw_codes = value.get("reason_codes", ())
    if not isinstance(raw_codes, Sequence) or isinstance(raw_codes, (str, bytes)):
        return ()
    return tuple(sorted({code for code in raw_codes if isinstance(code, str) and code}))


def _quality_codes_by_staged_record(
    connection: Connection,
    staged_record_ids: Sequence[UUID],
) -> dict[UUID, tuple[str, ...]]:
    if not staged_record_ids:
        return {}
    values: dict[UUID, set[str]] = defaultdict(set)
    for staged_record_id, code in connection.execute(
        select(DataQualityIssue.staged_record_id, DataQualityIssue.code).where(
            DataQualityIssue.staged_record_id.in_(staged_record_ids)
        )
    ):
        values[staged_record_id].add(code)
    return {key: tuple(sorted(codes)) for key, codes in values.items()}


def _collect_canonical_review_cases(
    connection: Connection,
    *,
    as_of: datetime,
    all_sources: Mapping[str, SourceDefinition],
    active_real_sources: Mapping[str, SourceDefinition],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    excluded_urls = _excluded_canonical_urls(all_sources)
    statement = (
        select(
            ReviewCase.id,
            ReviewCase.staged_record_id,
            ReviewCase.status,
            ReviewCase.opened_at,
            ReviewCase.resolved_at,
            ReviewCase.updated_at,
            ReviewCase.opened_snapshot,
            IngestionRun.source_id,
            Source.canonical_url.label("source_canonical_url"),
        )
        .select_from(ReviewCase)
        .join(StagedRecord, StagedRecord.id == ReviewCase.staged_record_id)
        .join(RawCapture, RawCapture.id == StagedRecord.raw_capture_id)
        .join(IngestionRun, IngestionRun.id == RawCapture.ingestion_run_id)
        .join(Source, Source.id == IngestionRun.source_id)
        .where(ReviewCase.opened_at <= as_of)
        .order_by(ReviewCase.id)
    )
    if excluded_urls:
        statement = statement.where(Source.canonical_url.not_in(excluded_urls))
    rows = list(
        connection.execute(statement).mappings()
    )
    quality_codes = _quality_codes_by_staged_record(
        connection,
        [row["staged_record_id"] for row in rows],
    )
    exclusions: Counter[str] = Counter()
    cases: list[dict[str, Any]] = []
    for row in rows:
        if row["updated_at"] > as_of:
            exclusions["updated_after_snapshot"] += 1
            continue
        source_reason = _source_exclusion_reason(
            row["source_canonical_url"],
            all_sources=all_sources,
            active_real_sources=active_real_sources,
        )
        if source_reason is not None:
            exclusions[source_reason] += 1
            continue
        reasons = _reason_codes(row["opened_snapshot"])
        issue_codes = quality_codes.get(row["staged_record_id"], ())
        cases.append(
            {
                "review_case_id": str(row["id"]),
                "case_type": "canonical",
                "source_id": str(row["source_id"]),
                "source_key": _source_key(row["source_canonical_url"], active_real_sources),
                "status": _enum_value(row["status"]),
                "opened_at": _timestamp(row["opened_at"]),
                "resolved_at": (
                    _timestamp(row["resolved_at"])
                    if row["resolved_at"] is not None
                    else None
                ),
                "reason_codes": list(reasons),
                "quality_issue_codes": list(issue_codes),
                "has_explicit_conflict": (
                    "exact_identity_conflict" in reasons
                    or "deduplication_exact_identity_conflict" in issue_codes
                ),
            }
        )
    return cases, _counter_payload(exclusions)


def _discovery_url_sources(
    connection: Connection,
    discovery_url_ids: Sequence[UUID],
) -> dict[UUID, UUID]:
    if not discovery_url_ids:
        return {}
    sources: dict[UUID, UUID] = {}
    rows = connection.execute(
        select(
            TelegramDiscoveryMessageUrl.discovery_url_id,
            TelegramDiscoveryMessage.source_id,
        )
        .select_from(TelegramDiscoveryMessageUrl)
        .join(
            TelegramDiscoveryMessage,
            TelegramDiscoveryMessage.id == TelegramDiscoveryMessageUrl.message_id,
        )
        .where(TelegramDiscoveryMessageUrl.discovery_url_id.in_(discovery_url_ids))
        .order_by(
            TelegramDiscoveryMessageUrl.discovery_url_id,
            TelegramDiscoveryMessage.source_id,
        )
    )
    for discovery_url_id, source_id in rows:
        sources.setdefault(discovery_url_id, source_id)
    return sources


def _source_urls_by_id(connection: Connection, source_ids: Sequence[UUID]) -> dict[UUID, str]:
    if not source_ids:
        return {}
    return {
        source_id: canonical_url
        for source_id, canonical_url in connection.execute(
            select(Source.id, Source.canonical_url).where(Source.id.in_(source_ids))
        )
    }


def _collect_discovery_review_cases(
    connection: Connection,
    *,
    as_of: datetime,
    all_sources: Mapping[str, SourceDefinition],
    active_real_sources: Mapping[str, SourceDefinition],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = list(
        connection.execute(
            select(
                DiscoveryReviewCase.id,
                DiscoveryReviewCase.telegram_discovery_url_id,
                DiscoveryReviewCase.status,
                DiscoveryReviewCase.opened_at,
                DiscoveryReviewCase.resolved_at,
                DiscoveryReviewCase.updated_at,
                DiscoveryReviewCase.opened_snapshot,
                TelegramDiscoveryMessage.source_id.label("message_source_id"),
            )
            .select_from(DiscoveryReviewCase)
            .outerjoin(
                TelegramDiscoveryMessage,
                TelegramDiscoveryMessage.id
                == DiscoveryReviewCase.telegram_discovery_message_id,
            )
            .where(DiscoveryReviewCase.opened_at <= as_of)
            .order_by(DiscoveryReviewCase.id)
        ).mappings()
    )
    url_source_ids = _discovery_url_sources(
        connection,
        [
            row["telegram_discovery_url_id"]
            for row in rows
            if row["telegram_discovery_url_id"] is not None
        ],
    )
    source_ids = [
        row["message_source_id"]
        or url_source_ids.get(row["telegram_discovery_url_id"])
        for row in rows
    ]
    source_urls = _source_urls_by_id(
        connection,
        [source_id for source_id in source_ids if source_id is not None],
    )
    exclusions: Counter[str] = Counter()
    cases: list[dict[str, Any]] = []
    for row in rows:
        if row["updated_at"] > as_of:
            exclusions["updated_after_snapshot"] += 1
            continue
        source_id = row["message_source_id"] or url_source_ids.get(
            row["telegram_discovery_url_id"]
        )
        if source_id is None:
            exclusions["unattributed_discovery_case"] += 1
            continue
        source_canonical_url = source_urls.get(source_id)
        if source_canonical_url is None:
            exclusions["missing_source"] += 1
            continue
        source_reason = _source_exclusion_reason(
            source_canonical_url,
            all_sources=all_sources,
            active_real_sources=active_real_sources,
        )
        if source_reason is not None:
            exclusions[source_reason] += 1
            continue
        cases.append(
            {
                "review_case_id": str(row["id"]),
                "case_type": "discovery",
                "source_id": str(source_id),
                "source_key": _source_key(source_canonical_url, active_real_sources),
                "status": _enum_value(row["status"]),
                "opened_at": _timestamp(row["opened_at"]),
                "resolved_at": (
                    _timestamp(row["resolved_at"])
                    if row["resolved_at"] is not None
                    else None
                ),
                "reason_codes": list(_reason_codes(row["opened_snapshot"])),
                "quality_issue_codes": [],
                "has_explicit_conflict": False,
            }
        )
    return cases, _counter_payload(exclusions)


def _collect_source_executions(
    connection: Connection,
    *,
    window_started_at: datetime,
    as_of: datetime,
    all_sources: Mapping[str, SourceDefinition],
    active_real_sources: Mapping[str, SourceDefinition],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    excluded_urls = _excluded_canonical_urls(
        all_sources,
        include_telegram_operational=True,
    )
    statement = (
        select(
            SourceExecutionRun.id,
            SourceExecutionRun.source_id,
            SourceExecutionRun.status,
            SourceExecutionRun.finished_at,
            SourceExecutionRun.result_kind,
            SourceExecutionRun.metrics,
            Source.canonical_url.label("source_canonical_url"),
        )
        .select_from(SourceExecutionRun)
        .join(Source, Source.id == SourceExecutionRun.source_id)
        .where(
            SourceExecutionRun.finished_at.is_not(None),
            SourceExecutionRun.finished_at >= window_started_at,
            SourceExecutionRun.finished_at <= as_of,
        )
        .order_by(SourceExecutionRun.finished_at, SourceExecutionRun.id)
    )
    if excluded_urls:
        statement = statement.where(Source.canonical_url.not_in(excluded_urls))
    rows = connection.execute(statement).mappings()
    exclusions: Counter[str] = Counter()
    executions: list[dict[str, Any]] = []
    for row in rows:
        source_reason = _source_exclusion_reason(
            row["source_canonical_url"],
            all_sources=all_sources,
            active_real_sources=active_real_sources,
        )
        if source_reason is not None:
            exclusions[source_reason] += 1
            continue
        metrics = row["metrics"]
        if isinstance(metrics, Mapping) and metrics.get("dry_run") is True:
            exclusions["dry_run_execution"] += 1
            continue
        executions.append(
            {
                "execution_id": str(row["id"]),
                "source_id": str(row["source_id"]),
                "source_key": _source_key(row["source_canonical_url"], active_real_sources),
                "status": _enum_value(row["status"]),
                "finished_at": _timestamp(row["finished_at"]),
                "result_kind": row["result_kind"],
                "dry_run": False,
            }
        )
    return executions, _counter_payload(exclusions)


def build_input_manifest(
    connection: Connection,
    *,
    registry: SourceRegistry,
    as_of: datetime,
    freshness_window_days: int = FRESHNESS_WINDOW_DAYS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Freeze the facts used by the catalog quality and baseline formulas.

    The caller owns a repeatable-read transaction. The manifest contains
    identifiers, field-presence facts, normalized deadline dates, and decimal
    amount values; raw captures and review payloads are not copied.
    """

    if freshness_window_days < 1:
        raise AnalyticsSnapshotError("freshness_window_days must be positive")
    source_scope, all_sources, active_real_sources = _registry_scope(registry)
    window_started_at = as_of - timedelta(days=freshness_window_days)
    programs, program_exclusions = _collect_programs(
        connection,
        as_of=as_of,
        all_sources=all_sources,
        active_real_sources=active_real_sources,
    )
    canonical_cases, canonical_case_exclusions = _collect_canonical_review_cases(
        connection,
        as_of=as_of,
        all_sources=all_sources,
        active_real_sources=active_real_sources,
    )
    discovery_cases, discovery_case_exclusions = _collect_discovery_review_cases(
        connection,
        as_of=as_of,
        all_sources=all_sources,
        active_real_sources=active_real_sources,
    )
    executions, execution_exclusions = _collect_source_executions(
        connection,
        window_started_at=window_started_at,
        as_of=as_of,
        all_sources=all_sources,
        active_real_sources=active_real_sources,
    )
    taxonomy = _collect_taxonomy_associations(
        connection,
        program_ids=[str(program["program_id"]) for program in programs],
    )
    input_manifest = {
        "version": INPUT_MANIFEST_VERSION,
        "data_class": _database_data_class(connection),
        "as_of": _timestamp(as_of),
        "freshness_window_days": freshness_window_days,
        "programs": programs,
        "taxonomy": taxonomy,
        "review_cases": canonical_cases + discovery_cases,
        "source_executions": executions,
        "exclusions": {
            "programs": program_exclusions,
            "canonical_review_cases": canonical_case_exclusions,
            "discovery_review_cases": discovery_case_exclusions,
            "source_executions": execution_exclusions,
        },
    }
    return source_scope, input_manifest


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalyticsSnapshotError(f"{field} must be an object")
    return value


def _object_list(value: object, *, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise AnalyticsSnapshotError(f"{field} must be an array")
    return [_mapping(item, field=field) for item in value]


def _exclusions(manifest: Mapping[str, Any], key: str) -> dict[str, int]:
    raw_exclusions = _mapping(manifest.get("exclusions", {}), field="exclusions")
    raw_values = _mapping(raw_exclusions.get(key, {}), field=f"exclusions.{key}")
    return {
        str(name): int(value)
        for name, value in sorted(raw_values.items())
        if isinstance(value, int) and value > 0
    }


def _metric(
    *,
    definition: str,
    period: Mapping[str, Any],
    numerator: int,
    denominator: int,
    exclusions: Mapping[str, int],
    limitation: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "definition": definition,
        "period": dict(period),
        "numerator": numerator,
        "denominator": denominator,
        "value": _ratio(numerator, denominator),
        "exclusions": dict(exclusions),
        "limitation": limitation,
    }
    if extra:
        result.update(extra)
    return result


def calculate_quality_metrics(
    *,
    source_scope: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Calculate catalog quality metrics from a frozen manifest, never live rows."""

    as_of = datetime.fromisoformat(str(input_manifest["as_of"]))
    as_of = _as_utc(as_of)
    freshness_window_days = int(input_manifest["freshness_window_days"])
    if freshness_window_days < 1:
        raise AnalyticsSnapshotError("freshness_window_days must be positive")
    window_started_at = as_of - timedelta(days=freshness_window_days)
    programs = _object_list(input_manifest.get("programs", []), field="programs")
    review_cases = _object_list(input_manifest.get("review_cases", []), field="review_cases")
    source_executions = _object_list(
        input_manifest.get("source_executions", []),
        field="source_executions",
    )
    active_sources = _object_list(
        source_scope.get("active_real_sources", []),
        field="source_scope.active_real_sources",
    )
    excluded_sources = _object_list(
        source_scope.get("excluded_sources", []),
        field="source_scope.excluded_sources",
    )
    active_source_keys = {
        str(source["source_key"])
        for source in active_sources
        if isinstance(source.get("source_key"), str)
    }

    fresh_programs = sum(
        datetime.fromisoformat(str(program["observed_at"])).astimezone(timezone.utc)
        >= window_started_at
        for program in programs
    )
    complete_programs = sum(
        bool(program.get("title_present"))
        and bool(program.get("source_url_present"))
        and bool(program.get("observed_at"))
        and bool(program.get("deadline_present"))
        and bool(program.get("funding_present"))
        and str(program.get("funding_value_kind"))
        in {"exact", "minimum", "maximum", "range", "unknown", "not_stated"}
        for program in programs
    )
    pending_statuses = {
        ReviewCaseStatus.OPEN.value,
        ReviewCaseStatus.NEEDS_CLARIFICATION.value,
    }
    canonical_pending_cases = [
        case
        for case in review_cases
        if case.get("case_type") == "canonical" and case.get("status") in pending_statuses
    ]
    explicit_conflicts = sum(
        bool(case.get("has_explicit_conflict")) for case in canonical_pending_cases
    )
    status_counts = {
        status: sum(case.get("status") == status for case in review_cases)
        for status in (
            ReviewCaseStatus.OPEN.value,
            ReviewCaseStatus.NEEDS_CLARIFICATION.value,
            ReviewCaseStatus.RESOLVED.value,
        )
    }
    pending_cases = (
        status_counts[ReviewCaseStatus.OPEN.value]
        + status_counts[ReviewCaseStatus.NEEDS_CLARIFICATION.value]
    )
    successful_source_keys = {
        str(execution["source_key"])
        for execution in source_executions
        if execution.get("status") == SourceExecutionStatus.SUCCEEDED.value
        and execution.get("dry_run") is False
        and str(execution.get("source_key")) in active_source_keys
    }
    program_exclusions = _exclusions(input_manifest, "programs")
    review_exclusions = _exclusions(input_manifest, "canonical_review_cases")
    for key, value in _exclusions(input_manifest, "discovery_review_cases").items():
        review_exclusions[f"discovery_{key}"] = value
    execution_exclusions = _exclusions(input_manifest, "source_executions")
    if excluded_sources:
        execution_exclusions["configured_but_excluded_sources"] = len(excluded_sources)
    period = {
        "kind": "rolling_window",
        "days": freshness_window_days,
        "started_at": _timestamp(window_started_at),
        "ended_at": _timestamp(as_of),
    }
    point_in_time = {"kind": "point_in_time", "as_of": _timestamp(as_of)}

    metrics = {
        "freshness": _metric(
            definition=(
                "Доля опубликованных программ из активных реальных источников, "
                "для которых первоисточник наблюдался в заданном окне."
            ),
            period=period,
            numerator=fresh_programs,
            denominator=len(programs),
            exclusions=program_exclusions,
            limitation=(
                "Показатель измеряет возраст последнего сохранённого наблюдения "
                "первоисточника, а не актуальность его содержимого на текущую минуту."
            ),
        ),
        "completeness": _metric(
            definition=(
                "Доля опубликованных программ из активных реальных источников с "
                "названием, ссылкой и временем наблюдения источника, дедлайном и "
                "корректно выраженным финансированием."
            ),
            period=point_in_time,
            numerator=complete_programs,
            denominator=len(programs),
            exclusions=program_exclusions,
            limitation=(
                "Неизвестное или неуказанное финансирование считается честно "
                "зафиксированным значением; показатель не доказывает полноту или "
                "истинность внешнего рынка."
            ),
        ),
        "conflicts": _metric(
            definition=(
                "Доля нерешённых канонических review-кейсов с явно зафиксированным "
                "конфликтом точной идентичности."
            ),
            period=point_in_time,
            numerator=explicit_conflicts,
            denominator=len(canonical_pending_cases),
            exclusions=review_exclusions,
            limitation=(
                "Учитываются только явно обозначенные конфликты дедупликации; "
                "отсутствие такого кейса не исключает других ошибок данных."
            ),
        ),
        "source_coverage": _metric(
            definition=(
                "Доля активных реальных источников из зафиксированного реестра, "
                "для которых был успешный не-dry-run запуск в заданном окне."
            ),
            period=period,
            numerator=len(successful_source_keys),
            denominator=len(active_source_keys),
            exclusions=execution_exclusions,
            limitation=(
                "Это покрытие настроенного реестра запусков, а не доля всех "
                "существующих в мире конкурсов или источников."
            ),
            extra={"covered_source_keys": sorted(successful_source_keys)},
        ),
        "review_status": _metric(
            definition=(
                "Доля review-кейсов из активных реальных источников, которые на "
                "момент среза ожидают решения или уточнения."
            ),
            period=point_in_time,
            numerator=pending_cases,
            denominator=len(review_cases),
            exclusions=review_exclusions,
            limitation=(
                "Это размер и состояние очередей canonical и discovery, а не оценка "
                "качества опубликованных программ."
            ),
            extra={"status_counts": status_counts},
        ),
    }
    metric_missing = "no implicit zero; null value when the denominator is zero"
    metric_contexts = {
        "freshness": {
            "filter": "published programs from active eligible non-fixture sources; observed_at compared with rolling window",
            "sample_unit": "program",
        },
        "completeness": {
            "filter": "published programs from active eligible non-fixture sources at as_of",
            "sample_unit": "program",
        },
        "conflicts": {
            "filter": "canonical ReviewCase with open/needs_clarification status at as_of",
            "sample_unit": "canonical review case",
        },
        "source_coverage": {
            "filter": "active non-fixture/non-FASIE registry keys and non-dry-run execution in rolling window",
            "sample_unit": "source",
        },
        "review_status": {
            "filter": "attributed canonical/discovery ReviewCase not updated after as_of",
            "sample_unit": "review case",
        },
    }
    for name, metric in metrics.items():
        metric["snapshot_id"] = snapshot_id
        metric["data_class"] = input_manifest.get("data_class", "unknown")
        metric["sample_size"] = metric["denominator"]
        metric["unit"] = "share"
        metric["sample_unit"] = metric_contexts[name]["sample_unit"]
        metric["filter"] = metric_contexts[name]["filter"]
        metric["missing"] = metric_missing
        metric["formula"] = "numerator / denominator; null when denominator = 0"
    return metrics


def _record_from_row(row: Mapping[str, Any]) -> AnalyticsSnapshotRecord:
    source_scope = row["source_scope"]
    input_manifest = row["input_manifest"]
    metrics = row["metrics"]
    limitations = row["limitations"]
    if not all(
        isinstance(value, Mapping) for value in (source_scope, input_manifest, metrics)
    ) or not isinstance(limitations, list):
        raise AnalyticsSnapshotError("stored snapshot has an invalid JSON shape")
    return AnalyticsSnapshotRecord(
        id=row["id"],
        scope=row["scope"],
        calculation_version=row["calculation_version"],
        as_of=row["as_of"],
        freshness_window_days=row["freshness_window_days"],
        registry_fingerprint=row["registry_fingerprint"],
        input_fingerprint=row["input_fingerprint"],
        source_scope=dict(source_scope),
        input_manifest=dict(input_manifest),
        metrics=dict(metrics),
        limitations=tuple(str(value) for value in limitations),
        created_at=row["created_at"],
    )


def get_analytics_snapshot(
    connection: Connection,
    snapshot_id: UUID,
) -> AnalyticsSnapshotRecord | None:
    row = connection.execute(
        select(
            AnalyticsSnapshot.id,
            AnalyticsSnapshot.scope,
            AnalyticsSnapshot.calculation_version,
            AnalyticsSnapshot.as_of,
            AnalyticsSnapshot.freshness_window_days,
            AnalyticsSnapshot.registry_fingerprint,
            AnalyticsSnapshot.input_fingerprint,
            AnalyticsSnapshot.source_scope,
            AnalyticsSnapshot.input_manifest,
            AnalyticsSnapshot.metrics,
            AnalyticsSnapshot.limitations,
            AnalyticsSnapshot.created_at,
        ).where(AnalyticsSnapshot.id == snapshot_id)
    ).mappings().one_or_none()
    return _record_from_row(row) if row is not None else None


def list_analytics_snapshots(
    connection: Connection,
    *,
    scope: str = SNAPSHOT_SCOPE,
    as_of_before: datetime | None = None,
) -> tuple[AnalyticsSnapshotRecord, ...]:
    """Return immutable snapshots in chronological order for reproducible analysis."""

    statement = select(
        AnalyticsSnapshot.id,
        AnalyticsSnapshot.scope,
        AnalyticsSnapshot.calculation_version,
        AnalyticsSnapshot.as_of,
        AnalyticsSnapshot.freshness_window_days,
        AnalyticsSnapshot.registry_fingerprint,
        AnalyticsSnapshot.input_fingerprint,
        AnalyticsSnapshot.source_scope,
        AnalyticsSnapshot.input_manifest,
        AnalyticsSnapshot.metrics,
        AnalyticsSnapshot.limitations,
        AnalyticsSnapshot.created_at,
    ).where(AnalyticsSnapshot.scope == scope)
    if as_of_before is not None:
        statement = statement.where(AnalyticsSnapshot.as_of < as_of_before)
    rows = connection.execute(
        statement.order_by(AnalyticsSnapshot.as_of, AnalyticsSnapshot.id)
    ).mappings()
    return tuple(_record_from_row(row) for row in rows)


def create_analytics_snapshot(
    connection: Connection,
    *,
    registry: SourceRegistry,
    as_of: datetime | None = None,
    freshness_window_days: int = FRESHNESS_WINDOW_DAYS,
) -> AnalyticsSnapshotResult:
    """Persist one idempotent quality and baseline snapshot in the caller's transaction."""

    resolved_as_of = _as_utc(as_of)
    source_scope, input_manifest = build_input_manifest(
        connection,
        registry=registry,
        as_of=resolved_as_of,
        freshness_window_days=freshness_window_days,
    )
    registry_fingerprint = _fingerprint(source_scope)
    input_fingerprint = _fingerprint(
        {
            "scope": SNAPSHOT_SCOPE,
            "calculation_version": CALCULATION_VERSION,
            "as_of": _timestamp(resolved_as_of),
            "freshness_window_days": freshness_window_days,
            "registry_fingerprint": registry_fingerprint,
            "input_manifest": input_manifest,
        }
    )
    snapshot_id = uuid5(NAMESPACE_URL, f"siderfold:analytics:{input_fingerprint}")
    metrics = calculate_snapshot_metrics(
        snapshot_id=snapshot_id,
        source_scope=source_scope,
        input_manifest=input_manifest,
        input_fingerprint=input_fingerprint,
    )
    snapshot_id = connection.scalar(
        postgresql_insert(AnalyticsSnapshot)
        .values(
            id=snapshot_id,
            scope=SNAPSHOT_SCOPE,
            calculation_version=CALCULATION_VERSION,
            as_of=resolved_as_of,
            freshness_window_days=freshness_window_days,
            registry_fingerprint=registry_fingerprint,
            input_fingerprint=input_fingerprint,
            source_scope=source_scope,
            input_manifest=input_manifest,
            metrics=metrics,
            limitations=list(SNAPSHOT_LIMITATIONS),
        )
        .on_conflict_do_nothing(index_elements=("input_fingerprint",))
        .returning(AnalyticsSnapshot.id)
    )
    created = snapshot_id is not None
    if snapshot_id is None:
        snapshot_id = connection.scalar(
            select(AnalyticsSnapshot.id).where(
                AnalyticsSnapshot.input_fingerprint == input_fingerprint
            )
        )
    if snapshot_id is None:
        raise AnalyticsSnapshotError("analytics snapshot was not persisted after conflict")
    snapshot = get_analytics_snapshot(connection, snapshot_id)
    if snapshot is None:
        raise AnalyticsSnapshotError("analytics snapshot could not be read after persistence")
    return AnalyticsSnapshotResult(snapshot=snapshot, created=created)


def recalculate_snapshot_metrics(snapshot: AnalyticsSnapshotRecord) -> dict[str, Any]:
    """Recalculate a persisted snapshot without reading mutable catalog rows."""

    manifest_version = snapshot.input_manifest.get("version")
    if manifest_version not in SUPPORTED_INPUT_MANIFEST_VERSIONS:
        raise AnalyticsSnapshotError(
            "recalculation requires a supported catalog-quality input manifest"
        )
    return calculate_snapshot_metrics(
        snapshot_id=snapshot.id,
        source_scope=snapshot.source_scope,
        input_manifest=snapshot.input_manifest,
        input_fingerprint=snapshot.input_fingerprint,
    )


def calculate_snapshot_metrics(
    *,
    snapshot_id: UUID | str,
    source_scope: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    input_fingerprint: str,
) -> dict[str, Any]:
    snapshot_key = str(snapshot_id)
    metrics = calculate_quality_metrics(
        source_scope=source_scope,
        input_manifest=input_manifest,
        snapshot_id=snapshot_key,
    )
    try:
        metrics["baseline"] = calculate_baseline_metrics(
            source_scope=source_scope,
            input_manifest=input_manifest,
            input_fingerprint=input_fingerprint,
            snapshot_id=snapshot_key,
        )
    except BaselineMetricsError as error:
        raise AnalyticsSnapshotError(str(error)) from error
    if input_manifest.get("version") == INPUT_MANIFEST_VERSION:
        if "taxonomy" not in input_manifest:
            raise AnalyticsSnapshotError("catalog-quality-input/v3 requires frozen taxonomy links")
        try:
            metrics["regional_indicators"] = calculate_regional_indicators(
                source_scope=source_scope,
                input_manifest=input_manifest,
                snapshot_id=snapshot_key,
            )
        except RegionalIndicatorsError as error:
            raise AnalyticsSnapshotError(str(error)) from error
    return metrics

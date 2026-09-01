from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.analytics.snapshots import (
    SNAPSHOT_SCOPE,
    calculate_quality_metrics,
    create_analytics_snapshot,
    get_analytics_snapshot,
    recalculate_snapshot_metrics,
)
from app.domain.models import (
    AnalyticsSnapshot,
    DataQualityIssue,
    DataQualitySeverity,
    DiscoveryReviewCase,
    FundingValueKind,
    Program,
    ProgramDeadline,
    ProgramFunding,
    ProgramSource,
    PublicationStatus,
    ReviewCase,
    ReviewCaseStatus,
    Source,
    SourceExecutionRun,
    SourceExecutionStatus,
    SourceExecutionTrigger,
    StagedRecordState,
    TelegramDiscoveryMessage,
)
from app.sources.registry import (
    SourceAccessMethod,
    SourceDefinition,
    SourceRegistry,
    SourceRegistryStatus,
)
from tests.fixtures.canonical import PUBLISHED_AT, insert_program_with_source
from tests.fixtures.provenance import (
    finish_ingestion_run,
    insert_ingestion_run,
    insert_raw_capture,
    insert_staged_record,
    start_ingestion_run,
    transition_staged_record,
)


AS_OF = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
WINDOW_STARTED_AT = AS_OF - timedelta(days=30)


def _registry() -> SourceRegistry:
    def definition(
        source_key: str,
        canonical_url: str,
        *,
        access_method: SourceAccessMethod = SourceAccessMethod.HTTP,
    ) -> SourceDefinition:
        return SourceDefinition(
            source_key=source_key,
            name=source_key.replace("-", " ").title(),
            canonical_url=canonical_url,
            allowed_url_prefixes=(canonical_url,),
            access_method=access_method,
            schedule="manual",
            status=SourceRegistryStatus.ACTIVE,
            responsible="test-owner",
            adapter_name="test-adapter",
            adapter_version="1.0.0",
            fixture_path=("tests/fixtures/adapters/catalog_v1.json" if access_method is SourceAccessMethod.FIXTURE else None),
        )

    definitions = (
        definition("official-alpha", "https://alpha.example.test/catalog"),
        definition("official-beta", "https://beta.example.test/catalog"),
        definition("telegram-discovery", "https://t.me/cptgrantov"),
        definition(
            "fixture-catalog",
            "https://fixture.example.test/catalog",
            access_method=SourceAccessMethod.FIXTURE,
        ),
    )
    return SourceRegistry(version=1, sources={item.source_key: item for item in definitions})


def _insert_source(connection: Connection, *, name: str, canonical_url: str) -> UUID:
    source_id = uuid4()
    connection.execute(
        insert(Source).values(id=source_id, name=name, canonical_url=canonical_url)
    )
    return source_id


def _publish_program(
    connection: Connection,
    *,
    source_id: UUID,
    title: str,
    observed_at: datetime,
    deadline: bool,
    funding_kind: FundingValueKind | None,
) -> UUID:
    program_id = insert_program_with_source(
        connection,
        source_id=source_id,
        title=title,
        publication_status=PublicationStatus.PUBLISHED,
        published_at=PUBLISHED_AT,
    )
    connection.execute(
        update(ProgramSource)
        .where(
            ProgramSource.program_id == program_id,
            ProgramSource.source_id == source_id,
        )
        .values(
            source_url=f"https://example.test/programs/{program_id}",
            observed_at=observed_at,
        )
    )
    if deadline:
        connection.execute(
            insert(ProgramDeadline).values(
                program_id=program_id,
                deadline_on=date(2026, 10, 1),
            )
        )
    if funding_kind is not None:
        values: dict[str, object] = {
            "program_id": program_id,
            "value_kind": funding_kind,
            "currency_code": None,
            "exact_amount": None,
            "min_amount": None,
            "max_amount": None,
        }
        if funding_kind is FundingValueKind.EXACT:
            values.update(currency_code="RUB", exact_amount=Decimal("100000.00"))
        connection.execute(insert(ProgramFunding).values(**values))
    return program_id


def _review_staged_record(connection: Connection, *, source_id: UUID) -> UUID:
    run_id = insert_ingestion_run(connection, source_id=source_id)
    start_ingestion_run(connection, run_id=run_id)
    finish_ingestion_run(connection, run_id=run_id)
    raw_capture_id = insert_raw_capture(connection, ingestion_run_id=run_id)
    staged_record_id = insert_staged_record(connection, raw_capture_id=raw_capture_id)
    transition_staged_record(
        connection,
        staged_record_id=staged_record_id,
        state=StagedRecordState.EXTRACTED,
    )
    transition_staged_record(
        connection,
        staged_record_id=staged_record_id,
        state=StagedRecordState.REVIEW,
    )
    return staged_record_id


def _insert_review_case(
    connection: Connection,
    *,
    source_id: UUID,
    reasons: list[str],
) -> UUID:
    staged_record_id = _review_staged_record(connection, source_id=source_id)
    review_case_id = uuid4()
    connection.execute(
        insert(ReviewCase).values(
            id=review_case_id,
            staged_record_id=staged_record_id,
            status=ReviewCaseStatus.OPEN,
            opened_snapshot={"reason_codes": reasons},
            opened_at=AS_OF - timedelta(days=1),
            resolved_at=None,
            updated_at=AS_OF - timedelta(days=1),
        )
    )
    if "exact_identity_conflict" in reasons:
        connection.execute(
            insert(DataQualityIssue).values(
                id=uuid4(),
                staged_record_id=staged_record_id,
                severity=DataQualitySeverity.WARNING,
                code="deduplication_exact_identity_conflict",
                message="Fixture conflict evidence",
            )
        )
    return review_case_id


def _insert_discovery_review_case(connection: Connection, *, source_id: UUID) -> UUID:
    run_id = insert_ingestion_run(connection, source_id=source_id)
    start_ingestion_run(connection, run_id=run_id)
    finish_ingestion_run(connection, run_id=run_id)
    raw_capture_id = insert_raw_capture(connection, ingestion_run_id=run_id)
    message_id = uuid4()
    received_at = AS_OF - timedelta(days=1)
    connection.execute(
        insert(TelegramDiscoveryMessage).values(
            id=message_id,
            source_id=source_id,
            ingestion_run_id=run_id,
            raw_capture_id=raw_capture_id,
            message_id=1001,
            message_url="https://t.me/cptgrantov/1001",
            published_at=received_at,
            received_at=received_at,
            last_observed_at=received_at,
            service_label=None,
            content_sha256="a" * 64,
            review_required=True,
            discovery_issues=[],
            expires_at=AS_OF + timedelta(days=30),
        )
    )
    review_case_id = uuid4()
    connection.execute(
        insert(DiscoveryReviewCase).values(
            id=review_case_id,
            telegram_discovery_message_id=message_id,
            status=ReviewCaseStatus.OPEN,
            opened_snapshot={"reason_codes": ["missing_reliable_external_url"]},
            opened_at=received_at,
            updated_at=received_at,
        )
    )
    return review_case_id


def _insert_execution(
    connection: Connection,
    *,
    source_id: UUID,
    source_key: str,
    status: SourceExecutionStatus,
) -> UUID:
    finished_at = AS_OF - timedelta(days=2)
    execution_id = uuid4()
    connection.execute(
        insert(SourceExecutionRun).values(
            id=execution_id,
            source_id=source_id,
            source_key=source_key,
            trigger=SourceExecutionTrigger.MANUAL,
            status=status,
            started_at=finished_at - timedelta(minutes=1),
            finished_at=finished_at,
            attempt_count=1,
            result_kind="completed" if status is SourceExecutionStatus.SUCCEEDED else "failed",
            metrics={"dry_run": False},
            error_codes=[] if status is SourceExecutionStatus.SUCCEEDED else ["fixture_failure"],
        )
    )
    return execution_id


def test_quality_formulas_keep_unknown_funding_and_explicit_denominators() -> None:
    source_scope = {
        "active_real_sources": [
            {"source_key": "official-alpha"},
            {"source_key": "official-beta"},
        ],
        "excluded_sources": [{"source_key": "fixture-catalog", "reason": "fixture_access"}],
    }
    input_manifest = {
        "as_of": AS_OF.isoformat(),
        "freshness_window_days": 30,
        "programs": [
            {
                "observed_at": (AS_OF - timedelta(days=2)).isoformat(),
                "title_present": True,
                "source_url_present": True,
                "deadline_present": True,
                "funding_present": True,
                "funding_value_kind": "unknown",
            },
            {
                "observed_at": (AS_OF - timedelta(days=31)).isoformat(),
                "title_present": True,
                "source_url_present": True,
                "deadline_present": True,
                "funding_present": True,
                "funding_value_kind": "exact",
            },
        ],
        "review_cases": [
            {
                "case_type": "canonical",
                "status": "open",
                "has_explicit_conflict": True,
            },
            {
                "case_type": "discovery",
                "status": "needs_clarification",
                "has_explicit_conflict": False,
            },
            {
                "case_type": "canonical",
                "status": "resolved",
                "has_explicit_conflict": False,
            },
        ],
        "source_executions": [
            {"source_key": "official-alpha", "status": "succeeded", "dry_run": False},
            {"source_key": "official-beta", "status": "failed", "dry_run": False},
        ],
        "exclusions": {
            "programs": {"fixture_source": 1},
            "canonical_review_cases": {},
            "discovery_review_cases": {},
            "source_executions": {},
        },
    }

    metrics = calculate_quality_metrics(
        source_scope=source_scope,
        input_manifest=input_manifest,
    )

    assert metrics["freshness"]["numerator"] == 1
    assert metrics["freshness"]["denominator"] == 2
    assert metrics["freshness"]["value"] == 0.5
    assert metrics["completeness"]["numerator"] == 2
    assert metrics["completeness"]["denominator"] == 2
    assert metrics["conflicts"]["numerator"] == 1
    assert metrics["conflicts"]["denominator"] == 1
    assert metrics["source_coverage"]["numerator"] == 1
    assert metrics["source_coverage"]["denominator"] == 2
    assert metrics["review_status"]["numerator"] == 2
    assert metrics["review_status"]["denominator"] == 3
    for metric in metrics.values():
        assert metric["definition"]
        assert metric["period"]
        assert "exclusions" in metric
        assert metric["limitation"]


@pytest.mark.postgres
def test_snapshot_freezes_real_catalog_inputs_and_excludes_fixture_data(
    migrated_engine: Engine,
) -> None:
    registry = _registry()
    with migrated_engine.begin() as connection:
        alpha_source_id = _insert_source(
            connection,
            name="Official Alpha",
            canonical_url="https://alpha.example.test/catalog",
        )
        beta_source_id = _insert_source(
            connection,
            name="Official Beta",
            canonical_url="https://beta.example.test/catalog",
        )
        telegram_source_id = _insert_source(
            connection,
            name="Telegram discovery",
            canonical_url="https://t.me/cptgrantov",
        )
        fixture_source_id = _insert_source(
            connection,
            name="Fixture catalog",
            canonical_url="https://fixture.example.test/catalog",
        )
        fresh_complete = _publish_program(
            connection,
            source_id=alpha_source_id,
            title="Fresh complete",
            observed_at=AS_OF - timedelta(days=1),
            deadline=True,
            funding_kind=FundingValueKind.EXACT,
        )
        _publish_program(
            connection,
            source_id=alpha_source_id,
            title="Stale complete",
            observed_at=WINDOW_STARTED_AT - timedelta(days=1),
            deadline=True,
            funding_kind=FundingValueKind.UNKNOWN,
        )
        _publish_program(
            connection,
            source_id=beta_source_id,
            title="Fresh without funding",
            observed_at=AS_OF - timedelta(days=1),
            deadline=True,
            funding_kind=None,
        )
        _publish_program(
            connection,
            source_id=beta_source_id,
            title="Fresh without deadline",
            observed_at=AS_OF - timedelta(days=1),
            deadline=False,
            funding_kind=FundingValueKind.UNKNOWN,
        )
        _publish_program(
            connection,
            source_id=fixture_source_id,
            title="Synthetic fixture program",
            observed_at=AS_OF - timedelta(days=1),
            deadline=True,
            funding_kind=FundingValueKind.EXACT,
        )
        _insert_review_case(
            connection,
            source_id=alpha_source_id,
            reasons=["exact_identity_conflict"],
        )
        _insert_review_case(
            connection,
            source_id=beta_source_id,
            reasons=["candidate_ready"],
        )
        _insert_review_case(
            connection,
            source_id=alpha_source_id,
            reasons=["candidate_ready"],
        )
        _insert_discovery_review_case(connection, source_id=telegram_source_id)
        _insert_execution(
            connection,
            source_id=alpha_source_id,
            source_key="official-alpha",
            status=SourceExecutionStatus.SUCCEEDED,
        )
        _insert_execution(
            connection,
            source_id=beta_source_id,
            source_key="official-beta",
            status=SourceExecutionStatus.FAILED,
        )

        first = create_analytics_snapshot(connection, registry=registry, as_of=AS_OF)
        duplicate = create_analytics_snapshot(connection, registry=registry, as_of=AS_OF)

        assert first.created is True
        assert duplicate.created is False
        assert duplicate.snapshot.id == first.snapshot.id
        assert first.snapshot.scope == SNAPSHOT_SCOPE
        assert first.snapshot.metrics["freshness"]["numerator"] == 3
        assert first.snapshot.metrics["freshness"]["denominator"] == 4
        assert first.snapshot.metrics["completeness"]["numerator"] == 2
        assert first.snapshot.metrics["completeness"]["denominator"] == 4
        assert first.snapshot.metrics["completeness"]["exclusions"] == {
            "fixture_source": 1
        }
        assert first.snapshot.metrics["conflicts"]["numerator"] == 1
        assert first.snapshot.metrics["conflicts"]["denominator"] == 3
        assert first.snapshot.metrics["source_coverage"]["numerator"] == 1
        assert first.snapshot.metrics["source_coverage"]["denominator"] == 3
        assert first.snapshot.metrics["review_status"]["status_counts"] == {
            "open": 4,
            "needs_clarification": 0,
            "resolved": 0,
        }
        assert first.snapshot.metrics["review_status"]["numerator"] == 4
        assert first.snapshot.metrics["review_status"]["denominator"] == 4

    with migrated_engine.begin() as connection:
        connection.execute(
            update(Program)
            .where(Program.id == fresh_complete)
            .values(title="Changed after snapshot")
        )
        stored = get_analytics_snapshot(connection, first.snapshot.id)
        assert stored is not None
        assert recalculate_snapshot_metrics(stored) == first.snapshot.metrics


@pytest.mark.postgres
def test_snapshot_rows_are_immutable(migrated_engine: Engine) -> None:
    registry = _registry()
    with migrated_engine.begin() as connection:
        result = create_analytics_snapshot(connection, registry=registry, as_of=AS_OF)
        snapshot_id = result.snapshot.id

    with pytest.raises(IntegrityError, match="analytics snapshots are immutable"):
        with migrated_engine.begin() as connection:
            connection.execute(
                update(AnalyticsSnapshot)
                .where(AnalyticsSnapshot.id == snapshot_id)
                .values(scope="changed")
            )

    with pytest.raises(IntegrityError, match="analytics snapshots are immutable"):
        with migrated_engine.begin() as connection:
            connection.execute(delete(AnalyticsSnapshot).where(AnalyticsSnapshot.id == snapshot_id))

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(AnalyticsSnapshot.id).where(AnalyticsSnapshot.id == snapshot_id)
        ) == snapshot_id

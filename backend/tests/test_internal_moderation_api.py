from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import ANY
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.domain.models import (
    DataQualityIssue,
    DataQualitySeverity,
    DeduplicationMatch,
    DiscoveryReviewAction,
    DiscoveryReviewCase,
    OperatorOperation,
    Program,
    ProgramPublicationAction,
    PublicationStatus,
    ReviewAction,
    ReviewCase,
    ReviewCaseStatus,
    ReviewIssueResolution,
    ReviewRevision,
    SourceExecutionRun,
    SourceExecutionStatus,
    SourceExecutionTrigger,
    StagedRecord,
    StagedRecordState,
    TelegramDiscoveryRoute,
    TelegramDiscoveryUrl,
    Theme,
)
from app.main import create_app
from app.review.service import evaluate_staged_record
from tests.fixtures.canonical import insert_source
from tests.fixtures.provenance import (
    finish_ingestion_run,
    insert_ingestion_run,
    insert_raw_capture,
    start_ingestion_run,
    transition_staged_record,
)


pytestmark = pytest.mark.postgres

AUTHORIZATION = {"Authorization": "Bearer internal-test-token"}


def _client(engine: Engine, *, enabled: bool = True) -> TestClient:
    settings = Settings(
        app_env="test",
        internal_api_token=SecretStr("internal-test-token") if enabled else None,
        internal_operator_id="reviewer@example.test",
    )
    return TestClient(create_app(settings=settings, engine=engine))


def _review_case(
    connection: Connection,
    *,
    source_id: UUID,
    record_key: str,
    external_id: str,
    record_url: str | None = None,
    title: str = "Конкурс для региональных инициатив",
) -> tuple[UUID, UUID]:
    run_id = insert_ingestion_run(connection, source_id=source_id)
    start_ingestion_run(connection, run_id=run_id)
    finish_ingestion_run(connection, run_id=run_id)
    raw_capture_id = insert_raw_capture(connection, ingestion_run_id=run_id)
    staged_record_id = uuid4()
    connection.execute(
        insert(StagedRecord).values(
            id=staged_record_id,
            raw_capture_id=raw_capture_id,
            record_key=record_key,
            candidate_payload={
                "record": {
                    "title": title,
                    "record_url": record_url
                    or f"https://source.example.test/competitions/{record_key}",
                    "deadline_on": date(2026, 11, 30).isoformat(),
                    "external_id": external_id,
                    "funding": {
                        "value_kind": "maximum",
                        "currency_code": "RUB",
                        "max_amount": "500000",
                    },
                    "payload": {"organizer": "Фонд примеров"},
                }
            },
            state=StagedRecordState.RECEIVED,
        )
    )
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
    evaluation = evaluate_staged_record(connection, staged_record_id)
    return staged_record_id, evaluation.review_case_id


def _request_headers(idempotency_key: str) -> dict[str, str]:
    return {**AUTHORIZATION, "Idempotency-Key": idempotency_key}


def test_internal_routes_require_a_configured_token_and_stay_out_of_public_openapi(
    migrated_engine: Engine,
) -> None:
    disabled = _client(migrated_engine, enabled=False)
    assert disabled.get("/api/internal/v1/review/cases").status_code == 404

    client = _client(migrated_engine)
    assert client.get("/api/internal/v1/review/cases").status_code == 401
    assert client.get(
        "/api/internal/v1/review/cases",
        headers={"Authorization": "Bearer wrong-token"},
    ).status_code == 401
    assert client.get("/api/internal/v1/review/cases", headers=AUTHORIZATION).json() == []

    public_openapi = json.dumps(client.get("/openapi.json").json())
    assert "/api/internal/v1" not in public_openapi
    assert "InternalReviewCaseDetail" not in public_openapi
    assert client.get("/api/v1/programs").json() == {
        "items": [],
        "page": 1,
        "page_size": 20,
        "total": 0,
    }


def test_internal_queue_uses_a_reader_friendly_title_without_mutating_source_data(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        _, review_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="quoted-title",
            external_id="quoted-title-2026",
            title="«Креативный музей»",
        )

    client = _client(migrated_engine)
    queue = client.get("/api/internal/v1/review/cases", headers=AUTHORIZATION)
    assert queue.status_code == 200
    assert queue.json()[0]["review_case_id"] == str(review_case_id)
    assert queue.json()[0]["title"] == "Креативный музей"

    detail = client.get(f"/api/internal/v1/review/cases/{review_case_id}", headers=AUTHORIZATION)
    assert detail.status_code == 200
    assert detail.json()["source_record"]["title"] == "«Креативный музей»"
    assert detail.json()["public_preview"]["title"] == "Креативный музей"


def test_internal_accept_is_idempotent_and_public_api_sees_only_the_published_result(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        staged_record_id, review_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="internal-accept",
            external_id="internal-accept-2026",
        )

    client = _client(migrated_engine)
    queue = client.get("/api/internal/v1/review/cases", headers=AUTHORIZATION)
    assert queue.status_code == 200
    assert queue.json()[0]["review_case_id"] == str(review_case_id)
    assert queue.json()[0]["title"] == "Конкурс для региональных инициатив"
    assert queue.json()[0]["source_url"].endswith("/internal-accept")
    detail = client.get(f"/api/internal/v1/review/cases/{review_case_id}", headers=AUTHORIZATION)
    assert detail.status_code == 200
    assert detail.json()["staged_record_id"] == str(staged_record_id)
    assert detail.json()["title"] == "Конкурс для региональных инициатив"
    assert "s3://" not in detail.text

    request = {
        "action": "accept",
        "reason": "Поля подтверждены первоисточником.",
    }
    first = client.post(
        f"/api/internal/v1/review/cases/{review_case_id}/actions",
        headers=_request_headers("accept-once"),
        json=request,
    )
    replay = client.post(
        f"/api/internal/v1/review/cases/{review_case_id}/actions",
        headers=_request_headers("accept-once"),
        json=request,
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert first.json()["operation_id"] == replay.json()["operation_id"]
    assert first.json()["program_id"] is not None

    conflicting_reuse = client.post(
        f"/api/internal/v1/review/cases/{review_case_id}/actions",
        headers=_request_headers("accept-once"),
        json={"action": "accept", "reason": "Другая причина."},
    )
    assert conflicting_reuse.status_code == 409
    assert conflicting_reuse.json()["error"]["code"] == "idempotency_key_reused"

    program_id = UUID(first.json()["program_id"])
    public_result = client.get(f"/api/v1/programs/{program_id}")
    assert public_result.status_code == 200
    assert public_result.json()["publication_status"] == "published"

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(ReviewAction).where(
                ReviewAction.review_case_id == review_case_id
            )
        ) == 1
        assert connection.scalar(select(func.count()).select_from(OperatorOperation)) == 1
        operator_operation_id = connection.scalar(select(OperatorOperation.id))
        assert connection.scalar(
            select(Program.publication_status).where(Program.id == program_id)
        ) == PublicationStatus.PUBLISHED

    assert operator_operation_id is not None
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                update(OperatorOperation)
                .where(OperatorOperation.id == operator_operation_id)
                .values(result_payload={"changed": True})
            )


def test_internal_actions_enforce_transition_rules_without_partial_writes(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        blocked_staged_id, blocked_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="quality-blocked",
            external_id="quality-blocked-2026",
        )
        connection.execute(
            insert(DataQualityIssue).values(
                staged_record_id=blocked_staged_id,
                severity=DataQualitySeverity.ERROR,
                code="deadline_conflict",
                message="Источник содержит несовместимые сроки.",
            )
        )
        clarification_staged_id, clarification_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="clarification",
            external_id="clarification-2026",
        )
        reject_staged_id, reject_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="reject",
            external_id="reject-2026",
        )

    client = _client(migrated_engine)
    blocked = client.post(
        f"/api/internal/v1/review/cases/{blocked_case_id}/actions",
        headers=_request_headers("blocked-accept"),
        json={"action": "accept", "reason": "Пробуем принять запись с ошибкой."},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "review_transition_not_allowed"

    clarification = client.post(
        f"/api/internal/v1/review/cases/{clarification_case_id}/actions",
        headers=_request_headers("clarification-once"),
        json={"action": "needs_clarification", "reason": "Нужно подтвердить срок."},
    )
    assert clarification.status_code == 200
    repeated_clarification = client.post(
        f"/api/internal/v1/review/cases/{clarification_case_id}/actions",
        headers=_request_headers("clarification-again"),
        json={"action": "needs_clarification", "reason": "Повторный запрос."},
    )
    assert repeated_clarification.status_code == 409

    rejected = client.post(
        f"/api/internal/v1/review/cases/{reject_case_id}/actions",
        headers=_request_headers("reject-once"),
        json={"action": "reject", "reason": "Это не самостоятельная программа."},
    )
    assert rejected.status_code == 200

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == blocked_staged_id)
        ) is StagedRecordState.REVIEW
        assert connection.scalar(
            select(func.count()).select_from(ReviewAction).where(
                ReviewAction.review_case_id == blocked_case_id
            )
        ) == 0
        assert connection.scalar(
            select(func.count()).select_from(OperatorOperation).where(
                OperatorOperation.target_id == blocked_case_id
            )
        ) == 0
        assert connection.scalar(
            select(ReviewCase.status).where(ReviewCase.id == clarification_case_id)
        ) is ReviewCaseStatus.NEEDS_CLARIFICATION
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == reject_staged_id)
        ) is StagedRecordState.REJECTED


def test_internal_revisions_preserve_source_data_and_require_explicit_quality_resolution(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        connection.execute(
            insert(Theme).values(
                id=uuid4(),
                slug="culture",
                name="Культура",
            )
        )
        staged_record_id, review_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="operator-correction",
            external_id="operator-correction-2026",
        )
        issue_id = uuid4()
        connection.execute(
            insert(DataQualityIssue).values(
                id=issue_id,
                staged_record_id=staged_record_id,
                severity=DataQualitySeverity.ERROR,
                code="missing_verified_summary",
                message="Нужно сверить описание программы.",
            )
        )

    client = _client(migrated_engine)
    initial = client.get(
        f"/api/internal/v1/review/cases/{review_case_id}",
        headers=AUTHORIZATION,
    )
    assert initial.status_code == 200
    assert initial.json()["source_record"]["title"] == "Конкурс для региональных инициатив"
    assert initial.json()["effective_record"] == initial.json()["source_record"]
    assert initial.json()["public_preview"]["title"] == "Конкурс для региональных инициатив"
    assert "external_content_uri" not in initial.text
    assert "s3://" not in initial.text

    revision_request = {
        "reason": "Сверено с официальной страницей конкурса.",
        "patch": {
            "title": "Уточнённый конкурс для региональных инициатив",
            "summary": "Поддержка инициатив региональных организаций.",
            "source_published_on": "2026-09-01",
            "source_status": "open",
            "deadline_on": "2026-12-01",
            "funding": {
                "value_kind": "exact",
                "currency_code": "RUB",
                "exact_amount": "750000",
            },
            "application": {
                "url": "https://source.example.test/apply/operator-correction",
                "start_on": "2026-10-01",
                "end_on": "2026-12-01",
            },
            "eligibility": {
                "summary": "Участвуют некоммерческие организации России.",
                "geography_note": "Российская Федерация",
                "access_mode": "open",
            },
            "taxonomy": {
                "themes": [{"name": "Культура"}],
                "geographies": [{"slug": "russia", "name": "Россия"}],
            },
        },
        "resolve_issue_ids": [str(issue_id)],
    }
    first = client.post(
        f"/api/internal/v1/review/cases/{review_case_id}/revisions",
        headers=_request_headers("correction-once"),
        json=revision_request,
    )
    replay = client.post(
        f"/api/internal/v1/review/cases/{review_case_id}/revisions",
        headers=_request_headers("correction-once"),
        json=revision_request,
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert first.json()["review_revision_id"] == replay.json()["review_revision_id"]

    corrected = client.get(
        f"/api/internal/v1/review/cases/{review_case_id}",
        headers=AUTHORIZATION,
    )
    assert corrected.status_code == 200
    assert corrected.json()["source_record"]["title"] == "Конкурс для региональных инициатив"
    assert corrected.json()["effective_record"]["title"] == (
        "Уточнённый конкурс для региональных инициатив"
    )
    assert corrected.json()["public_preview"]["summary"] == (
        "Поддержка инициатив региональных организаций."
    )
    assert corrected.json()["public_preview"]["geographies"] == [
        {"slug": "russia", "name": "Россия"}
    ]
    assert corrected.json()["effective_record"]["payload"]["taxonomy"]["themes"] == [
        {"slug": "culture", "name": "Культура"}
    ]
    assert corrected.json()["quality_issues"][0]["resolution"]["review_revision_id"] == first.json()[
        "review_revision_id"
    ]

    revision_id = UUID(first.json()["review_revision_id"])
    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.candidate_payload).where(StagedRecord.id == staged_record_id)
        )["record"]["title"] == "Конкурс для региональных инициатив"
        assert connection.scalar(
            select(func.count()).select_from(ReviewRevision).where(
                ReviewRevision.review_case_id == review_case_id
            )
        ) == 1
        assert connection.scalar(
            select(func.count()).select_from(ReviewIssueResolution).where(
                ReviewIssueResolution.data_quality_issue_id == issue_id
            )
        ) == 1

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                update(StagedRecord)
                .where(StagedRecord.id == staged_record_id)
                .values(candidate_payload={"record": {"title": "Нельзя изменить"}})
            )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                update(ReviewRevision)
                .where(ReviewRevision.id == revision_id)
                .values(reason="Нельзя изменить")
            )

    accepted = client.post(
        f"/api/internal/v1/review/cases/{review_case_id}/actions",
        headers=_request_headers("correction-accept"),
        json={"action": "accept", "reason": "Исправленная версия проверена."},
    )
    assert accepted.status_code == 200
    program_id = accepted.json()["program_id"]
    assert program_id is not None
    public = client.get(f"/api/v1/programs/{program_id}")
    assert public.status_code == 200
    assert public.json()["title"] == "Уточнённый конкурс для региональных инициатив"
    assert public.json()["summary"] == "Поддержка инициатив региональных организаций."
    assert public.json()["geographies"] == [{"slug": "russia", "name": "Россия"}]


def test_internal_merge_rejects_a_candidate_without_deleting_match_history(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        _target_staged_id, _target_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="merge-target",
            external_id="merge-target-2026",
            record_url="https://source.example.test/competitions/merge-target",
        )
        candidate_staged_id, candidate_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="merge-candidate",
            external_id="merge-candidate-2026",
            record_url="https://source.example.test/competitions/merge-candidate",
        )
        match_id = connection.scalar(
            select(DeduplicationMatch.id).where(
                DeduplicationMatch.candidate_staged_record_id == candidate_staged_id
            )
        )

    assert match_id is not None
    client = _client(migrated_engine)
    merged = client.post(
        f"/api/internal/v1/review/cases/{candidate_case_id}/actions",
        headers=_request_headers("merge-once"),
        json={
            "action": "merge",
            "deduplication_match_id": str(match_id),
            "reason": "Это та же программа в другой карточке источника.",
        },
    )
    assert merged.status_code == 200
    assert merged.json()["program_id"] is None

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == candidate_staged_id)
        ) is StagedRecordState.REJECTED
        assert connection.scalar(
            select(func.count()).select_from(ReviewAction).where(
                ReviewAction.review_case_id == candidate_case_id
            )
        ) == 1


def test_internal_archive_and_republish_use_prior_review_evidence_and_are_idempotent(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        _staged_record_id, review_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="republish",
            external_id="republish-2026",
        )

    client = _client(migrated_engine)
    accepted = client.post(
        f"/api/internal/v1/review/cases/{review_case_id}/actions",
        headers=_request_headers("republish-accept"),
        json={"action": "accept", "reason": "Первичная публикация подтверждена."},
    )
    assert accepted.status_code == 200
    program_id = UUID(accepted.json()["program_id"])

    archive = client.post(
        f"/api/internal/v1/programs/{program_id}/archive",
        headers=_request_headers("archive-once"),
        json={"reason": "Официальная страница больше не актуальна."},
    )
    archive_replay = client.post(
        f"/api/internal/v1/programs/{program_id}/archive",
        headers=_request_headers("archive-once"),
        json={"reason": "Официальная страница больше не актуальна."},
    )
    assert archive.status_code == archive_replay.status_code == 200
    assert archive.json()["replayed"] is False
    assert archive_replay.json()["replayed"] is True
    assert archive.json()["program_publication_action_id"] == archive_replay.json()[
        "program_publication_action_id"
    ]
    assert client.get(f"/api/v1/programs/{program_id}").status_code == 404

    second_archive = client.post(
        f"/api/internal/v1/programs/{program_id}/archive",
        headers=_request_headers("archive-again"),
        json={"reason": "Повторное архивирование недопустимо."},
    )
    assert second_archive.status_code == 409

    first = client.post(
        f"/api/internal/v1/programs/{program_id}/republish",
        headers=_request_headers("republish-once"),
        json={"reason": "Карточка снова доступна у официального источника."},
    )
    replay = client.post(
        f"/api/internal/v1/programs/{program_id}/republish",
        headers=_request_headers("republish-once"),
        json={"reason": "Карточка снова доступна у официального источника."},
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert first.json()["program_publication_action_id"] == replay.json()[
        "program_publication_action_id"
    ]
    assert client.get(f"/api/v1/programs/{program_id}").status_code == 200

    second_republish = client.post(
        f"/api/internal/v1/programs/{program_id}/republish",
        headers=_request_headers("republish-again"),
        json={"reason": "Повтор без архивирования недопустим."},
    )
    assert second_republish.status_code == 409

    with migrated_engine.connect() as connection:
        publication_actions = list(
            connection.execute(
                select(ProgramPublicationAction.id, ProgramPublicationAction.action)
                .where(ProgramPublicationAction.program_id == program_id)
                .order_by(ProgramPublicationAction.created_at, ProgramPublicationAction.id)
            ).all()
        )
        assert [action.action for action in publication_actions] == ["archive", "republish"]
        with pytest.raises(IntegrityError):
            with migrated_engine.begin() as mutation_connection:
                mutation_connection.execute(
                    update(ProgramPublicationAction)
                    .where(ProgramPublicationAction.id == publication_actions[0].id)
                    .values(reason="изменено")
                )


def test_internal_discovery_actions_and_operational_reads_are_audited(
    migrated_engine: Engine,
) -> None:
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        staged_record_id, review_case_id = _review_case(
            connection,
            source_id=source_id,
            record_key="quality-read",
            external_id="quality-read-2026",
        )
        connection.execute(
            insert(DataQualityIssue).values(
                staged_record_id=staged_record_id,
                severity=DataQualitySeverity.WARNING,
                code="source_note",
                message="Нужно сверить дополнительное поле.",
            )
        )
        connection.execute(
            insert(SourceExecutionRun).values(
                id=uuid4(),
                source_id=source_id,
                source_key="fixture-catalog",
                trigger=SourceExecutionTrigger.MANUAL,
                status=SourceExecutionStatus.SUCCEEDED,
                owner_token=None,
                started_at=now,
                lease_expires_at=None,
                finished_at=now + timedelta(seconds=1),
                ingestion_run_id=None,
                attempt_count=1,
                result_kind="completed",
                metrics={"new": 1},
                error_codes=[],
            )
        )
        url_id = uuid4()
        connection.execute(
            insert(TelegramDiscoveryUrl).values(
                id=url_id,
                normalized_url="https://fixture.siderfold.test/catalog/example",
                route=TelegramDiscoveryRoute.MANUAL_REVIEW,
                target_source_key=None,
                manual_review_reason="no_registered_source",
                first_seen_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(days=90),
                seen_count=1,
            )
        )
        discovery_case_id = uuid4()
        connection.execute(
            insert(DiscoveryReviewCase).values(
                id=discovery_case_id,
                telegram_discovery_message_id=None,
                telegram_discovery_url_id=url_id,
                status=ReviewCaseStatus.OPEN,
                opened_snapshot={
                    "subject_type": "url",
                    "normalized_url": "https://fixture.siderfold.test/catalog/example",
                    "reason_codes": ["no_registered_source"],
                },
                opened_at=now,
                updated_at=now,
            )
        )

    client = _client(migrated_engine)
    assert client.get("/api/internal/v1/sources", headers=AUTHORIZATION).json()[0]["id"] == str(
        source_id
    )
    registered_sources = client.get(
        "/api/internal/v1/source-definitions",
        headers=AUTHORIZATION,
    )
    assert registered_sources.status_code == 200
    fixture_definition = next(
        item
        for item in registered_sources.json()
        if item["source_key"] == "fixture-catalog"
    )
    assert fixture_definition["adapter_name"] == "fixture-catalog"
    assert "secret_env_vars" not in fixture_definition
    runs = client.get("/api/internal/v1/runs", headers=AUTHORIZATION)
    assert runs.status_code == 200
    assert runs.json()[0]["source_key"] == "fixture-catalog"
    ingestion_runs = client.get("/api/internal/v1/ingestion-runs", headers=AUTHORIZATION)
    assert ingestion_runs.status_code == 200
    assert ingestion_runs.json()[0] == {
        "id": ANY,
        "source_id": str(source_id),
        "adapter_name": "fixture-adapter",
        "adapter_version": "1.0.0",
        "status": "completed",
        "received_at": ANY,
        "started_at": ANY,
        "finished_at": ANY,
        "raw_capture_count": 1,
        "staged_record_count": 1,
        "quality_issue_count": 1,
        "quality_error_count": 0,
        "run_statistics": {},
    }
    issues = client.get("/api/internal/v1/quality/issues", headers=AUTHORIZATION)
    assert issues.status_code == 200
    assert issues.json()[0]["review_case_id"] == str(review_case_id)

    linked = client.post(
        f"/api/internal/v1/discovery-review/cases/{discovery_case_id}/actions",
        headers=_request_headers("discovery-link"),
        json={
            "action": "link_to_registered_source",
            "source_key": "fixture-catalog",
            "reason": "URL соответствует уже разрешённому адаптеру.",
        },
    )
    replay = client.post(
        f"/api/internal/v1/discovery-review/cases/{discovery_case_id}/actions",
        headers=_request_headers("discovery-link"),
        json={
            "action": "link_to_registered_source",
            "source_key": "fixture-catalog",
            "reason": "URL соответствует уже разрешённому адаптеру.",
        },
    )
    assert linked.status_code == replay.status_code == 200
    assert linked.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert linked.json()["target_source_key"] == "fixture-catalog"

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(DiscoveryReviewAction).where(
                DiscoveryReviewAction.discovery_review_case_id == discovery_case_id
            )
        ) == 1

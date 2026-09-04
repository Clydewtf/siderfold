from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from sqlalchemy.engine import Connection, Engine

from app.api.v1.schemas import ProgramDetail
from app.domain.models import (
    ProgramContact,
    ProgramContentSection,
    ProgramDeadline,
    ProgramDetails,
    ProgramFunding,
    ProgramFundingAmount,
    ProgramResource,
    ProgramTimelineEvent,
    StagedRecord,
    StagedRecordState,
)
from app.main import create_app
from app.review.service import accept_review_case, evaluate_staged_record
from app.sources.adapters.potanin.parsing import parse_competition_page
from tests.fixtures.canonical import insert_source
from tests.fixtures.provenance import (
    finish_ingestion_run,
    insert_ingestion_run,
    insert_raw_capture,
    start_ingestion_run,
    transition_staged_record,
)


pytestmark = pytest.mark.postgres

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    BACKEND_ROOT
    / "tests"
    / "fixtures"
    / "adapters"
    / "potanin"
    / "sectioned-competition.html"
)
SOURCE_URL = "https://fondpotanin.ru/competitions/sectioned-quality-reference/"
MULTI_CYCLE_FIXTURE_PATH = (
    BACKEND_ROOT
    / "tests"
    / "fixtures"
    / "adapters"
    / "potanin"
    / "multi-cycle-schedule.html"
)
MULTI_CYCLE_SOURCE_URL = "https://fondpotanin.ru/competitions/quality-reference-multiple-cycles/"


def _review_ready_potanin_candidate(
    connection: Connection,
    *,
    source_id: UUID,
    fixture_path: Path = FIXTURE_PATH,
    source_url: str = SOURCE_URL,
) -> UUID:
    parsed = parse_competition_page(
        fixture_path.read_bytes(),
        source_url=source_url,
        sitemap_last_modified_at=None,
    )
    assert parsed.issues == ()

    run_id = insert_ingestion_run(connection, source_id=source_id)
    start_ingestion_run(connection, run_id=run_id)
    finish_ingestion_run(connection, run_id=run_id)
    raw_capture_id = insert_raw_capture(connection, ingestion_run_id=run_id)
    staged_record_id = uuid4()
    connection.execute(
        insert(StagedRecord).values(
            id=staged_record_id,
            raw_capture_id=raw_capture_id,
            record_key=source_url,
            candidate_payload={"record": parsed.record_payload},
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
    return staged_record_id


def test_review_acceptance_preserves_rich_source_data_without_exposing_contacts(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        staged_record_id = _review_ready_potanin_candidate(connection, source_id=source_id)
        review_case_id = evaluate_staged_record(connection, staged_record_id).review_case_id
        accepted = accept_review_case(
            connection,
            review_case_id,
            reason="Все извлечённые поля сверены с официальной страницей и документами.",
        )

    assert accepted.program_id is not None
    program_id = accepted.program_id
    with migrated_engine.connect() as connection:
        details = connection.execute(
            select(
                ProgramDetails.summary,
                ProgramDetails.source_published_on,
                ProgramDetails.application_start_on,
                ProgramDetails.application_end_on,
                ProgramDetails.access_mode,
            ).where(ProgramDetails.program_id == program_id)
        ).one()
        primary_funding = connection.execute(
            select(ProgramFunding.value_kind, ProgramFunding.max_amount).where(
                ProgramFunding.program_id == program_id
            )
        ).one()
        scoped_funding = {
            row.scope.value: row
            for row in connection.execute(
                select(
                    ProgramFundingAmount.scope,
                    ProgramFundingAmount.value_kind,
                    ProgramFundingAmount.exact_amount,
                    ProgramFundingAmount.max_amount,
                ).where(ProgramFundingAmount.program_id == program_id)
            )
        }
        timeline = connection.execute(
            select(ProgramTimelineEvent.event_kind, ProgramTimelineEvent.start_on, ProgramTimelineEvent.end_on)
            .where(ProgramTimelineEvent.program_id == program_id)
            .order_by(ProgramTimelineEvent.position)
        ).all()
        resources = connection.execute(
            select(ProgramResource.resource_kind, ProgramResource.url).where(
                ProgramResource.program_id == program_id
            )
        ).all()
        contacts = connection.execute(
            select(ProgramContact.name, ProgramContact.email, ProgramContact.is_public).where(
                ProgramContact.program_id == program_id
            )
        ).all()
        public_sections = connection.scalars(
            select(ProgramContentSection.content).where(
                ProgramContentSection.program_id == program_id,
                ProgramContentSection.is_public.is_(True),
            )
        ).all()

    assert details.summary.startswith("Поддержка российских организаций")
    assert details.source_published_on.isoformat() == "2023-08-01"
    assert details.application_start_on.isoformat() == "2023-09-01"
    assert details.application_end_on.isoformat() == "2023-09-20"
    assert details.access_mode.value == "invitation_only"
    assert primary_funding.value_kind.value == "maximum"
    assert str(primary_funding.max_amount) == "15000000.00"
    assert str(scoped_funding["announced_total"].exact_amount) == "150000000.00"
    assert str(scoped_funding["per_recipient"].max_amount) == "15000000.00"
    assert [item.event_kind.value for item in timeline] == [
        "application",
        "evaluation",
        "results",
        "contracting",
    ]
    assert any(url.endswith("winners.pdf") for _kind, url in resources)
    assert any(url.endswith("rules.pdf") for _kind, url in resources)
    assert contacts == [("Юлия Лизичева", "wecare@fondpotanin.ru", False)]
    assert all("wecare@fondpotanin.ru" not in section for section in public_sections)

    client = TestClient(create_app(engine=migrated_engine))
    response = client.get(f"/api/v1/programs/{program_id}")

    assert response.status_code == 200
    detail = ProgramDetail.model_validate(response.json())
    assert detail.source_published_on is not None
    assert detail.source_published_on.isoformat() == "2023-08-01"
    assert detail.summary is not None and detail.summary.startswith("Поддержка российских организаций")
    assert detail.application_start_on is not None
    assert detail.application_start_on.isoformat() == "2023-09-01"
    assert {amount.scope.value for amount in detail.funding_amounts} == {
        "announced_total",
        "per_recipient",
    }
    assert len(detail.timeline) == 4
    assert any(resource.url.endswith("winners.pdf") for resource in detail.resources)

    response_text = json.dumps(response.json())
    for private_or_internal_field in (
        "Юлия Лизичева",
        "wecare@fondpotanin.ru",
        "source_metadata",
        "evidence",
        "raw_capture",
        "candidate_payload",
        "review_decision",
    ):
        assert private_or_internal_field not in response_text


def test_review_acceptance_preserves_multiple_application_windows_without_a_fake_deadline(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        staged_record_id = _review_ready_potanin_candidate(
            connection,
            source_id=source_id,
            fixture_path=MULTI_CYCLE_FIXTURE_PATH,
            source_url=MULTI_CYCLE_SOURCE_URL,
        )
        review_case_id = evaluate_staged_record(connection, staged_record_id).review_case_id
        accepted = accept_review_case(
            connection,
            review_case_id,
            reason="Все циклы подачи и связанные этапы сверены с источником.",
        )

    assert accepted.program_id is not None
    with migrated_engine.connect() as connection:
        details = connection.execute(
            select(ProgramDetails.application_start_on, ProgramDetails.application_end_on).where(
                ProgramDetails.program_id == accepted.program_id
            )
        ).one()
        deadline = connection.scalar(
            select(ProgramDeadline.deadline_on).where(
                ProgramDeadline.program_id == accepted.program_id
            )
        )
        timeline = connection.execute(
            select(
                ProgramTimelineEvent.event_kind,
                ProgramTimelineEvent.label,
                ProgramTimelineEvent.start_on,
                ProgramTimelineEvent.end_on,
            )
            .where(ProgramTimelineEvent.program_id == accepted.program_id)
            .order_by(ProgramTimelineEvent.position)
        ).all()

    assert details == (None, None)
    assert deadline is None
    application_events = [event for event in timeline if event.event_kind.value == "application"]
    assert [(event.start_on.isoformat(), event.end_on.isoformat()) for event in application_events] == [
        ("2026-01-30", "2026-03-02"),
        ("2026-03-16", "2026-04-16"),
        ("2026-05-18", "2026-06-18"),
        ("2026-09-01", "2026-10-01"),
    ]
    assert len(timeline) == 12

    client = TestClient(create_app(engine=migrated_engine))
    response = client.get(f"/api/v1/programs/{accepted.program_id}")

    assert response.status_code == 200
    detail = ProgramDetail.model_validate(response.json())
    assert detail.deadline_on is None
    assert len(detail.timeline) == 12

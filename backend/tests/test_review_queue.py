from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.domain.models import (
    DataQualityIssue,
    DataQualitySeverity,
    DeduplicationMatch,
    DeduplicationMatchDisposition,
    DeduplicationMatchLevel,
    Program,
    ReviewAction,
    ReviewActionType,
    ReviewCase,
    ReviewCaseStatus,
    ReviewDecision,
    ReviewDecisionOutcome,
    StagedRecord,
    StagedRecordState,
)
from app.review.service import (
    ReviewPolicyError,
    accept_review_case,
    evaluate_staged_record,
    list_review_queue,
    merge_review_case,
    reject_review_case,
    request_clarification,
)
from app.review.deduplication import normalize_deduplication_url, normalize_text
from tests.fixtures.canonical import insert_source
from tests.fixtures.provenance import (
    finish_ingestion_run,
    insert_ingestion_run,
    insert_raw_capture,
    start_ingestion_run,
    transition_staged_record,
)


pytestmark = pytest.mark.postgres


def _review_candidate(
    connection: Connection,
    *,
    source_id: UUID,
    record_key: str,
    external_id: str | None = None,
    title: str = "Конкурс для региональных инициатив",
    organizer: str = "Фонд примеров",
    deadline_on: date = date(2026, 11, 30),
    record_url: str | None = None,
) -> UUID:
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
                    "deadline_on": deadline_on.isoformat(),
                    "external_id": external_id,
                    "funding": {
                        "value_kind": "maximum",
                        "currency_code": "RUB",
                        "max_amount": "500000",
                    },
                    "payload": {"organizer": organizer},
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
    return staged_record_id


def test_exact_external_id_auto_merges_only_a_clean_single_staging_match(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        first_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:regional:2026",
            external_id="regional-2026",
        )
        evaluate_staged_record(connection, first_id)
        duplicate_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:regional:2026:repeat",
            external_id="regional-2026",
        )
        result = evaluate_staged_record(connection, duplicate_id)

    assert result.auto_merged is True
    assert result.reason_codes == ("high_confidence_duplicate",)
    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == duplicate_id)
        ) == StagedRecordState.REJECTED
        match = connection.execute(
            select(
                DeduplicationMatch.match_level,
                DeduplicationMatch.disposition,
                DeduplicationMatch.target_staged_record_id,
            ).where(DeduplicationMatch.id == result.match_ids[0])
        ).one()
        assert match.match_level == DeduplicationMatchLevel.EXACT_EXTERNAL_ID
        assert match.disposition == DeduplicationMatchDisposition.AUTO_MERGED
        assert match.target_staged_record_id == first_id
        action = connection.execute(
            select(ReviewAction.action, ReviewAction.prior_values, ReviewAction.result_values)
            .where(ReviewAction.review_case_id == result.review_case_id)
        ).one()
        assert action.action == ReviewActionType.AUTO_MERGE
        assert action.prior_values["staged_record_state"] == "review"
        assert action.result_values["staged_record_state"] == "rejected"
        assert connection.scalar(select(func.count()).select_from(StagedRecord)) == 2
        assert connection.scalar(select(func.count()).select_from(Program)) == 0

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                update(DeduplicationMatch)
                .where(DeduplicationMatch.id == result.match_ids[0])
                .values(evidence={"changed": True})
            )


def test_exact_url_auto_merge_uses_a_deterministic_tracking_free_url_form(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        first_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:url:first",
            external_id="url-first",
            record_url="https://SOURCE.example.test/competitions/alpha/?utm_source=mail&b=2",
        )
        evaluate_staged_record(connection, first_id)
        duplicate_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:url:second",
            external_id="url-second",
            record_url="https://source.example.test/competitions//alpha?b=2#details",
        )
        result = evaluate_staged_record(connection, duplicate_id)

    assert result.auto_merged is True
    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(DeduplicationMatch.match_level).where(DeduplicationMatch.id == result.match_ids[0])
        ) == DeduplicationMatchLevel.EXACT_URL


def test_text_and_url_normalization_are_deterministic() -> None:
    assert normalize_text("  КОнкурс — Ёлка 2026! ") == "конкурс елка 2026"
    assert normalize_deduplication_url(
        "HTTPS://SOURCE.example.test/competitions//alpha/?b=2&utm_source=mail&a=1#details"
    ) == "https://source.example.test/competitions/alpha?a=1&b=2"


def test_normalized_fields_match_requires_review_and_creates_a_quality_warning(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        first_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:regional:first",
            external_id="regional-2026-a",
        )
        evaluate_staged_record(connection, first_id)
        possible_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:regional:second",
            external_id="regional-2026-b",
            record_url="https://source.example.test/other/record",
        )
        result = evaluate_staged_record(connection, possible_id)

    assert result.auto_merged is False
    assert "possible_duplicate" in result.reason_codes
    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == possible_id)
        ) == StagedRecordState.REVIEW
        assert connection.scalar(
            select(DeduplicationMatch.match_level).where(DeduplicationMatch.id == result.match_ids[0])
        ) == DeduplicationMatchLevel.NORMALIZED_FIELDS
        assert connection.scalar(
            select(DataQualityIssue.severity).where(
                DataQualityIssue.staged_record_id == possible_id,
                DataQualityIssue.code == "deduplication_possible_duplicate",
            )
        ) == DataQualitySeverity.WARNING
        assert connection.scalar(
            select(ReviewCase.status).where(ReviewCase.id == result.review_case_id)
        ) == ReviewCaseStatus.OPEN


def test_similar_title_with_different_organizer_stays_a_separate_candidate(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        first_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:regional:one",
            external_id="first-id",
        )
        evaluate_staged_record(connection, first_id)
        separate_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:regional:two",
            external_id="second-id",
            organizer="Другой организатор",
        )
        result = evaluate_staged_record(connection, separate_id)

    assert result.auto_merged is False
    assert result.match_ids == ()
    assert result.reason_codes == ("candidate_ready",)
    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == separate_id)
        ) == StagedRecordState.REVIEW
        assert connection.scalar(
            select(func.count())
            .select_from(DeduplicationMatch)
            .where(DeduplicationMatch.candidate_staged_record_id == separate_id)
        ) == 0


def test_exact_identity_with_conflicting_values_requires_manual_merge(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        target_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:regional:target",
            external_id="regional-2026",
        )
        evaluate_staged_record(connection, target_id)
        candidate_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:regional:changed",
            external_id="regional-2026",
            title="Конкурс для региональных инициатив: новая редакция",
        )
        evaluation = evaluate_staged_record(connection, candidate_id)
        review_case_id = evaluation.review_case_id
        match_id = evaluation.match_ids[0]

    assert evaluation.auto_merged is False
    assert "exact_identity_conflict" in evaluation.reason_codes
    with migrated_engine.begin() as connection:
        action = merge_review_case(
            connection,
            review_case_id,
            deduplication_match_id=match_id,
            reason="Источник подтверждает, что это обновление того же конкурса.",
        )

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == candidate_id)
        ) == StagedRecordState.REJECTED
        assert connection.scalar(
            select(ReviewCase.status).where(ReviewCase.id == review_case_id)
        ) == ReviewCaseStatus.RESOLVED
        stored_action = connection.execute(
            select(
                ReviewAction.action,
                ReviewAction.target_staged_record_id,
                ReviewAction.review_decision_id,
            ).where(ReviewAction.id == action.review_action_id)
        ).one()
        assert stored_action.action == ReviewActionType.MERGE
        assert stored_action.target_staged_record_id == target_id
        assert stored_action.review_decision_id is None


def test_duplicate_of_a_published_program_requires_review_instead_of_auto_merge(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        accepted_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:published",
            external_id="published-2026",
        )
        accepted_case = evaluate_staged_record(connection, accepted_id).review_case_id

    with migrated_engine.begin() as connection:
        accepted = accept_review_case(
            connection,
            accepted_case,
            reason="Первичная карточка подтверждена официальным источником.",
        )
        duplicate_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:published:repeat",
            external_id="published-2026",
            record_url="https://source.example.test/competitions/published-repeat",
        )
        evaluation = evaluate_staged_record(connection, duplicate_id)

    assert accepted.program_id is not None
    assert evaluation.auto_merged is False
    with migrated_engine.connect() as connection:
        match = connection.execute(
            select(
                DeduplicationMatch.match_level,
                DeduplicationMatch.target_program_id,
                DeduplicationMatch.disposition,
            ).where(DeduplicationMatch.id == evaluation.match_ids[0])
        ).one()
        assert match.match_level == DeduplicationMatchLevel.EXACT_EXTERNAL_ID
        assert match.target_program_id == accepted.program_id
        assert match.disposition == DeduplicationMatchDisposition.REVIEW_REQUIRED
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == duplicate_id)
        ) == StagedRecordState.REVIEW


def test_accept_reject_and_clarification_actions_keep_a_reproducible_history(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        accepted_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:accepted",
            external_id="accepted-2026",
        )
        accepted_case = evaluate_staged_record(connection, accepted_id).review_case_id
        rejected_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:rejected",
            external_id="rejected-2026",
        )
        rejected_case = evaluate_staged_record(connection, rejected_id).review_case_id
        clarification_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:clarification",
            external_id="clarification-2026",
        )
        clarification_case = evaluate_staged_record(connection, clarification_id).review_case_id

    with migrated_engine.begin() as connection:
        accepted = accept_review_case(
            connection,
            accepted_case,
            reason="Поля подтверждены официальным источником.",
        )
        rejected = reject_review_case(
            connection,
            rejected_case,
            reason="Материал не описывает самостоятельную программу.",
        )
        clarification = request_clarification(
            connection,
            clarification_case,
            reason="Нужно подтвердить срок приёма заявок.",
        )

    assert accepted.program_id is not None
    assert accepted.review_decision_id is not None
    assert rejected.review_decision_id is not None
    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(Program.publication_status).where(Program.id == accepted.program_id)
        ).value == "published"
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == accepted_id)
        ) == StagedRecordState.PUBLISHED
        assert connection.scalar(
            select(ReviewDecision.decision).where(ReviewDecision.id == accepted.review_decision_id)
        ) == ReviewDecisionOutcome.PUBLISH
        assert connection.scalar(
            select(ReviewDecision.decision).where(ReviewDecision.id == rejected.review_decision_id)
        ) == ReviewDecisionOutcome.REJECT
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == rejected_id)
        ) == StagedRecordState.REJECTED
        assert connection.scalar(
            select(ReviewCase.status).where(ReviewCase.id == clarification_case)
        ) == ReviewCaseStatus.NEEDS_CLARIFICATION
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == clarification_id)
        ) == StagedRecordState.REVIEW
        assert connection.scalar(
            select(ReviewAction.action).where(ReviewAction.id == clarification.review_action_id)
        ) == ReviewActionType.NEEDS_CLARIFICATION
        queue = list_review_queue(connection)
        assert [item.review_case_id for item in queue] == [clarification_case]

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                update(ReviewAction)
                .where(ReviewAction.id == accepted.review_action_id)
                .values(reason="Changed later")
            )


def test_quality_error_blocks_acceptance_but_not_the_audit_queue(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        staged_record_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:quality-error",
            external_id="quality-error-2026",
        )
        connection.execute(
            insert(DataQualityIssue).values(
                staged_record_id=staged_record_id,
                severity=DataQualitySeverity.ERROR,
                code="deadline_conflict",
                message="The source exposes incompatible application deadlines.",
            )
        )
        review_case_id = evaluate_staged_record(connection, staged_record_id).review_case_id

    with pytest.raises(ReviewPolicyError, match="quality errors"):
        with migrated_engine.begin() as connection:
            accept_review_case(
                connection,
                review_case_id,
                reason="This must not be accepted while an error is open.",
            )

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == staged_record_id)
        ) == StagedRecordState.REVIEW
        assert connection.scalar(
            select(ReviewCase.status).where(ReviewCase.id == review_case_id)
        ) == ReviewCaseStatus.OPEN
        assert connection.scalar(
            select(func.count())
            .select_from(ReviewAction)
            .where(ReviewAction.review_case_id == review_case_id)
        ) == 0


def test_review_operation_is_rolled_back_with_its_outer_transaction(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = insert_source(connection)
        staged_record_id = _review_candidate(
            connection,
            source_id=source_id,
            record_key="fund:rollback",
            external_id="rollback-2026",
        )
        review_case_id = evaluate_staged_record(connection, staged_record_id).review_case_id

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            accept_review_case(
                connection,
                review_case_id,
                reason="This transaction will fail after the review action.",
            )
            connection.execute(
                insert(Program).values(
                    id=uuid4(),
                    title="Broken deferred source link",
                    publication_status="draft",
                    primary_source_id=source_id,
                )
            )

    with migrated_engine.connect() as connection:
        assert connection.scalar(
            select(StagedRecord.state).where(StagedRecord.id == staged_record_id)
        ) == StagedRecordState.REVIEW
        assert connection.scalar(
            select(ReviewCase.status).where(ReviewCase.id == review_case_id)
        ) == ReviewCaseStatus.OPEN
        assert connection.scalar(select(func.count()).select_from(Program)) == 0
        assert connection.scalar(
            select(func.count())
            .select_from(ReviewAction)
            .where(ReviewAction.review_case_id == review_case_id)
        ) == 0

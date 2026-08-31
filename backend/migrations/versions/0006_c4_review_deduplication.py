"""Add deterministic deduplication and an auditable review queue.

Revision ID: 0006_c4_review_deduplication
Revises: 0005_telegram_discovery
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_c4_review_deduplication"
down_revision = "0005_telegram_discovery"
branch_labels = None
depends_on = None


deduplication_match_level = postgresql.ENUM(
    "exact_external_id",
    "exact_url",
    "normalized_fields",
    name="deduplication_match_level",
    create_type=False,
)

deduplication_match_disposition = postgresql.ENUM(
    "auto_merged",
    "review_required",
    name="deduplication_match_disposition",
    create_type=False,
)

review_case_status = postgresql.ENUM(
    "open",
    "needs_clarification",
    "resolved",
    name="review_case_status",
    create_type=False,
)

review_action_type = postgresql.ENUM(
    "accept",
    "reject",
    "merge",
    "needs_clarification",
    "auto_merge",
    name="review_action_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    deduplication_match_level.create(bind, checkfirst=True)
    deduplication_match_disposition.create(bind, checkfirst=True)
    review_case_status.create(bind, checkfirst=True)
    review_action_type.create(bind, checkfirst=True)

    op.create_table(
        "deduplication_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_staged_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_staged_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_program_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("match_level", deduplication_match_level, nullable=False),
        sa.Column("disposition", deduplication_match_disposition, nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(target_staged_record_id IS NOT NULL AND target_program_id IS NULL) "
            "OR (target_staged_record_id IS NULL AND target_program_id IS NOT NULL)",
            name="exactly_one_target",
        ),
        sa.CheckConstraint(
            "target_staged_record_id IS NULL "
            "OR candidate_staged_record_id <> target_staged_record_id",
            name="candidate_differs_from_staged_target",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_staged_record_id"],
            ["staged_records.id"],
            name="fk_dedup_matches_candidate_stage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_staged_record_id"],
            ["staged_records.id"],
            name="fk_dedup_matches_target_stage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_program_id"],
            ["programs.id"],
            name="fk_dedup_matches_target_program",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_deduplication_matches"),
    )
    op.create_index(
        "ix_deduplication_matches_candidate_created_at",
        "deduplication_matches",
        ["candidate_staged_record_id", "created_at"],
    )
    op.create_index(
        "ix_deduplication_matches_target_staged_record_id",
        "deduplication_matches",
        ["target_staged_record_id"],
    )
    op.create_index(
        "ix_deduplication_matches_target_program_id",
        "deduplication_matches",
        ["target_program_id"],
    )
    op.create_index(
        "uq_deduplication_matches_candidate_staged_target_level",
        "deduplication_matches",
        ["candidate_staged_record_id", "target_staged_record_id", "match_level"],
        unique=True,
        postgresql_where=sa.text("target_staged_record_id IS NOT NULL"),
    )
    op.create_index(
        "uq_deduplication_matches_candidate_program_target_level",
        "deduplication_matches",
        ["candidate_staged_record_id", "target_program_id", "match_level"],
        unique=True,
        postgresql_where=sa.text("target_program_id IS NOT NULL"),
    )

    op.create_table(
        "review_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staged_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            review_case_status,
            server_default=sa.text("'open'::review_case_status"),
            nullable=False,
        ),
        sa.Column(
            "opened_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(status IN ('open', 'needs_clarification') AND resolved_at IS NULL) "
            "OR (status = 'resolved' AND resolved_at IS NOT NULL)",
            name="resolution_timestamp_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["staged_record_id"],
            ["staged_records.id"],
            name="fk_review_cases_stage",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_cases"),
        sa.UniqueConstraint("staged_record_id", name="uq_review_cases_staged_record_id"),
    )
    op.create_index(
        "ix_review_cases_status_opened_at",
        "review_cases",
        ["status", "opened_at"],
    )

    op.create_table(
        "review_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", review_action_type, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("deduplication_match_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_staged_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_program_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "prior_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "result_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        sa.CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        sa.CheckConstraint(
            "(action IN ('merge', 'auto_merge') "
            "AND ((target_staged_record_id IS NOT NULL AND target_program_id IS NULL) "
            "OR (target_staged_record_id IS NULL AND target_program_id IS NOT NULL)) "
            "AND review_decision_id IS NULL) "
            "OR (action IN ('accept', 'reject') "
            "AND target_staged_record_id IS NULL AND target_program_id IS NULL "
            "AND review_decision_id IS NOT NULL) "
            "OR (action = 'needs_clarification' "
            "AND target_staged_record_id IS NULL AND target_program_id IS NULL "
            "AND review_decision_id IS NULL)",
            name="targets_match_action",
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id"],
            ["review_cases.id"],
            name="fk_review_actions_case",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deduplication_match_id"],
            ["deduplication_matches.id"],
            name="fk_review_actions_match",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_staged_record_id"],
            ["staged_records.id"],
            name="fk_review_actions_target_stage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_program_id"],
            ["programs.id"],
            name="fk_review_actions_target_program",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_decision_id"],
            ["review_decisions.id"],
            name="fk_review_actions_decision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_actions"),
    )
    op.create_index(
        "ix_review_actions_review_case_id_created_at",
        "review_actions",
        ["review_case_id", "created_at"],
    )
    op.create_index(
        "ix_review_actions_deduplication_match_id",
        "review_actions",
        ["deduplication_match_id"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_deduplication_match_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'deduplication matches are immutable'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER deduplication_matches_append_only
        BEFORE UPDATE OR DELETE ON deduplication_matches
        FOR EACH ROW
        EXECUTE FUNCTION prevent_deduplication_match_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_review_action_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'review actions are append-only'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_actions_append_only
        BEFORE UPDATE OR DELETE ON review_actions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_review_action_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_review_case_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            latest_action text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status::text <> 'open' OR NEW.resolved_at IS NOT NULL THEN
                    RAISE EXCEPTION 'review cases must start open'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.staged_record_id IS DISTINCT FROM OLD.staged_record_id
                OR NEW.opened_snapshot IS DISTINCT FROM OLD.opened_snapshot
                OR NEW.opened_at IS DISTINCT FROM OLD.opened_at THEN
                RAISE EXCEPTION 'review case identity and opening snapshot are immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;

            IF OLD.status::text = 'resolved' THEN
                RAISE EXCEPTION 'resolved review cases cannot change state'
                    USING ERRCODE = '23514';
            END IF;

            IF NOT (
                (OLD.status::text = 'open'
                    AND NEW.status::text IN ('needs_clarification', 'resolved'))
                OR (OLD.status::text = 'needs_clarification'
                    AND NEW.status::text = 'resolved')
            ) THEN
                RAISE EXCEPTION 'invalid review case transition: % -> %', OLD.status, NEW.status
                    USING ERRCODE = '23514';
            END IF;

            SELECT action::text INTO latest_action
            FROM review_actions
            WHERE review_case_id = NEW.id
            ORDER BY created_at DESC, id DESC
            LIMIT 1;

            IF NEW.status::text = 'needs_clarification'
                AND latest_action IS DISTINCT FROM 'needs_clarification' THEN
                RAISE EXCEPTION 'clarification state requires a matching review action'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.status::text = 'resolved'
                AND latest_action NOT IN ('accept', 'reject', 'merge', 'auto_merge') THEN
                RAISE EXCEPTION 'resolved state requires a terminal review action'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_cases_state_machine
        BEFORE INSERT OR UPDATE ON review_cases
        FOR EACH ROW
        EXECUTE FUNCTION enforce_review_case_transition();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_review_action_consistency()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            case_staged_record_id uuid;
            case_status text;
            staged_state text;
            decision_staged_record_id uuid;
            decision_outcome text;
            match_candidate_id uuid;
            match_target_staged_id uuid;
            match_target_program_id uuid;
            match_disposition text;
        BEGIN
            SELECT staged_record_id, status::text
            INTO case_staged_record_id, case_status
            FROM review_cases
            WHERE id = NEW.review_case_id;

            IF NOT FOUND OR case_status = 'resolved' THEN
                RAISE EXCEPTION 'review actions require an unresolved review case'
                    USING ERRCODE = '23514';
            END IF;

            SELECT state::text INTO staged_state
            FROM staged_records
            WHERE id = case_staged_record_id;
            IF staged_state IS DISTINCT FROM 'review' THEN
                RAISE EXCEPTION 'review actions require a staged record in review'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.action::text IN ('accept', 'reject') THEN
                SELECT staged_record_id, decision::text
                INTO decision_staged_record_id, decision_outcome
                FROM review_decisions
                WHERE id = NEW.review_decision_id;

                IF NOT FOUND
                    OR decision_staged_record_id IS DISTINCT FROM case_staged_record_id
                    OR decision_outcome IS DISTINCT FROM (
                        CASE WHEN NEW.action::text = 'accept' THEN 'publish' ELSE 'reject' END
                    ) THEN
                    RAISE EXCEPTION 'review action must reference its matching final decision'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF NEW.action::text IN ('merge', 'auto_merge') THEN
                SELECT
                    candidate_staged_record_id,
                    target_staged_record_id,
                    target_program_id,
                    disposition::text
                INTO
                    match_candidate_id,
                    match_target_staged_id,
                    match_target_program_id,
                    match_disposition
                FROM deduplication_matches
                WHERE id = NEW.deduplication_match_id;

                IF NOT FOUND
                    OR match_candidate_id IS DISTINCT FROM case_staged_record_id
                    OR match_target_staged_id IS DISTINCT FROM NEW.target_staged_record_id
                    OR match_target_program_id IS DISTINCT FROM NEW.target_program_id THEN
                    RAISE EXCEPTION 'merge action must reference an exact candidate match target'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.action::text = 'auto_merge'
                    AND (match_disposition IS DISTINCT FROM 'auto_merged' OR NEW.actor <> 'system') THEN
                    RAISE EXCEPTION 'automatic merges require a system-approved high-confidence match'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF NEW.deduplication_match_id IS NOT NULL THEN
                RAISE EXCEPTION 'non-merge review actions cannot reference a deduplication match'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_actions_consistency
        BEFORE INSERT ON review_actions
        FOR EACH ROW
        EXECUTE FUNCTION enforce_review_action_consistency();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS review_actions_consistency ON review_actions")
    op.execute("DROP TRIGGER IF EXISTS review_cases_state_machine ON review_cases")
    op.execute("DROP TRIGGER IF EXISTS review_actions_append_only ON review_actions")
    op.execute("DROP TRIGGER IF EXISTS deduplication_matches_append_only ON deduplication_matches")
    op.execute("DROP FUNCTION IF EXISTS enforce_review_action_consistency()")
    op.execute("DROP FUNCTION IF EXISTS enforce_review_case_transition()")
    op.execute("DROP FUNCTION IF EXISTS prevent_review_action_mutation()")
    op.execute("DROP FUNCTION IF EXISTS prevent_deduplication_match_mutation()")

    op.drop_index("ix_review_actions_deduplication_match_id", table_name="review_actions")
    op.drop_index("ix_review_actions_review_case_id_created_at", table_name="review_actions")
    op.drop_table("review_actions")
    op.drop_index("ix_review_cases_status_opened_at", table_name="review_cases")
    op.drop_table("review_cases")
    op.drop_index(
        "uq_deduplication_matches_candidate_program_target_level",
        table_name="deduplication_matches",
    )
    op.drop_index(
        "uq_deduplication_matches_candidate_staged_target_level",
        table_name="deduplication_matches",
    )
    op.drop_index(
        "ix_deduplication_matches_target_program_id",
        table_name="deduplication_matches",
    )
    op.drop_index(
        "ix_deduplication_matches_target_staged_record_id",
        table_name="deduplication_matches",
    )
    op.drop_index(
        "ix_deduplication_matches_candidate_created_at",
        table_name="deduplication_matches",
    )
    op.drop_table("deduplication_matches")

    bind = op.get_bind()
    review_action_type.drop(bind, checkfirst=True)
    review_case_status.drop(bind, checkfirst=True)
    deduplication_match_disposition.drop(bind, checkfirst=True)
    deduplication_match_level.drop(bind, checkfirst=True)

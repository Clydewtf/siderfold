"""Add immutable operator corrections for review candidates.

Revision ID: 0014_review_revisions
Revises: 0013_program_details_resources
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_review_revisions"
down_revision = "0013_program_details_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staged_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "effective_record",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "changed_fields",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "deduplication_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("revision_number > 0", name="revision_number_positive"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        sa.CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        sa.CheckConstraint("jsonb_typeof(effective_record) = 'object'", name="effective_record_is_object"),
        sa.CheckConstraint("jsonb_typeof(changed_fields) = 'array'", name="changed_fields_is_array"),
        sa.CheckConstraint(
            "jsonb_typeof(deduplication_snapshot) = 'object'",
            name="deduplication_snapshot_is_object",
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id"],
            ["review_cases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staged_record_id"],
            ["staged_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_case_id", "revision_number", name="uq_review_revisions_case_number"),
    )
    op.create_index(
        "ix_review_revisions_case_created",
        "review_revisions",
        ["review_case_id", "created_at"],
    )
    op.create_index(
        "ix_review_revisions_staged_record",
        "review_revisions",
        ["staged_record_id"],
    )

    op.create_table(
        "review_issue_resolutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("data_quality_issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        sa.CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        sa.ForeignKeyConstraint(
            ["review_revision_id"],
            ["review_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["data_quality_issue_id"],
            ["data_quality_issues.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data_quality_issue_id", name="uq_review_issue_resolutions_issue"),
    )
    op.create_index(
        "ix_review_issue_resolutions_revision",
        "review_issue_resolutions",
        ["review_revision_id"],
    )

    op.add_column(
        "operator_operations",
        sa.Column("review_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_operator_operations_review_revision",
        "operator_operations",
        "review_revisions",
        ["review_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "exactly_one_audit_action",
        "operator_operations",
        type_="check",
    )
    op.create_check_constraint(
        "exactly_one_audit_action",
        "operator_operations",
        "((review_action_id IS NOT NULL)::integer + "
        "(discovery_review_action_id IS NOT NULL)::integer + "
        "(program_publication_action_id IS NOT NULL)::integer + "
        "(review_revision_id IS NOT NULL)::integer) = 1",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_staged_record_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.state::text <> 'received' THEN
                    RAISE EXCEPTION 'staged records must start in received'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.raw_capture_id IS DISTINCT FROM OLD.raw_capture_id
                OR NEW.record_key IS DISTINCT FROM OLD.record_key
                OR NEW.candidate_payload IS DISTINCT FROM OLD.candidate_payload
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'staged record provenance is immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.state = OLD.state THEN
                RETURN NEW;
            END IF;

            IF (OLD.state::text = 'received' AND NEW.state::text IN ('extracted', 'error'))
                OR (OLD.state::text = 'extracted'
                    AND NEW.state::text IN ('warning', 'error', 'review'))
                OR (OLD.state::text = 'warning' AND NEW.state::text IN ('error', 'review'))
                OR (OLD.state::text = 'error' AND NEW.state::text = 'review')
                OR (OLD.state::text = 'review'
                    AND NEW.state::text IN ('published', 'rejected')) THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'invalid staged record transition: % -> %', OLD.state, NEW.state
                USING ERRCODE = '23514';
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE FUNCTION prevent_review_revision_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'review revisions are append-only'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_revisions_append_only
        BEFORE UPDATE OR DELETE ON review_revisions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_review_revision_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_review_issue_resolution_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'review issue resolutions are append-only'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_issue_resolutions_append_only
        BEFORE UPDATE OR DELETE ON review_issue_resolutions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_review_issue_resolution_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS review_issue_resolutions_append_only "
        "ON review_issue_resolutions"
    )
    op.execute("DROP TRIGGER IF EXISTS review_revisions_append_only ON review_revisions")
    op.execute("DROP FUNCTION IF EXISTS prevent_review_issue_resolution_mutation()")
    op.execute("DROP FUNCTION IF EXISTS prevent_review_revision_mutation()")

    op.execute(
        "ALTER TABLE operator_operations "
        "DISABLE TRIGGER operator_operations_append_only"
    )
    op.execute("DELETE FROM operator_operations WHERE review_revision_id IS NOT NULL")
    op.execute(
        "ALTER TABLE operator_operations "
        "ENABLE TRIGGER operator_operations_append_only"
    )

    op.drop_constraint("exactly_one_audit_action", "operator_operations", type_="check")
    op.create_check_constraint(
        "exactly_one_audit_action",
        "operator_operations",
        "((review_action_id IS NOT NULL)::integer + "
        "(discovery_review_action_id IS NOT NULL)::integer + "
        "(program_publication_action_id IS NOT NULL)::integer) = 1",
    )
    op.drop_constraint(
        "fk_operator_operations_review_revision",
        "operator_operations",
        type_="foreignkey",
    )
    op.drop_column("operator_operations", "review_revision_id")

    op.drop_index("ix_review_issue_resolutions_revision", table_name="review_issue_resolutions")
    op.drop_table("review_issue_resolutions")
    op.drop_index("ix_review_revisions_staged_record", table_name="review_revisions")
    op.drop_index("ix_review_revisions_case_created", table_name="review_revisions")
    op.drop_table("review_revisions")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_staged_record_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.state::text <> 'received' THEN
                    RAISE EXCEPTION 'staged records must start in received'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.raw_capture_id IS DISTINCT FROM OLD.raw_capture_id
                OR NEW.record_key IS DISTINCT FROM OLD.record_key
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'staged record identity is immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.state = OLD.state THEN
                RETURN NEW;
            END IF;

            IF (OLD.state::text = 'received' AND NEW.state::text IN ('extracted', 'error'))
                OR (OLD.state::text = 'extracted'
                    AND NEW.state::text IN ('warning', 'error', 'review'))
                OR (OLD.state::text = 'warning' AND NEW.state::text IN ('error', 'review'))
                OR (OLD.state::text = 'error' AND NEW.state::text = 'review')
                OR (OLD.state::text = 'review'
                    AND NEW.state::text IN ('published', 'rejected')) THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'invalid staged record transition: % -> %', OLD.state, NEW.state
                USING ERRCODE = '23514';
        END;
        $$;
        """
    )

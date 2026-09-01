"""Add protected operator action records and publication lifecycle audit history.

Revision ID: 0011_internal_moderation
Revises: 0010_analytics_snapshots
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_internal_moderation"
down_revision = "0010_analytics_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program_publication_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publication_review_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
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
        sa.CheckConstraint("action = 'republish'", name="only_republish_supported"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        sa.CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        sa.CheckConstraint("jsonb_typeof(prior_values) = 'object'", name="prior_values_is_object"),
        sa.CheckConstraint("jsonb_typeof(result_values) = 'object'", name="result_values_is_object"),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_publication_actions_program",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id"],
            ["review_cases.id"],
            name="fk_program_publication_actions_review_case",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["publication_review_decision_id"],
            ["review_decisions.id"],
            name="fk_program_publication_actions_decision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_program_publication_actions"),
    )
    op.create_index(
        "ix_program_publication_actions_program_created",
        "program_publication_actions",
        ["program_id", "created_at"],
    )
    op.create_index(
        "ix_program_publication_actions_review_case_created",
        "program_publication_actions",
        ["review_case_id", "created_at"],
    )

    op.create_table(
        "operator_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "result_payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("review_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("discovery_review_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("program_publication_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        sa.CheckConstraint("length(btrim(idempotency_key)) > 0", name="idempotency_key_not_blank"),
        sa.CheckConstraint("length(btrim(action)) > 0", name="action_not_blank"),
        sa.CheckConstraint("length(btrim(target_type)) > 0", name="target_type_not_blank"),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[a-f0-9]{64}$'",
            name="request_fingerprint_sha256",
        ),
        sa.CheckConstraint("jsonb_typeof(result_payload) = 'object'", name="result_payload_is_object"),
        sa.CheckConstraint(
            "((review_action_id IS NOT NULL)::integer + "
            "(discovery_review_action_id IS NOT NULL)::integer + "
            "(program_publication_action_id IS NOT NULL)::integer) = 1",
            name="exactly_one_audit_action",
        ),
        sa.ForeignKeyConstraint(
            ["review_action_id"],
            ["review_actions.id"],
            name="fk_operator_operations_review_action",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["discovery_review_action_id"],
            ["discovery_review_actions.id"],
            name="fk_operator_operations_discovery_action",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["program_publication_action_id"],
            ["program_publication_actions.id"],
            name="fk_operator_operations_publication_action",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operator_operations"),
        sa.UniqueConstraint("actor", "idempotency_key", name="uq_operator_operations_actor_key"),
    )
    op.create_index(
        "ix_operator_operations_target_created",
        "operator_operations",
        ["target_type", "target_id", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_program_publication_action_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'program publication actions are append-only'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER program_publication_actions_append_only
        BEFORE UPDATE OR DELETE ON program_publication_actions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_program_publication_action_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_operator_operation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'operator operations are append-only'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER operator_operations_append_only
        BEFORE UPDATE OR DELETE ON operator_operations
        FOR EACH ROW
        EXECUTE FUNCTION prevent_operator_operation_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS operator_operations_append_only ON operator_operations")
    op.execute(
        "DROP TRIGGER IF EXISTS program_publication_actions_append_only "
        "ON program_publication_actions"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_operator_operation_mutation()")
    op.execute("DROP FUNCTION IF EXISTS prevent_program_publication_action_mutation()")

    op.drop_index("ix_operator_operations_target_created", table_name="operator_operations")
    op.drop_table("operator_operations")
    op.drop_index(
        "ix_program_publication_actions_review_case_created",
        table_name="program_publication_actions",
    )
    op.drop_index(
        "ix_program_publication_actions_program_created",
        table_name="program_publication_actions",
    )
    op.drop_table("program_publication_actions")

"""Add local source execution journal and retry attempts.

Revision ID: 0008_c5_operations
Revises: 0007_discovery_review
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_c5_operations"
down_revision = "0007_discovery_review"
branch_labels = None
depends_on = None


source_execution_status = postgresql.ENUM(
    "running",
    "succeeded",
    "failed",
    "skipped_locked",
    "skipped_rate_limited",
    "interrupted",
    name="source_execution_status",
    create_type=False,
)

source_execution_trigger = postgresql.ENUM(
    "manual",
    "scheduled",
    name="source_execution_trigger",
    create_type=False,
)

source_execution_attempt_status = postgresql.ENUM(
    "succeeded",
    "failed",
    name="source_execution_attempt_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    source_execution_status.create(bind, checkfirst=True)
    source_execution_trigger.create(bind, checkfirst=True)
    source_execution_attempt_status.create(bind, checkfirst=True)

    op.create_table(
        "source_execution_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("trigger", source_execution_trigger, nullable=False),
        sa.Column("status", source_execution_status, nullable=False),
        sa.Column("owner_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("result_kind", sa.String(length=50), nullable=True),
        sa.Column(
            "metrics",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "error_codes",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(source_key)) > 0", name="source_key_not_blank"),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        sa.CheckConstraint(
            "result_kind IS NULL OR length(btrim(result_kind)) > 0",
            name="result_kind_not_blank",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND owner_token IS NOT NULL "
            "AND finished_at IS NULL AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at > started_at) "
            "OR (status IN ('succeeded', 'failed', 'skipped_locked', "
            "'skipped_rate_limited', 'interrupted') AND finished_at IS NOT NULL)",
            name="timestamps_match_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_source_execution_runs_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_source_execution_runs_ingestion_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_execution_runs"),
    )
    op.create_index(
        "ix_source_execution_runs_source_started",
        "source_execution_runs",
        ["source_id", "started_at"],
    )
    op.create_index(
        "ix_source_execution_runs_status_lease",
        "source_execution_runs",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "ix_source_execution_runs_ingestion_run",
        "source_execution_runs",
        ["ingestion_run_id"],
    )

    op.create_table(
        "source_execution_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_execution_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", source_execution_attempt_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retry_class", sa.String(length=32), nullable=True),
        sa.Column("backoff_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "error_codes",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        sa.CheckConstraint("finished_at >= started_at", name="finished_after_started"),
        sa.CheckConstraint(
            "retry_class IS NULL OR length(btrim(retry_class)) > 0",
            name="retry_class_not_blank",
        ),
        sa.CheckConstraint("backoff_seconds >= 0", name="backoff_nonnegative"),
        sa.ForeignKeyConstraint(
            ["source_execution_run_id"],
            ["source_execution_runs.id"],
            name="fk_source_execution_attempts_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_source_execution_attempts_ingestion_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_execution_attempts"),
        sa.UniqueConstraint(
            "source_execution_run_id",
            "attempt_number",
            name="uq_source_execution_attempts_run_number",
        ),
    )
    op.create_index(
        "ix_source_execution_attempts_run_created",
        "source_execution_attempts",
        ["source_execution_run_id", "created_at"],
    )
    op.create_index(
        "ix_source_execution_attempts_ingestion_run",
        "source_execution_attempts",
        ["ingestion_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_execution_attempts_ingestion_run",
        table_name="source_execution_attempts",
    )
    op.drop_index(
        "ix_source_execution_attempts_run_created",
        table_name="source_execution_attempts",
    )
    op.drop_table("source_execution_attempts")
    op.drop_index(
        "ix_source_execution_runs_ingestion_run",
        table_name="source_execution_runs",
    )
    op.drop_index(
        "ix_source_execution_runs_status_lease",
        table_name="source_execution_runs",
    )
    op.drop_index(
        "ix_source_execution_runs_source_started",
        table_name="source_execution_runs",
    )
    op.drop_table("source_execution_runs")

    bind = op.get_bind()
    source_execution_attempt_status.drop(bind, checkfirst=True)
    source_execution_trigger.drop(bind, checkfirst=True)
    source_execution_status.drop(bind, checkfirst=True)

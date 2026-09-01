"""Store immutable catalog quality snapshots.

Revision ID: 0010_analytics_snapshots
Revises: 0009_public_catalog_indexes
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_analytics_snapshots"
down_revision = "0009_public_catalog_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("calculation_version", sa.String(length=100), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness_window_days", sa.Integer(), nullable=False),
        sa.Column("registry_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "source_scope",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "input_manifest",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metrics",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "limitations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(scope)) > 0", name="scope_not_blank"),
        sa.CheckConstraint(
            "length(btrim(calculation_version)) > 0",
            name="calculation_version_not_blank",
        ),
        sa.CheckConstraint(
            "freshness_window_days >= 1 AND freshness_window_days <= 3650",
            name="freshness_window_days_in_range",
        ),
        sa.CheckConstraint(
            "registry_fingerprint ~ '^[a-f0-9]{64}$'",
            name="registry_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[a-f0-9]{64}$'",
            name="input_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_scope) = 'object'",
            name="source_scope_is_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(input_manifest) = 'object'",
            name="input_manifest_is_object",
        ),
        sa.CheckConstraint("jsonb_typeof(metrics) = 'object'", name="metrics_is_object"),
        sa.CheckConstraint(
            "jsonb_typeof(limitations) = 'array'",
            name="limitations_is_array",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analytics_snapshots"),
        sa.UniqueConstraint("input_fingerprint", name="uq_analytics_snapshots_input_fingerprint"),
    )
    op.create_index(
        "ix_analytics_snapshots_scope_as_of_id",
        "analytics_snapshots",
        ["scope", "as_of", "id"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_analytics_snapshot_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'analytics snapshots are immutable'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER analytics_snapshots_immutable
        BEFORE UPDATE OR DELETE ON analytics_snapshots
        FOR EACH ROW
        EXECUTE FUNCTION prevent_analytics_snapshot_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS analytics_snapshots_immutable ON analytics_snapshots")
    op.execute("DROP FUNCTION IF EXISTS prevent_analytics_snapshot_mutation()")
    op.drop_index("ix_analytics_snapshots_scope_as_of_id", table_name="analytics_snapshots")
    op.drop_table("analytics_snapshots")

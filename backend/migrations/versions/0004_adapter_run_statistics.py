"""Store sanitized adapter run statistics on ingestion runs.

Revision ID: 0004_adapter_run_statistics
Revises: 0003_b3_provenance
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_adapter_run_statistics"
down_revision = "0003_b3_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "run_statistics",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("ingestion_runs", "run_statistics")

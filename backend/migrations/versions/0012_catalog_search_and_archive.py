"""Add Russian title search, typo matching, and archival lifecycle actions.

Revision ID: 0012_catalog_search_and_archive
Revises: 0011_internal_moderation
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_catalog_search_and_archive"
down_revision = "0011_internal_moderation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.drop_index("ix_programs_title_search", table_name="programs")
    op.create_index(
        "ix_programs_title_search",
        "programs",
        [sa.text("to_tsvector('russian', title)")],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_programs_title_trigram",
        "programs",
        [sa.text("lower(title) gin_trgm_ops")],
        postgresql_using="gin",
    )

    op.drop_constraint(
        "only_republish_supported",
        "program_publication_actions",
        type_="check",
    )
    op.create_check_constraint(
        "publication_lifecycle_action_allowed",
        "program_publication_actions",
        "action IN ('archive', 'republish')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "publication_lifecycle_action_allowed",
        "program_publication_actions",
        type_="check",
    )
    op.create_check_constraint(
        "only_republish_supported",
        "program_publication_actions",
        "action IN ('archive', 'republish')",
    )

    op.drop_index("ix_programs_title_trigram", table_name="programs")
    op.drop_index("ix_programs_title_search", table_name="programs")
    op.create_index(
        "ix_programs_title_search",
        "programs",
        [sa.text("to_tsvector('simple', title)")],
        postgresql_using="gin",
    )

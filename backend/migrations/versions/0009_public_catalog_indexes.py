"""Add public catalog search and filter indexes.

Revision ID: 0009_public_catalog_indexes
Revises: 0008_c5_operations
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_public_catalog_indexes"
down_revision = "0008_c5_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_programs_publication_status_updated_at_id",
        "programs",
        ["publication_status", "updated_at", "id"],
    )
    op.create_index(
        "ix_programs_title_search",
        "programs",
        [sa.text("to_tsvector('simple', title)")],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_program_sources_source_id_program_id",
        "program_sources",
        ["source_id", "program_id"],
    )
    op.create_index(
        "ix_program_deadlines_deadline_on_program_id",
        "program_deadlines",
        ["deadline_on", "program_id"],
    )
    op.create_index(
        "ix_program_geographies_geography_id_program_id",
        "program_geographies",
        ["geography_id", "program_id"],
    )
    op.create_index(
        "ix_program_themes_theme_id_program_id",
        "program_themes",
        ["theme_id", "program_id"],
    )
    op.create_index(
        "ix_program_funding_value_kind_program_id",
        "program_funding",
        ["value_kind", "program_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_program_funding_value_kind_program_id",
        table_name="program_funding",
    )
    op.drop_index(
        "ix_program_themes_theme_id_program_id",
        table_name="program_themes",
    )
    op.drop_index(
        "ix_program_geographies_geography_id_program_id",
        table_name="program_geographies",
    )
    op.drop_index(
        "ix_program_deadlines_deadline_on_program_id",
        table_name="program_deadlines",
    )
    op.drop_index(
        "ix_program_sources_source_id_program_id",
        table_name="program_sources",
    )
    op.drop_index("ix_programs_title_search", table_name="programs")
    op.drop_index(
        "ix_programs_publication_status_updated_at_id",
        table_name="programs",
    )

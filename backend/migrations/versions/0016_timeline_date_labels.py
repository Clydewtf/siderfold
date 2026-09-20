"""Preserve publisher-visible labels for imprecise timeline dates.

Revision ID: 0016_timeline_date_labels
Revises: 0015_taxonomy_name_uniqueness
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_timeline_date_labels"
down_revision = "0015_taxonomy_name_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "program_timeline_events",
        sa.Column("date_label", sa.String(length=500), nullable=True),
    )
    op.drop_constraint(
        "timeline_event_has_date",
        "program_timeline_events",
        type_="check",
    )
    op.create_check_constraint(
        "timeline_event_has_date_or_label",
        "program_timeline_events",
        "start_on IS NOT NULL OR end_on IS NOT NULL OR date_label IS NOT NULL",
    )
    op.create_check_constraint(
        "timeline_event_date_label_not_blank",
        "program_timeline_events",
        "date_label IS NULL OR length(btrim(date_label)) > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "timeline_event_date_label_not_blank",
        "program_timeline_events",
        type_="check",
    )
    op.drop_constraint(
        "timeline_event_has_date_or_label",
        "program_timeline_events",
        type_="check",
    )
    # The previous schema cannot represent a source milestone that has only a
    # textual month/period. An explicit rollback must therefore discard only
    # these unrepresentable rows rather than invent a false calendar day.
    op.execute(
        "DELETE FROM program_timeline_events "
        "WHERE start_on IS NULL AND end_on IS NULL"
    )
    op.create_check_constraint(
        "timeline_event_has_date",
        "program_timeline_events",
        "start_on IS NOT NULL OR end_on IS NOT NULL",
    )
    op.drop_column("program_timeline_events", "date_label")

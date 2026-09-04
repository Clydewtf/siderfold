"""Store approved program details, timelines, resources, and scoped funding.

Revision ID: 0013_program_details_resources
Revises: 0012_catalog_search_and_archive
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_program_details_resources"
down_revision = "0012_catalog_search_and_archive"
branch_labels = None
depends_on = None


program_source_status = postgresql.ENUM(
    "unknown",
    "open",
    "closed",
    "completed",
    "upcoming",
    name="program_source_status",
    create_type=False,
)
program_access_mode = postgresql.ENUM(
    "unknown",
    "open",
    "invitation_only",
    name="program_access_mode",
    create_type=False,
)
program_timeline_event_kind = postgresql.ENUM(
    "application",
    "application_open",
    "application_close",
    "evaluation",
    "results",
    "contracting",
    "implementation",
    "other",
    name="program_timeline_event_kind",
    create_type=False,
)
program_funding_scope = postgresql.ENUM(
    "announced_total",
    "per_recipient",
    "per_program",
    "awarded_total",
    "other",
    name="program_funding_scope",
    create_type=False,
)
program_resource_kind = postgresql.ENUM(
    "application",
    "competition_document",
    "program_document",
    "result",
    "detail",
    "reference",
    name="program_resource_kind",
    create_type=False,
)
funding_value_kind = postgresql.ENUM(
    "exact",
    "minimum",
    "maximum",
    "range",
    "unknown",
    "not_stated",
    name="funding_value_kind",
    create_type=False,
)


def _funding_value_constraint() -> str:
    return (
        "(value_kind = 'exact' AND currency_code IS NOT NULL "
        "AND exact_amount IS NOT NULL AND exact_amount > 0 "
        "AND min_amount IS NULL AND max_amount IS NULL) "
        "OR (value_kind = 'minimum' AND currency_code IS NOT NULL "
        "AND exact_amount IS NULL AND min_amount IS NOT NULL AND min_amount > 0 "
        "AND max_amount IS NULL) "
        "OR (value_kind = 'maximum' AND currency_code IS NOT NULL "
        "AND exact_amount IS NULL AND min_amount IS NULL "
        "AND max_amount IS NOT NULL AND max_amount > 0) "
        "OR (value_kind = 'range' AND currency_code IS NOT NULL "
        "AND exact_amount IS NULL AND min_amount IS NOT NULL AND min_amount > 0 "
        "AND max_amount IS NOT NULL AND max_amount > 0 AND min_amount <= max_amount) "
        "OR (value_kind IN ('unknown', 'not_stated') AND currency_code IS NULL "
        "AND exact_amount IS NULL AND min_amount IS NULL AND max_amount IS NULL)"
    )


def upgrade() -> None:
    bind = op.get_bind()
    for enum in (
        program_source_status,
        program_access_mode,
        program_timeline_event_kind,
        program_funding_scope,
        program_resource_kind,
    ):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "program_details",
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("eligibility_summary", sa.Text(), nullable=True),
        sa.Column("eligibility_geography_note", sa.Text(), nullable=True),
        sa.Column("source_published_on", sa.Date(), nullable=True),
        sa.Column(
            "source_status",
            program_source_status,
            server_default=sa.text("'unknown'::program_source_status"),
            nullable=False,
        ),
        sa.Column(
            "access_mode",
            program_access_mode,
            server_default=sa.text("'unknown'::program_access_mode"),
            nullable=False,
        ),
        sa.Column("application_url", sa.String(length=2048), nullable=True),
        sa.Column("application_start_on", sa.Date(), nullable=True),
        sa.Column("application_end_on", sa.Date(), nullable=True),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "application_start_on IS NULL OR application_end_on IS NULL "
            "OR application_start_on <= application_end_on",
            name="application_dates_in_order",
        ),
        sa.CheckConstraint(
            "application_url IS NULL OR length(btrim(application_url)) > 0",
            name="application_url_not_blank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_metadata) = 'object'",
            name="source_metadata_is_object",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_details_program",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("program_id", name="pk_program_details"),
    )

    op.create_table(
        "program_timeline_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_kind", program_timeline_event_kind, nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("start_on", sa.Date(), nullable=True),
        sa.Column("end_on", sa.Date(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(btrim(label)) > 0", name="label_not_blank"),
        sa.CheckConstraint("position >= 0", name="position_nonnegative"),
        sa.CheckConstraint("start_on IS NOT NULL OR end_on IS NOT NULL", name="timeline_event_has_date"),
        sa.CheckConstraint(
            "start_on IS NULL OR end_on IS NULL OR start_on <= end_on",
            name="timeline_dates_in_order",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_timeline_events_program",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_program_timeline_events"),
        sa.UniqueConstraint("program_id", "position", name="uq_program_timeline_events_position"),
    )
    op.create_index(
        "ix_program_timeline_events_program_position",
        "program_timeline_events",
        ["program_id", "position"],
    )
    op.create_index(
        "ix_program_timeline_events_kind_end",
        "program_timeline_events",
        ["event_kind", "end_on"],
    )

    op.create_table(
        "program_funding_amounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", program_funding_scope, nullable=False),
        sa.Column("label", sa.String(length=500), nullable=True),
        sa.Column("value_kind", funding_value_kind, nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("exact_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("min_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("max_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="position_nonnegative"),
        sa.CheckConstraint(
            "label IS NULL OR length(btrim(label)) > 0",
            name="label_not_blank",
        ),
        sa.CheckConstraint(
            "currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'",
            name="currency_code_format",
        ),
        sa.CheckConstraint(_funding_value_constraint(), name="values_match_kind"),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_funding_amounts_program",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_program_funding_amounts"),
        sa.UniqueConstraint(
            "program_id",
            "scope",
            "position",
            name="uq_program_funding_amounts_scope_position",
        ),
    )
    op.create_index(
        "ix_program_funding_amounts_program_position",
        "program_funding_amounts",
        ["program_id", "position"],
    )
    op.create_index(
        "ix_program_funding_amounts_scope_kind",
        "program_funding_amounts",
        ["scope", "value_kind"],
    )

    op.create_table(
        "program_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_kind", program_resource_kind, nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("source_section", sa.String(length=500), nullable=True),
        sa.Column("content_format", sa.String(length=100), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(btrim(url)) > 0", name="url_not_blank"),
        sa.CheckConstraint("position >= 0", name="position_nonnegative"),
        sa.CheckConstraint(
            "title IS NULL OR length(btrim(title)) > 0",
            name="title_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_resources_program",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_program_resources"),
        sa.UniqueConstraint("program_id", "url", name="uq_program_resources_url"),
    )
    op.create_index(
        "ix_program_resources_program_position",
        "program_resources",
        ["program_id", "position"],
    )
    op.create_index("ix_program_resources_kind", "program_resources", ["resource_kind"])

    op.create_table(
        "program_content_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("heading", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(btrim(heading)) > 0", name="heading_not_blank"),
        sa.CheckConstraint("length(btrim(category)) > 0", name="category_not_blank"),
        sa.CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        sa.CheckConstraint("position >= 0", name="position_nonnegative"),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_content_sections_program",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_program_content_sections"),
        sa.UniqueConstraint("program_id", "position", name="uq_program_content_sections_position"),
    )
    op.create_index(
        "ix_program_content_sections_program_position",
        "program_content_sections",
        ["program_id", "position"],
    )
    op.create_index(
        "ix_program_content_sections_public_category",
        "program_content_sections",
        ["is_public", "category"],
    )

    op.create_table(
        "program_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("source_evidence", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        sa.CheckConstraint("position >= 0", name="position_nonnegative"),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_contacts_program",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_program_contacts"),
        sa.UniqueConstraint("program_id", "position", name="uq_program_contacts_position"),
    )
    op.create_index(
        "ix_program_contacts_program_position",
        "program_contacts",
        ["program_id", "position"],
    )


def downgrade() -> None:
    op.drop_table("program_contacts")
    op.drop_table("program_content_sections")
    op.drop_table("program_resources")
    op.drop_table("program_funding_amounts")
    op.drop_table("program_timeline_events")
    op.drop_table("program_details")

    bind = op.get_bind()
    for enum in (
        program_resource_kind,
        program_funding_scope,
        program_timeline_event_kind,
        program_access_mode,
        program_source_status,
    ):
        enum.drop(bind, checkfirst=True)

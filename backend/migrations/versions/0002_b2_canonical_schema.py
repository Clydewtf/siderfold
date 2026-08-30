"""Create the canonical program schema.

Revision ID: 0002_b2_canonical_schema
Revises: 0001_b1_baseline
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_b2_canonical_schema"
down_revision = "0001_b1_baseline"
branch_labels = None
depends_on = None


publication_status = postgresql.ENUM(
    "draft",
    "published",
    "archived",
    name="publication_status",
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


def upgrade() -> None:
    bind = op.get_bind()
    publication_status.create(bind, checkfirst=True)
    funding_value_kind.create(bind, checkfirst=True)

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("canonical_url", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        sa.CheckConstraint(
            "length(btrim(canonical_url)) > 0",
            name="canonical_url_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
        sa.UniqueConstraint("canonical_url", name="uq_sources_canonical_url"),
    )

    op.create_table(
        "programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column(
            "publication_status",
            publication_status,
            server_default=sa.text("'draft'::publication_status"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primary_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        sa.CheckConstraint(
            "(publication_status = 'draft' AND published_at IS NULL) "
            "OR (publication_status IN ('published', 'archived') AND published_at IS NOT NULL)",
            name="publication_timestamp_matches_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_programs"),
    )

    op.create_table(
        "geographies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.CheckConstraint("length(btrim(slug)) > 0", name="slug_not_blank"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_geographies"),
        sa.UniqueConstraint("slug", name="uq_geographies_slug"),
    )

    op.create_table(
        "themes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.CheckConstraint("length(btrim(slug)) > 0", name="slug_not_blank"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_themes"),
        sa.UniqueConstraint("slug", name="uq_themes_slug"),
    )

    op.create_table(
        "program_sources",
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(btrim(source_url)) > 0", name="source_url_not_blank"),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_sources_program_id_programs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_program_sources_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("program_id", "source_id", name="pk_program_sources"),
    )
    op.create_foreign_key(
        "fk_programs_primary_source_link",
        "programs",
        "program_sources",
        ["id", "primary_source_id"],
        ["program_id", "source_id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "program_deadlines",
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deadline_on", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_deadlines_program_id_programs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("program_id", name="pk_program_deadlines"),
    )

    op.create_table(
        "program_geographies",
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("geography_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_geographies_program_id_programs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["geography_id"],
            ["geographies.id"],
            name="fk_program_geographies_geography_id_geographies",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("program_id", "geography_id", name="pk_program_geographies"),
    )

    op.create_table(
        "program_themes",
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("theme_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_themes_program_id_programs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["theme_id"],
            ["themes.id"],
            name="fk_program_themes_theme_id_themes",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("program_id", "theme_id", name="pk_program_themes"),
    )

    op.create_table(
        "program_funding",
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value_kind", funding_value_kind, nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("exact_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("min_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("max_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.CheckConstraint(
            "currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'",
            name="currency_code_format",
        ),
        sa.CheckConstraint(
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
            "AND exact_amount IS NULL AND min_amount IS NULL AND max_amount IS NULL)",
            name="values_match_kind",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name="fk_program_funding_program_id_programs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("program_id", name="pk_program_funding"),
    )

    op.create_index(
        "ix_programs_publication_status_published_at",
        "programs",
        ["publication_status", "published_at"],
    )
    op.create_index("ix_program_sources_source_id", "program_sources", ["source_id"])
    op.create_index("ix_program_deadlines_deadline_on", "program_deadlines", ["deadline_on"])
    op.create_index("ix_program_geographies_geography_id", "program_geographies", ["geography_id"])
    op.create_index("ix_program_themes_theme_id", "program_themes", ["theme_id"])
    op.create_index(
        "ix_program_funding_value_kind_currency",
        "program_funding",
        ["value_kind", "currency_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_program_funding_value_kind_currency", table_name="program_funding")
    op.drop_index("ix_program_themes_theme_id", table_name="program_themes")
    op.drop_index("ix_program_geographies_geography_id", table_name="program_geographies")
    op.drop_index("ix_program_deadlines_deadline_on", table_name="program_deadlines")
    op.drop_index("ix_program_sources_source_id", table_name="program_sources")
    op.drop_index("ix_programs_publication_status_published_at", table_name="programs")

    op.drop_table("program_funding")
    op.drop_table("program_themes")
    op.drop_table("program_geographies")
    op.drop_table("program_deadlines")
    op.drop_constraint("fk_programs_primary_source_link", "programs", type_="foreignkey")
    op.drop_table("program_sources")
    op.drop_table("themes")
    op.drop_table("geographies")
    op.drop_table("programs")
    op.drop_table("sources")

    bind = op.get_bind()
    funding_value_kind.drop(bind, checkfirst=True)
    publication_status.drop(bind, checkfirst=True)

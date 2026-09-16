"""Keep one canonical public taxonomy entry per display name.

Revision ID: 0015_taxonomy_name_uniqueness
Revises: 0014_review_revisions
Create Date: 2026-09-15
"""

from alembic import op


revision = "0015_taxonomy_name_uniqueness"
down_revision = "0014_review_revisions"
branch_labels = None
depends_on = None


def _merge_duplicate_names(
    *,
    table_name: str,
    link_table: str,
    link_column: str,
) -> None:
    """Relink duplicate labels before enforcing normalized-name uniqueness."""

    op.execute(
        f"""
        WITH ranked AS (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY lower(btrim(name))
                    ORDER BY CASE WHEN slug LIKE 'manual-%' THEN 1 ELSE 0 END, slug, id
                ) AS canonical_id
            FROM {table_name}
        ),
        relinked AS (
            INSERT INTO {link_table} (program_id, {link_column})
            SELECT links.program_id, ranked.canonical_id
            FROM {link_table} AS links
            JOIN ranked ON ranked.id = links.{link_column}
            WHERE ranked.id <> ranked.canonical_id
            ON CONFLICT (program_id, {link_column}) DO NOTHING
        )
        DELETE FROM {link_table} AS links
        USING ranked
        WHERE links.{link_column} = ranked.id
          AND ranked.id <> ranked.canonical_id
        """
    )
    op.execute(
        f"""
        WITH ranked AS (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY lower(btrim(name))
                    ORDER BY CASE WHEN slug LIKE 'manual-%' THEN 1 ELSE 0 END, slug, id
                ) AS canonical_id
            FROM {table_name}
        )
        DELETE FROM {table_name} AS taxonomy
        USING ranked
        WHERE taxonomy.id = ranked.id
          AND ranked.id <> ranked.canonical_id
        """
    )


def upgrade() -> None:
    _merge_duplicate_names(
        table_name="themes",
        link_table="program_themes",
        link_column="theme_id",
    )
    _merge_duplicate_names(
        table_name="geographies",
        link_table="program_geographies",
        link_column="geography_id",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_themes_normalized_name "
        "ON themes (lower(btrim(name)))"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_geographies_normalized_name "
        "ON geographies (lower(btrim(name)))"
    )


def downgrade() -> None:
    op.drop_index("uq_geographies_normalized_name", table_name="geographies")
    op.drop_index("uq_themes_normalized_name", table_name="themes")

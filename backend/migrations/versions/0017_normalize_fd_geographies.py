"""Canonicalize federal-district geography aliases.

Revision ID: 0017_normalize_fd_geographies
Revises: 0016_timeline_date_labels
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Mapping

from alembic import op
import sqlalchemy as sa

from app.domain.geography import FEDERAL_DISTRICTS, normalize_geography_entry


revision = "0017_normalize_fd_geographies"
down_revision = "0016_timeline_date_labels"
branch_labels = None
depends_on = None


def _federal_district_for(row: Mapping[str, object]) -> tuple[str, str] | None:
    slug = str(row["slug"])
    name = str(row["name"])
    canonical = normalize_geography_entry(slug=slug, name=name)
    return canonical if canonical in FEDERAL_DISTRICTS else None


def upgrade() -> None:
    """Relink existing programs before deleting full-name alias rows.

    A program can already point at both an alias and the canonical geography.
    The link insert is therefore conflict-safe before the old link is removed.
    """

    bind = op.get_bind()
    rows = [
        dict(row)
        for row in bind.execute(
            sa.text("SELECT id, slug, name FROM geographies")
        ).mappings()
    ]

    for canonical_slug, canonical_name in FEDERAL_DISTRICTS:
        candidates = [
            row
            for row in rows
            if _federal_district_for(row) == (canonical_slug, canonical_name)
        ]
        if not candidates:
            continue

        target = next(
            (
                row
                for row in candidates
                if row["slug"] == canonical_slug and row["name"] == canonical_name
            ),
            next(
                (row for row in candidates if row["slug"] == canonical_slug),
                next(
                    (row for row in candidates if row["name"] == canonical_name),
                    candidates[0],
                ),
            ),
        )

        for alias in candidates:
            if alias["id"] == target["id"]:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO program_geographies (program_id, geography_id)
                    SELECT program_id, :target_id
                    FROM program_geographies
                    WHERE geography_id = :alias_id
                    ON CONFLICT (program_id, geography_id) DO NOTHING
                    """
                ),
                {"target_id": target["id"], "alias_id": alias["id"]},
            )
            bind.execute(
                sa.text("DELETE FROM program_geographies WHERE geography_id = :alias_id"),
                {"alias_id": alias["id"]},
            )
            bind.execute(
                sa.text("DELETE FROM geographies WHERE id = :alias_id"),
                {"alias_id": alias["id"]},
            )

        bind.execute(
            sa.text(
                "UPDATE geographies SET slug = :slug, name = :name WHERE id = :id"
            ),
            {"id": target["id"], "slug": canonical_slug, "name": canonical_name},
        )


def downgrade() -> None:
    # The pre-upgrade aliases are intentionally not recreated: their exact
    # spelling cannot be recovered after relinking existing program records.
    pass

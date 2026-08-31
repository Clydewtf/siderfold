"""Add bounded Telegram discovery records.

Revision ID: 0005_telegram_discovery
Revises: 0004_adapter_run_statistics
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_telegram_discovery"
down_revision = "0004_adapter_run_statistics"
branch_labels = None
depends_on = None


telegram_discovery_route = postgresql.ENUM(
    "source_adapter",
    "manual_review",
    name="telegram_discovery_route",
    create_type=False,
)

telegram_link_role = postgresql.ENUM(
    "possible_source",
    "registration",
    "other",
    name="telegram_link_role",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    telegram_discovery_route.create(bind, checkfirst=True)
    telegram_link_role.create(bind, checkfirst=True)

    op.create_table(
        "telegram_discovery_cursors",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_message_id", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("last_message_id > 0", name="last_message_id_positive"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_tg_cursor_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_id", name="pk_telegram_discovery_cursors"),
    )

    op.create_table(
        "telegram_discovery_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_capture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("message_url", sa.String(length=2048), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service_label", sa.String(length=280), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("review_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "discovery_issues",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("message_id > 0", name="message_id_positive"),
        sa.CheckConstraint("length(btrim(message_url)) > 0", name="message_url_not_blank"),
        sa.CheckConstraint(
            "service_label IS NULL OR length(btrim(service_label)) > 0",
            name="service_label_not_blank",
        ),
        sa.CheckConstraint("content_sha256 ~ '^[a-f0-9]{64}$'", name="content_sha256_format"),
        sa.CheckConstraint("last_observed_at >= received_at", name="observed_after_received"),
        sa.CheckConstraint("expires_at > received_at", name="expiry_after_received"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_tg_message_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_tg_message_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_capture_id"],
            ["raw_captures.id"],
            name="fk_tg_message_capture",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_discovery_messages"),
        sa.UniqueConstraint("source_id", "message_id", name="uq_telegram_messages_source_message"),
    )

    op.create_table(
        "telegram_discovery_urls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("route", telegram_discovery_route, nullable=False),
        sa.Column("target_source_key", sa.String(length=64), nullable=True),
        sa.Column("manual_review_reason", sa.String(length=100), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_count", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("length(btrim(normalized_url)) > 0", name="normalized_url_not_blank"),
        sa.CheckConstraint(
            "(route = 'source_adapter' AND target_source_key IS NOT NULL "
            "AND manual_review_reason IS NULL) "
            "OR (route = 'manual_review' AND target_source_key IS NULL "
            "AND manual_review_reason IS NOT NULL)",
            name="route_target_matches_state",
        ),
        sa.CheckConstraint(
            "manual_review_reason IS NULL OR length(btrim(manual_review_reason)) > 0",
            name="manual_review_reason_not_blank",
        ),
        sa.CheckConstraint("last_seen_at >= first_seen_at", name="last_seen_after_first_seen"),
        sa.CheckConstraint("expires_at > last_seen_at", name="expiry_after_last_seen"),
        sa.CheckConstraint("seen_count > 0", name="seen_count_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_discovery_urls"),
        sa.UniqueConstraint("normalized_url", name="uq_telegram_urls_normalized_url"),
    )

    op.create_table(
        "telegram_discovery_message_urls",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("discovery_url_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_role", telegram_link_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["telegram_discovery_messages.id"],
            name="fk_tg_message_url_message",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["discovery_url_id"],
            ["telegram_discovery_urls.id"],
            name="fk_tg_message_url_url",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "message_id",
            "discovery_url_id",
            name="pk_telegram_discovery_message_urls",
        ),
    )

    op.create_index(
        "ix_telegram_messages_source_expires",
        "telegram_discovery_messages",
        ["source_id", "expires_at"],
    )
    op.create_index(
        "ix_telegram_messages_review_expires",
        "telegram_discovery_messages",
        ["review_required", "expires_at"],
    )
    op.create_index(
        "ix_telegram_messages_raw_capture",
        "telegram_discovery_messages",
        ["raw_capture_id"],
    )
    op.create_index(
        "ix_telegram_urls_route_expires",
        "telegram_discovery_urls",
        ["route", "expires_at"],
    )
    op.create_index(
        "ix_telegram_message_urls_discovery_url",
        "telegram_discovery_message_urls",
        ["discovery_url_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_message_urls_discovery_url",
        table_name="telegram_discovery_message_urls",
    )
    op.drop_index("ix_telegram_urls_route_expires", table_name="telegram_discovery_urls")
    op.drop_index("ix_telegram_messages_raw_capture", table_name="telegram_discovery_messages")
    op.drop_index(
        "ix_telegram_messages_review_expires",
        table_name="telegram_discovery_messages",
    )
    op.drop_index(
        "ix_telegram_messages_source_expires",
        table_name="telegram_discovery_messages",
    )
    op.drop_table("telegram_discovery_message_urls")
    op.drop_table("telegram_discovery_urls")
    op.drop_table("telegram_discovery_messages")
    op.drop_table("telegram_discovery_cursors")

    bind = op.get_bind()
    telegram_link_role.drop(bind, checkfirst=True)
    telegram_discovery_route.drop(bind, checkfirst=True)

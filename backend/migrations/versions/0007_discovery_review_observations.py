"""Add discovery review tasks and append-only Telegram observations.

Revision ID: 0007_discovery_review
Revises: 0006_c4_review_deduplication
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_discovery_review"
down_revision = "0006_c4_review_deduplication"
branch_labels = None
depends_on = None


review_case_status = postgresql.ENUM(
    "open",
    "needs_clarification",
    "resolved",
    name="review_case_status",
    create_type=False,
)

discovery_review_action_type = postgresql.ENUM(
    "link_to_registered_source",
    "reject",
    "needs_clarification",
    name="discovery_review_action_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    discovery_review_action_type.create(bind, checkfirst=True)

    op.create_table(
        "telegram_discovery_message_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_discovery_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_capture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_url", sa.String(length=2048), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("length(btrim(message_url)) > 0", name="message_url"),
        sa.CheckConstraint(
            "service_label IS NULL OR length(btrim(service_label)) > 0",
            name="service_label",
        ),
        sa.CheckConstraint("content_sha256 ~ '^[a-f0-9]{64}$'", name="content_hash"),
        sa.CheckConstraint("expires_at > observed_at", name="expiry"),
        sa.ForeignKeyConstraint(
            ["telegram_discovery_message_id"],
            ["telegram_discovery_messages.id"],
            name="fk_tg_message_observations_message",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_tg_message_observations_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_capture_id"],
            ["raw_captures.id"],
            name="fk_tg_message_observations_capture",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_discovery_message_observations"),
        sa.UniqueConstraint(
            "telegram_discovery_message_id",
            "ingestion_run_id",
            name="uq_tg_message_observations_message_run",
        ),
    )
    op.create_index(
        "ix_tg_message_observations_message_observed",
        "telegram_discovery_message_observations",
        ["telegram_discovery_message_id", "observed_at"],
    )
    op.create_index(
        "ix_tg_message_observations_raw_capture",
        "telegram_discovery_message_observations",
        ["raw_capture_id"],
    )

    op.create_table(
        "discovery_review_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_discovery_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("telegram_discovery_url_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            review_case_status,
            server_default=sa.text("'open'::review_case_status"),
            nullable=False,
        ),
        sa.Column(
            "opened_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(telegram_discovery_message_id IS NOT NULL AND telegram_discovery_url_id IS NULL) "
            "OR (telegram_discovery_message_id IS NULL AND telegram_discovery_url_id IS NOT NULL)",
            name="exactly_one_subject",
        ),
        sa.CheckConstraint(
            "(status IN ('open', 'needs_clarification') AND resolved_at IS NULL) "
            "OR (status = 'resolved' AND resolved_at IS NOT NULL)",
            name="resolution_timestamp_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["telegram_discovery_message_id"],
            ["telegram_discovery_messages.id"],
            name="fk_discovery_review_cases_message",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["telegram_discovery_url_id"],
            ["telegram_discovery_urls.id"],
            name="fk_discovery_review_cases_url",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_discovery_review_cases"),
        sa.UniqueConstraint(
            "telegram_discovery_message_id",
            name="uq_discovery_review_cases_message",
        ),
        sa.UniqueConstraint(
            "telegram_discovery_url_id",
            name="uq_discovery_review_cases_url",
        ),
    )
    op.create_index(
        "ix_discovery_review_cases_status_opened",
        "discovery_review_cases",
        ["status", "opened_at"],
    )

    op.create_table(
        "discovery_review_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("discovery_review_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", discovery_review_action_type, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("target_source_key", sa.String(length=64), nullable=True),
        sa.Column(
            "prior_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "result_values",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        sa.CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        sa.CheckConstraint(
            "target_source_key IS NULL OR length(btrim(target_source_key)) > 0",
            name="target_source_key_not_blank",
        ),
        sa.CheckConstraint(
            "(action = 'link_to_registered_source' AND target_source_key IS NOT NULL) "
            "OR (action IN ('reject', 'needs_clarification') AND target_source_key IS NULL)",
            name="target_matches_action",
        ),
        sa.ForeignKeyConstraint(
            ["discovery_review_case_id"],
            ["discovery_review_cases.id"],
            name="fk_discovery_review_actions_case",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_discovery_review_actions"),
    )
    op.create_index(
        "ix_discovery_review_actions_case_created",
        "discovery_review_actions",
        ["discovery_review_case_id", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_telegram_discovery_message_provenance_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source_id IS DISTINCT FROM OLD.source_id
                OR NEW.ingestion_run_id IS DISTINCT FROM OLD.ingestion_run_id
                OR NEW.raw_capture_id IS DISTINCT FROM OLD.raw_capture_id
                OR NEW.message_id IS DISTINCT FROM OLD.message_id
                OR NEW.received_at IS DISTINCT FROM OLD.received_at
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'telegram discovery message identity and first provenance are immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER telegram_discovery_messages_preserve_first_provenance
        BEFORE UPDATE ON telegram_discovery_messages
        FOR EACH ROW
        EXECUTE FUNCTION prevent_telegram_discovery_message_provenance_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_telegram_discovery_message_observation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'telegram discovery observations are append-only'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER telegram_discovery_message_observations_append_only
        BEFORE UPDATE OR DELETE ON telegram_discovery_message_observations
        FOR EACH ROW
        EXECUTE FUNCTION prevent_telegram_discovery_message_observation_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_discovery_review_action_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'discovery review actions are append-only'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER discovery_review_actions_append_only
        BEFORE UPDATE OR DELETE ON discovery_review_actions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_discovery_review_action_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_discovery_review_case_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            latest_action text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status::text <> 'open' OR NEW.resolved_at IS NOT NULL THEN
                    RAISE EXCEPTION 'discovery review cases must start open'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.telegram_discovery_message_id IS DISTINCT FROM OLD.telegram_discovery_message_id
                OR NEW.telegram_discovery_url_id IS DISTINCT FROM OLD.telegram_discovery_url_id
                OR NEW.opened_snapshot IS DISTINCT FROM OLD.opened_snapshot
                OR NEW.opened_at IS DISTINCT FROM OLD.opened_at THEN
                RAISE EXCEPTION 'discovery review case identity and opening snapshot are immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;

            IF OLD.status::text = 'resolved' THEN
                RAISE EXCEPTION 'resolved discovery review cases cannot change state'
                    USING ERRCODE = '23514';
            END IF;

            IF NOT (
                (OLD.status::text = 'open'
                    AND NEW.status::text IN ('needs_clarification', 'resolved'))
                OR (OLD.status::text = 'needs_clarification'
                    AND NEW.status::text = 'resolved')
            ) THEN
                RAISE EXCEPTION 'invalid discovery review case transition: % -> %', OLD.status, NEW.status
                    USING ERRCODE = '23514';
            END IF;

            SELECT action::text INTO latest_action
            FROM discovery_review_actions
            WHERE discovery_review_case_id = NEW.id
            ORDER BY created_at DESC, id DESC
            LIMIT 1;

            IF NEW.status::text = 'needs_clarification'
                AND latest_action IS DISTINCT FROM 'needs_clarification' THEN
                RAISE EXCEPTION 'clarification state requires a matching discovery review action'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.status::text = 'resolved'
                AND latest_action NOT IN ('link_to_registered_source', 'reject') THEN
                RAISE EXCEPTION 'resolved state requires a terminal discovery review action'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER discovery_review_cases_state_machine
        BEFORE INSERT OR UPDATE ON discovery_review_cases
        FOR EACH ROW
        EXECUTE FUNCTION enforce_discovery_review_case_transition();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_discovery_review_action_consistency()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            case_status text;
            case_url_id uuid;
        BEGIN
            SELECT status::text, telegram_discovery_url_id
            INTO case_status, case_url_id
            FROM discovery_review_cases
            WHERE id = NEW.discovery_review_case_id;

            IF NOT FOUND OR case_status = 'resolved' THEN
                RAISE EXCEPTION 'discovery review actions require an unresolved review case'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.action::text = 'link_to_registered_source' AND case_url_id IS NULL THEN
                RAISE EXCEPTION 'only URL discovery cases can link to a source adapter'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER discovery_review_actions_consistency
        BEFORE INSERT ON discovery_review_actions
        FOR EACH ROW
        EXECUTE FUNCTION enforce_discovery_review_action_consistency();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS discovery_review_actions_consistency ON discovery_review_actions")
    op.execute("DROP TRIGGER IF EXISTS discovery_review_cases_state_machine ON discovery_review_cases")
    op.execute("DROP TRIGGER IF EXISTS discovery_review_actions_append_only ON discovery_review_actions")
    op.execute(
        "DROP TRIGGER IF EXISTS telegram_discovery_message_observations_append_only "
        "ON telegram_discovery_message_observations"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS telegram_discovery_messages_preserve_first_provenance "
        "ON telegram_discovery_messages"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_discovery_review_action_consistency()")
    op.execute("DROP FUNCTION IF EXISTS enforce_discovery_review_case_transition()")
    op.execute("DROP FUNCTION IF EXISTS prevent_discovery_review_action_mutation()")
    op.execute("DROP FUNCTION IF EXISTS prevent_telegram_discovery_message_observation_mutation()")
    op.execute("DROP FUNCTION IF EXISTS prevent_telegram_discovery_message_provenance_mutation()")

    op.drop_index(
        "ix_discovery_review_actions_case_created",
        table_name="discovery_review_actions",
    )
    op.drop_table("discovery_review_actions")
    op.drop_index(
        "ix_discovery_review_cases_status_opened",
        table_name="discovery_review_cases",
    )
    op.drop_table("discovery_review_cases")
    op.drop_index(
        "ix_tg_message_observations_raw_capture",
        table_name="telegram_discovery_message_observations",
    )
    op.drop_index(
        "ix_tg_message_observations_message_observed",
        table_name="telegram_discovery_message_observations",
    )
    op.drop_table("telegram_discovery_message_observations")

    bind = op.get_bind()
    discovery_review_action_type.drop(bind, checkfirst=True)

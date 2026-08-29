"""Add B3 raw, staging, and provenance records.

Revision ID: 0003_b3_provenance
Revises: 0002_b2_canonical_schema
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_b3_provenance"
down_revision = "0002_b2_canonical_schema"
branch_labels = None
depends_on = None


ingestion_run_status = postgresql.ENUM(
    "received",
    "processing",
    "completed",
    "failed",
    "duplicate",
    name="ingestion_run_status",
    create_type=False,
)

staged_record_state = postgresql.ENUM(
    "received",
    "extracted",
    "warning",
    "error",
    "review",
    "published",
    "rejected",
    name="staged_record_state",
    create_type=False,
)

data_quality_severity = postgresql.ENUM(
    "warning",
    "error",
    name="data_quality_severity",
    create_type=False,
)

review_decision_outcome = postgresql.ENUM(
    "publish",
    "reject",
    name="review_decision_outcome",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    has_untraced_published_programs = bind.scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM programs "
            "WHERE publication_status IN ('published', 'archived')"
            ")"
        )
    )
    if has_untraced_published_programs:
        raise RuntimeError(
            "B3 requires provenance for published programs. "
            "Backfill or archive published B2 rows before upgrading."
        )

    ingestion_run_status.create(bind, checkfirst=True)
    staged_record_state.create(bind, checkfirst=True)
    data_quality_severity.create(bind, checkfirst=True)
    review_decision_outcome.create(bind, checkfirst=True)

    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("adapter_name", sa.String(length=100), nullable=False),
        sa.Column("adapter_version", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            ingestion_run_status,
            server_default=sa.text("'received'::ingestion_run_status"),
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[a-f0-9]{64}$'",
            name="input_fingerprint_sha256",
        ),
        sa.CheckConstraint("length(btrim(adapter_name)) > 0", name="adapter_name_not_blank"),
        sa.CheckConstraint(
            "length(btrim(adapter_version)) > 0",
            name="adapter_version_not_blank",
        ),
        sa.CheckConstraint(
            "(status = 'received' AND started_at IS NULL AND finished_at IS NULL) "
            "OR (status = 'processing' AND started_at IS NOT NULL AND finished_at IS NULL) "
            "OR (status IN ('completed', 'failed') "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL) "
            "OR (status = 'duplicate' AND finished_at IS NOT NULL)",
            name="timestamps_match_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_ingestion_runs_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_runs"),
        sa.UniqueConstraint(
            "source_id",
            "input_fingerprint",
            name="uq_ingestion_runs_source_input_fingerprint_unique",
        ),
    )

    op.create_table(
        "raw_captures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_format", sa.String(length=100), nullable=False),
        sa.Column("adapter_name", sa.String(length=100), nullable=False),
        sa.Column("adapter_version", sa.String(length=100), nullable=False),
        sa.Column(
            "response_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("external_content_uri", sa.String(length=2048), nullable=False),
        sa.CheckConstraint("content_sha256 ~ '^[a-f0-9]{64}$'", name="content_sha256_format"),
        sa.CheckConstraint("length(btrim(source_url)) > 0", name="source_url_not_blank"),
        sa.CheckConstraint("length(btrim(content_format)) > 0", name="content_format_not_blank"),
        sa.CheckConstraint("length(btrim(adapter_name)) > 0", name="adapter_name_not_blank"),
        sa.CheckConstraint(
            "length(btrim(adapter_version)) > 0",
            name="adapter_version_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(external_content_uri)) > 0",
            name="external_content_uri_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_raw_captures_ingestion_run_id_ingestion_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_raw_captures"),
        sa.UniqueConstraint(
            "ingestion_run_id",
            "content_sha256",
            name="uq_raw_captures_run_content_sha256_unique",
        ),
    )

    op.create_table(
        "staged_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_capture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_key", sa.String(length=512), nullable=False),
        sa.Column(
            "candidate_payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "state",
            staged_record_state,
            server_default=sa.text("'received'::staged_record_state"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(record_key)) > 0", name="record_key_not_blank"),
        sa.ForeignKeyConstraint(
            ["raw_capture_id"],
            ["raw_captures.id"],
            name="fk_staged_records_raw_capture_id_raw_captures",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staged_records"),
        sa.UniqueConstraint(
            "raw_capture_id",
            "record_key",
            name="uq_staged_records_capture_record_key_unique",
        ),
    )

    op.create_table(
        "data_quality_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staged_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", data_quality_severity, nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(code)) > 0", name="code_not_blank"),
        sa.CheckConstraint("length(btrim(message)) > 0", name="message_not_blank"),
        sa.ForeignKeyConstraint(
            ["staged_record_id"],
            ["staged_records.id"],
            name="fk_data_quality_issues_staged_record_id_staged_records",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_data_quality_issues"),
        sa.UniqueConstraint(
            "staged_record_id",
            "code",
            name="uq_data_quality_issues_record_code_unique",
        ),
    )

    op.create_table(
        "review_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staged_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", review_decision_outcome, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        sa.ForeignKeyConstraint(
            ["staged_record_id"],
            ["staged_records.id"],
            name="fk_review_decisions_staged_record_id_staged_records",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_decisions"),
    )

    op.add_column(
        "programs",
        sa.Column("publication_review_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "ALTER TABLE programs "
        "ADD CONSTRAINT fk_programs_publication_review_decision_id_review_decisions "
        "FOREIGN KEY (publication_review_decision_id) "
        "REFERENCES review_decisions (id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE programs "
        "ADD CONSTRAINT uq_programs_publication_review_decision_id "
        "UNIQUE (publication_review_decision_id)"
    )
    op.execute(
        "ALTER TABLE programs "
        "ADD CONSTRAINT ck_programs_publication_review_matches_status "
        "CHECK ("
        "(publication_status = 'draft' AND publication_review_decision_id IS NULL) "
        "OR (publication_status IN ('published', 'archived') "
        "AND publication_review_decision_id IS NOT NULL)"
        ")"
    )

    op.create_index(
        "ix_ingestion_runs_source_id_status",
        "ingestion_runs",
        ["source_id", "status"],
    )
    op.create_index(
        "ix_raw_captures_ingestion_run_id_received_at",
        "raw_captures",
        ["ingestion_run_id", "received_at"],
    )
    op.create_index("ix_raw_captures_content_sha256", "raw_captures", ["content_sha256"])
    op.create_index(
        "ix_staged_records_raw_capture_id_state",
        "staged_records",
        ["raw_capture_id", "state"],
    )
    op.create_index(
        "ix_data_quality_issues_staged_record_id_severity",
        "data_quality_issues",
        ["staged_record_id", "severity"],
    )
    op.create_index(
        "ix_review_decisions_staged_record_id_decided_at",
        "review_decisions",
        ["staged_record_id", "decided_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_raw_capture_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'raw_captures are immutable'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER raw_captures_immutable
        BEFORE UPDATE OR DELETE ON raw_captures
        FOR EACH ROW
        EXECUTE FUNCTION prevent_raw_capture_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_ingestion_run_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status::text <> 'received' THEN
                    RAISE EXCEPTION 'ingestion runs must start in received'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.source_id IS DISTINCT FROM OLD.source_id
                OR NEW.input_fingerprint IS DISTINCT FROM OLD.input_fingerprint
                OR NEW.adapter_name IS DISTINCT FROM OLD.adapter_name
                OR NEW.adapter_version IS DISTINCT FROM OLD.adapter_version
                OR NEW.received_at IS DISTINCT FROM OLD.received_at THEN
                RAISE EXCEPTION 'ingestion run identity is immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;

            IF (OLD.status::text = 'received' AND NEW.status::text IN ('processing', 'duplicate'))
                OR (OLD.status::text = 'processing'
                    AND NEW.status::text IN ('completed', 'failed', 'duplicate')) THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'invalid ingestion run transition: % -> %', OLD.status, NEW.status
                USING ERRCODE = '23514';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ingestion_runs_state_machine
        BEFORE INSERT OR UPDATE ON ingestion_runs
        FOR EACH ROW
        EXECUTE FUNCTION enforce_ingestion_run_transition();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_staged_record_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.state::text <> 'received' THEN
                    RAISE EXCEPTION 'staged records must start in received'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.raw_capture_id IS DISTINCT FROM OLD.raw_capture_id
                OR NEW.record_key IS DISTINCT FROM OLD.record_key
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'staged record identity is immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.state = OLD.state THEN
                RETURN NEW;
            END IF;

            IF (OLD.state::text = 'received' AND NEW.state::text IN ('extracted', 'error'))
                OR (OLD.state::text = 'extracted'
                    AND NEW.state::text IN ('warning', 'error', 'review'))
                OR (OLD.state::text = 'warning' AND NEW.state::text IN ('error', 'review'))
                OR (OLD.state::text = 'error' AND NEW.state::text = 'review')
                OR (OLD.state::text = 'review'
                    AND NEW.state::text IN ('published', 'rejected')) THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'invalid staged record transition: % -> %', OLD.state, NEW.state
                USING ERRCODE = '23514';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER staged_records_state_machine
        BEFORE INSERT OR UPDATE ON staged_records
        FOR EACH ROW
        EXECUTE FUNCTION enforce_staged_record_transition();
        """
    )
    op.execute(
        """
        CREATE FUNCTION require_review_state_for_decision()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            staged_state text;
        BEGIN
            SELECT state::text INTO staged_state
            FROM staged_records
            WHERE id = NEW.staged_record_id;

            IF staged_state IS DISTINCT FROM 'review' THEN
                RAISE EXCEPTION 'review decisions require a staged record in review'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_decisions_require_review
        BEFORE INSERT ON review_decisions
        FOR EACH ROW
        EXECUTE FUNCTION require_review_state_for_decision();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_review_decision_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'review decisions are append-only'
                USING ERRCODE = '23514';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_decisions_append_only
        BEFORE UPDATE OR DELETE ON review_decisions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_review_decision_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION ensure_published_program_provenance()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            review_outcome text;
            staged_state text;
            run_status text;
            provenance_source_id uuid;
        BEGIN
            IF NEW.publication_status::text NOT IN ('published', 'archived') THEN
                RETURN NEW;
            END IF;

            SELECT
                decision.decision::text,
                staged.state::text,
                run.status::text,
                run.source_id
            INTO review_outcome, staged_state, run_status, provenance_source_id
            FROM review_decisions AS decision
            JOIN staged_records AS staged ON staged.id = decision.staged_record_id
            JOIN raw_captures AS capture ON capture.id = staged.raw_capture_id
            JOIN ingestion_runs AS run ON run.id = capture.ingestion_run_id
            WHERE decision.id = NEW.publication_review_decision_id;

            IF NOT FOUND
                OR review_outcome IS DISTINCT FROM 'publish'
                OR staged_state IS DISTINCT FROM 'published'
                OR run_status IS DISTINCT FROM 'completed'
                OR provenance_source_id IS DISTINCT FROM NEW.primary_source_id THEN
                RAISE EXCEPTION 'published programs require a completed, reviewed provenance chain'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER programs_published_provenance
        AFTER INSERT OR UPDATE ON programs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION ensure_published_program_provenance();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS programs_published_provenance ON programs")
    op.execute("DROP TRIGGER IF EXISTS review_decisions_append_only ON review_decisions")
    op.execute("DROP TRIGGER IF EXISTS review_decisions_require_review ON review_decisions")
    op.execute("DROP TRIGGER IF EXISTS staged_records_state_machine ON staged_records")
    op.execute("DROP TRIGGER IF EXISTS ingestion_runs_state_machine ON ingestion_runs")
    op.execute("DROP TRIGGER IF EXISTS raw_captures_immutable ON raw_captures")

    op.execute("DROP FUNCTION IF EXISTS ensure_published_program_provenance()")
    op.execute("DROP FUNCTION IF EXISTS prevent_review_decision_mutation()")
    op.execute("DROP FUNCTION IF EXISTS require_review_state_for_decision()")
    op.execute("DROP FUNCTION IF EXISTS enforce_staged_record_transition()")
    op.execute("DROP FUNCTION IF EXISTS enforce_ingestion_run_transition()")
    op.execute("DROP FUNCTION IF EXISTS prevent_raw_capture_mutation()")

    op.execute(
        "ALTER TABLE programs "
        "DROP CONSTRAINT IF EXISTS ck_programs_publication_review_matches_status"
    )
    op.execute(
        "ALTER TABLE programs "
        "DROP CONSTRAINT IF EXISTS uq_programs_publication_review_decision_id"
    )
    op.execute(
        "ALTER TABLE programs "
        "DROP CONSTRAINT IF EXISTS fk_programs_publication_review_decision_id_review_decisions"
    )
    op.drop_column("programs", "publication_review_decision_id")

    op.drop_index(
        "ix_review_decisions_staged_record_id_decided_at",
        table_name="review_decisions",
    )
    op.drop_index(
        "ix_data_quality_issues_staged_record_id_severity",
        table_name="data_quality_issues",
    )
    op.drop_index(
        "ix_staged_records_raw_capture_id_state",
        table_name="staged_records",
    )
    op.drop_index("ix_raw_captures_content_sha256", table_name="raw_captures")
    op.drop_index(
        "ix_raw_captures_ingestion_run_id_received_at",
        table_name="raw_captures",
    )
    op.drop_index("ix_ingestion_runs_source_id_status", table_name="ingestion_runs")

    op.drop_table("review_decisions")
    op.drop_table("data_quality_issues")
    op.drop_table("staged_records")
    op.drop_table("raw_captures")
    op.drop_table("ingestion_runs")

    bind = op.get_bind()
    review_decision_outcome.drop(bind, checkfirst=True)
    data_quality_severity.drop(bind, checkfirst=True)
    staged_record_state.drop(bind, checkfirst=True)
    ingestion_run_status.drop(bind, checkfirst=True)

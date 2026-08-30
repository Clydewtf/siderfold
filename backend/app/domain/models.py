from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PublicationStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class FundingValueKind(StrEnum):
    EXACT = "exact"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    RANGE = "range"
    UNKNOWN = "unknown"
    NOT_STATED = "not_stated"


class IngestionRunStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DUPLICATE = "duplicate"


class StagedRecordState(StrEnum):
    RECEIVED = "received"
    EXTRACTED = "extracted"
    WARNING = "warning"
    ERROR = "error"
    REVIEW = "review"
    PUBLISHED = "published"
    REJECTED = "rejected"


class DataQualitySeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class ReviewDecisionOutcome(StrEnum):
    PUBLISH = "publish"
    REJECT = "reject"


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


publication_status_enum = Enum(
    PublicationStatus,
    name="publication_status",
    native_enum=True,
    values_callable=_enum_values,
)

funding_value_kind_enum = Enum(
    FundingValueKind,
    name="funding_value_kind",
    native_enum=True,
    values_callable=_enum_values,
)

ingestion_run_status_enum = Enum(
    IngestionRunStatus,
    name="ingestion_run_status",
    native_enum=True,
    values_callable=_enum_values,
)

staged_record_state_enum = Enum(
    StagedRecordState,
    name="staged_record_state",
    native_enum=True,
    values_callable=_enum_values,
)

data_quality_severity_enum = Enum(
    DataQualitySeverity,
    name="data_quality_severity",
    native_enum=True,
    values_callable=_enum_values,
)

review_decision_outcome_enum = Enum(
    ReviewDecisionOutcome,
    name="review_decision_outcome",
    native_enum=True,
    values_callable=_enum_values,
)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("length(btrim(canonical_url)) > 0", name="canonical_url_not_blank"),
        UniqueConstraint("canonical_url", name="uq_sources_canonical_url"),
    )


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    publication_status: Mapped[PublicationStatus] = mapped_column(
        publication_status_enum,
        nullable=False,
        default=PublicationStatus.DRAFT,
        server_default=PublicationStatus.DRAFT.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_review_decision_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("review_decisions.id", ondelete="RESTRICT"),
    )
    primary_source_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint(
            "(publication_status = 'draft' AND published_at IS NULL) "
            "OR (publication_status IN ('published', 'archived') AND published_at IS NOT NULL)",
            name="publication_timestamp_matches_status",
        ),
        CheckConstraint(
            "(publication_status = 'draft' AND publication_review_decision_id IS NULL) "
            "OR (publication_status IN ('published', 'archived') "
            "AND publication_review_decision_id IS NOT NULL)",
            name="publication_review_matches_status",
        ),
        UniqueConstraint(
            "publication_review_decision_id",
            name="uq_programs_publication_review_decision_id",
        ),
        ForeignKeyConstraint(
            ["id", "primary_source_id"],
            ["program_sources.program_id", "program_sources.source_id"],
            name="primary_source_link",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_programs_publication_status_published_at",
            "publication_status",
            "published_at",
        ),
    )


class ProgramSource(Base):
    __tablename__ = "program_sources"

    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(source_url)) > 0", name="source_url_not_blank"),
        Index("ix_program_sources_source_id", "source_id"),
    )


class ProgramDeadline(Base):
    __tablename__ = "program_deadlines"

    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    deadline_on: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (Index("ix_program_deadlines_deadline_on", "deadline_on"),)


class Geography(Base):
    __tablename__ = "geographies"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(slug)) > 0", name="slug_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        UniqueConstraint("slug", name="uq_geographies_slug"),
    )


class ProgramGeography(Base):
    __tablename__ = "program_geographies"

    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    geography_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("geographies.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    __table_args__ = (Index("ix_program_geographies_geography_id", "geography_id"),)


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(slug)) > 0", name="slug_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        UniqueConstraint("slug", name="uq_themes_slug"),
    )


class ProgramTheme(Base):
    __tablename__ = "program_themes"

    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    theme_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("themes.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    __table_args__ = (Index("ix_program_themes_theme_id", "theme_id"),)


class ProgramFunding(Base):
    __tablename__ = "program_funding"

    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    value_kind: Mapped[FundingValueKind] = mapped_column(funding_value_kind_enum, nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    exact_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    __table_args__ = (
        CheckConstraint(
            "currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'",
            name="currency_code_format",
        ),
        CheckConstraint(
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
        Index(
            "ix_program_funding_value_kind_currency",
            "value_kind",
            "currency_code",
        ),
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[IngestionRunStatus] = mapped_column(
        ingestion_run_status_enum,
        nullable=False,
        default=IngestionRunStatus.RECEIVED,
        server_default=IngestionRunStatus.RECEIVED.value,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_statistics: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        CheckConstraint(
            "input_fingerprint ~ '^[a-f0-9]{64}$'",
            name="input_fingerprint_sha256",
        ),
        CheckConstraint("length(btrim(adapter_name)) > 0", name="adapter_name_not_blank"),
        CheckConstraint(
            "length(btrim(adapter_version)) > 0",
            name="adapter_version_not_blank",
        ),
        CheckConstraint(
            "(status = 'received' AND started_at IS NULL AND finished_at IS NULL) "
            "OR (status = 'processing' AND started_at IS NOT NULL AND finished_at IS NULL) "
            "OR (status IN ('completed', 'failed') "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL) "
            "OR (status = 'duplicate' AND finished_at IS NOT NULL)",
            name="timestamps_match_status",
        ),
        UniqueConstraint(
            "source_id",
            "input_fingerprint",
            name="uq_ingestion_runs_source_input_fingerprint_unique",
        ),
        Index("ix_ingestion_runs_source_id_status", "source_id", "status"),
    )


class RawCapture(Base):
    __tablename__ = "raw_captures"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_format: Mapped[str] = mapped_column(String(100), nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(100), nullable=False)
    response_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    external_content_uri: Mapped[str] = mapped_column(String(2048), nullable=False)

    __table_args__ = (
        CheckConstraint("content_sha256 ~ '^[a-f0-9]{64}$'", name="content_sha256_format"),
        CheckConstraint("length(btrim(source_url)) > 0", name="source_url_not_blank"),
        CheckConstraint("length(btrim(content_format)) > 0", name="content_format_not_blank"),
        CheckConstraint("length(btrim(adapter_name)) > 0", name="adapter_name_not_blank"),
        CheckConstraint(
            "length(btrim(adapter_version)) > 0",
            name="adapter_version_not_blank",
        ),
        CheckConstraint(
            "length(btrim(external_content_uri)) > 0",
            name="external_content_uri_not_blank",
        ),
        UniqueConstraint(
            "ingestion_run_id",
            "content_sha256",
            name="uq_raw_captures_run_content_sha256_unique",
        ),
        Index(
            "ix_raw_captures_ingestion_run_id_received_at",
            "ingestion_run_id",
            "received_at",
        ),
        Index("ix_raw_captures_content_sha256", "content_sha256"),
    )


class StagedRecord(Base):
    __tablename__ = "staged_records"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    raw_capture_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("raw_captures.id", ondelete="RESTRICT"),
        nullable=False,
    )
    record_key: Mapped[str] = mapped_column(String(512), nullable=False)
    candidate_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    state: Mapped[StagedRecordState] = mapped_column(
        staged_record_state_enum,
        nullable=False,
        default=StagedRecordState.RECEIVED,
        server_default=StagedRecordState.RECEIVED.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(record_key)) > 0", name="record_key_not_blank"),
        UniqueConstraint(
            "raw_capture_id",
            "record_key",
            name="uq_staged_records_capture_record_key_unique",
        ),
        Index("ix_staged_records_raw_capture_id_state", "raw_capture_id", "state"),
    )


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    staged_record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("staged_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    severity: Mapped[DataQualitySeverity] = mapped_column(data_quality_severity_enum, nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(code)) > 0", name="code_not_blank"),
        CheckConstraint("length(btrim(message)) > 0", name="message_not_blank"),
        UniqueConstraint(
            "staged_record_id",
            "code",
            name="uq_data_quality_issues_record_code_unique",
        ),
        Index(
            "ix_data_quality_issues_staged_record_id_severity",
            "staged_record_id",
            "severity",
        ),
    )


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    staged_record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("staged_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[ReviewDecisionOutcome] = mapped_column(
        review_decision_outcome_enum,
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        Index(
            "ix_review_decisions_staged_record_id_decided_at",
            "staged_record_id",
            "decided_at",
        ),
    )

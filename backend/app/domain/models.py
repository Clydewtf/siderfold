from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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


class ProgramSourceStatus(StrEnum):
    UNKNOWN = "unknown"
    OPEN = "open"
    CLOSED = "closed"
    COMPLETED = "completed"
    UPCOMING = "upcoming"


class ProgramAccessMode(StrEnum):
    UNKNOWN = "unknown"
    OPEN = "open"
    INVITATION_ONLY = "invitation_only"


class ProgramTimelineEventKind(StrEnum):
    APPLICATION = "application"
    APPLICATION_OPEN = "application_open"
    APPLICATION_CLOSE = "application_close"
    EVALUATION = "evaluation"
    RESULTS = "results"
    CONTRACTING = "contracting"
    IMPLEMENTATION = "implementation"
    OTHER = "other"


class ProgramFundingScope(StrEnum):
    ANNOUNCED_TOTAL = "announced_total"
    PER_RECIPIENT = "per_recipient"
    PER_PROGRAM = "per_program"
    AWARDED_TOTAL = "awarded_total"
    OTHER = "other"


class ProgramResourceKind(StrEnum):
    APPLICATION = "application"
    COMPETITION_DOCUMENT = "competition_document"
    PROGRAM_DOCUMENT = "program_document"
    RESULT = "result"
    DETAIL = "detail"
    REFERENCE = "reference"


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


class DeduplicationMatchLevel(StrEnum):
    EXACT_EXTERNAL_ID = "exact_external_id"
    EXACT_URL = "exact_url"
    NORMALIZED_FIELDS = "normalized_fields"


class DeduplicationMatchDisposition(StrEnum):
    AUTO_MERGED = "auto_merged"
    REVIEW_REQUIRED = "review_required"


class ReviewCaseStatus(StrEnum):
    OPEN = "open"
    NEEDS_CLARIFICATION = "needs_clarification"
    RESOLVED = "resolved"


class ReviewActionType(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    MERGE = "merge"
    NEEDS_CLARIFICATION = "needs_clarification"
    AUTO_MERGE = "auto_merge"


class DiscoveryReviewActionType(StrEnum):
    LINK_TO_REGISTERED_SOURCE = "link_to_registered_source"
    REJECT = "reject"
    NEEDS_CLARIFICATION = "needs_clarification"


class TelegramDiscoveryRoute(StrEnum):
    SOURCE_ADAPTER = "source_adapter"
    MANUAL_REVIEW = "manual_review"


class TelegramLinkRole(StrEnum):
    POSSIBLE_SOURCE = "possible_source"
    REGISTRATION = "registration"
    OTHER = "other"


class SourceExecutionStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_LOCKED = "skipped_locked"
    SKIPPED_RATE_LIMITED = "skipped_rate_limited"
    INTERRUPTED = "interrupted"


class SourceExecutionTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class SourceExecutionAttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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

program_source_status_enum = Enum(
    ProgramSourceStatus,
    name="program_source_status",
    native_enum=True,
    values_callable=_enum_values,
)

program_access_mode_enum = Enum(
    ProgramAccessMode,
    name="program_access_mode",
    native_enum=True,
    values_callable=_enum_values,
)

program_timeline_event_kind_enum = Enum(
    ProgramTimelineEventKind,
    name="program_timeline_event_kind",
    native_enum=True,
    values_callable=_enum_values,
)

program_funding_scope_enum = Enum(
    ProgramFundingScope,
    name="program_funding_scope",
    native_enum=True,
    values_callable=_enum_values,
)

program_resource_kind_enum = Enum(
    ProgramResourceKind,
    name="program_resource_kind",
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

deduplication_match_level_enum = Enum(
    DeduplicationMatchLevel,
    name="deduplication_match_level",
    native_enum=True,
    values_callable=_enum_values,
)

deduplication_match_disposition_enum = Enum(
    DeduplicationMatchDisposition,
    name="deduplication_match_disposition",
    native_enum=True,
    values_callable=_enum_values,
)

review_case_status_enum = Enum(
    ReviewCaseStatus,
    name="review_case_status",
    native_enum=True,
    values_callable=_enum_values,
)

review_action_type_enum = Enum(
    ReviewActionType,
    name="review_action_type",
    native_enum=True,
    values_callable=_enum_values,
)

discovery_review_action_type_enum = Enum(
    DiscoveryReviewActionType,
    name="discovery_review_action_type",
    native_enum=True,
    values_callable=_enum_values,
)

telegram_discovery_route_enum = Enum(
    TelegramDiscoveryRoute,
    name="telegram_discovery_route",
    native_enum=True,
    values_callable=_enum_values,
)

telegram_link_role_enum = Enum(
    TelegramLinkRole,
    name="telegram_link_role",
    native_enum=True,
    values_callable=_enum_values,
)

source_execution_status_enum = Enum(
    SourceExecutionStatus,
    name="source_execution_status",
    native_enum=True,
    values_callable=_enum_values,
)

source_execution_trigger_enum = Enum(
    SourceExecutionTrigger,
    name="source_execution_trigger",
    native_enum=True,
    values_callable=_enum_values,
)

source_execution_attempt_status_enum = Enum(
    SourceExecutionAttemptStatus,
    name="source_execution_attempt_status",
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
        Index(
            "ix_programs_publication_status_updated_at_id",
            "publication_status",
            "updated_at",
            "id",
        ),
        Index(
            "ix_programs_title_search",
            func.to_tsvector(text("'russian'"), title),
            postgresql_using="gin",
        ),
        Index(
            "ix_programs_title_trigram",
            text("lower(title) gin_trgm_ops"),
            postgresql_using="gin",
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
        Index("ix_program_sources_source_id_program_id", "source_id", "program_id"),
    )


class ProgramDeadline(Base):
    __tablename__ = "program_deadlines"

    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    deadline_on: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        Index("ix_program_deadlines_deadline_on", "deadline_on"),
        Index("ix_program_deadlines_deadline_on_program_id", "deadline_on", "program_id"),
    )


class Geography(Base):
    __tablename__ = "geographies"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(slug)) > 0", name="slug_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        UniqueConstraint("slug", name="uq_geographies_slug"),
        Index(
            "uq_geographies_normalized_name",
            func.lower(func.btrim(name)),
            unique=True,
        ),
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

    __table_args__ = (
        Index("ix_program_geographies_geography_id", "geography_id"),
        Index(
            "ix_program_geographies_geography_id_program_id",
            "geography_id",
            "program_id",
        ),
    )


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(slug)) > 0", name="slug_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        UniqueConstraint("slug", name="uq_themes_slug"),
        Index(
            "uq_themes_normalized_name",
            func.lower(func.btrim(name)),
            unique=True,
        ),
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

    __table_args__ = (
        Index("ix_program_themes_theme_id", "theme_id"),
        Index("ix_program_themes_theme_id_program_id", "theme_id", "program_id"),
    )


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
        Index("ix_program_funding_value_kind_program_id", "value_kind", "program_id"),
    )


class ProgramDetails(Base):
    """Approved source facts that do not fit the catalog's core filter tables."""

    __tablename__ = "program_details"

    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    summary: Mapped[str | None] = mapped_column(Text)
    eligibility_summary: Mapped[str | None] = mapped_column(Text)
    eligibility_geography_note: Mapped[str | None] = mapped_column(Text)
    source_published_on: Mapped[date | None] = mapped_column(Date)
    source_status: Mapped[ProgramSourceStatus] = mapped_column(
        program_source_status_enum,
        nullable=False,
        default=ProgramSourceStatus.UNKNOWN,
        server_default=ProgramSourceStatus.UNKNOWN.value,
    )
    access_mode: Mapped[ProgramAccessMode] = mapped_column(
        program_access_mode_enum,
        nullable=False,
        default=ProgramAccessMode.UNKNOWN,
        server_default=ProgramAccessMode.UNKNOWN.value,
    )
    application_url: Mapped[str | None] = mapped_column(String(2048))
    application_start_on: Mapped[date | None] = mapped_column(Date)
    application_end_on: Mapped[date | None] = mapped_column(Date)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "application_start_on IS NULL OR application_end_on IS NULL "
            "OR application_start_on <= application_end_on",
            name="application_dates_in_order",
        ),
        CheckConstraint(
            "application_url IS NULL OR length(btrim(application_url)) > 0",
            name="application_url_not_blank",
        ),
        CheckConstraint(
            "jsonb_typeof(source_metadata) = 'object'",
            name="source_metadata_is_object",
        ),
    )


class ProgramTimelineEvent(Base):
    """One explicit date or date range announced for a published program."""

    __tablename__ = "program_timeline_events"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_kind: Mapped[ProgramTimelineEventKind] = mapped_column(
        program_timeline_event_kind_enum,
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    start_on: Mapped[date | None] = mapped_column(Date)
    end_on: Mapped[date | None] = mapped_column(Date)
    evidence: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(label)) > 0", name="label_not_blank"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            "start_on IS NOT NULL OR end_on IS NOT NULL",
            name="timeline_event_has_date",
        ),
        CheckConstraint(
            "start_on IS NULL OR end_on IS NULL OR start_on <= end_on",
            name="timeline_dates_in_order",
        ),
        UniqueConstraint("program_id", "position", name="uq_program_timeline_events_position"),
        Index("ix_program_timeline_events_program_position", "program_id", "position"),
        Index("ix_program_timeline_events_kind_end", "event_kind", "end_on"),
    )


class ProgramFundingAmount(Base):
    """A scoped funding fact, preserving totals and recipient limits separately."""

    __tablename__ = "program_funding_amounts"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[ProgramFundingScope] = mapped_column(
        program_funding_scope_enum,
        nullable=False,
    )
    label: Mapped[str | None] = mapped_column(String(500))
    value_kind: Mapped[FundingValueKind] = mapped_column(funding_value_kind_enum, nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    exact_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    evidence: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            "label IS NULL OR length(btrim(label)) > 0",
            name="label_not_blank",
        ),
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
        UniqueConstraint(
            "program_id",
            "scope",
            "position",
            name="uq_program_funding_amounts_scope_position",
        ),
        Index("ix_program_funding_amounts_program_position", "program_id", "position"),
        Index("ix_program_funding_amounts_scope_kind", "scope", "value_kind"),
    )


class ProgramResource(Base):
    """A public outbound resource approved with a canonical program."""

    __tablename__ = "program_resources"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_kind: Mapped[ProgramResourceKind] = mapped_column(
        program_resource_kind_enum,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_section: Mapped[str | None] = mapped_column(String(500))
    content_format: Mapped[str | None] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(url)) > 0", name="url_not_blank"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            "title IS NULL OR length(btrim(title)) > 0",
            name="title_not_blank",
        ),
        UniqueConstraint("program_id", "url", name="uq_program_resources_url"),
        Index("ix_program_resources_program_position", "program_id", "position"),
        Index("ix_program_resources_kind", "resource_kind"),
    )


class ProgramContentSection(Base):
    """Bounded, human-readable source sections retained after acceptance."""

    __tablename__ = "program_content_sections"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    heading: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(heading)) > 0", name="heading_not_blank"),
        CheckConstraint("length(btrim(category)) > 0", name="category_not_blank"),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        UniqueConstraint("program_id", "position", name="uq_program_content_sections_position"),
        Index("ix_program_content_sections_program_position", "program_id", "position"),
        Index("ix_program_content_sections_public_category", "is_public", "category"),
    )


class ProgramContact(Base):
    """Source contact data retained for review and intentionally hidden from public API."""

    __tablename__ = "program_contacts"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    source_evidence: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        UniqueConstraint("program_id", "position", name="uq_program_contacts_position"),
        Index("ix_program_contacts_program_position", "program_id", "position"),
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


class SourceExecutionRun(Base):
    """One managed source execution, including skipped and recovered attempts."""

    __tablename__ = "source_execution_runs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger: Mapped[SourceExecutionTrigger] = mapped_column(
        source_execution_trigger_enum,
        nullable=False,
    )
    status: Mapped[SourceExecutionStatus] = mapped_column(
        source_execution_status_enum,
        nullable=False,
    )
    owner_token: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingestion_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    result_kind: Mapped[str | None] = mapped_column(String(50))
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(source_key)) > 0", name="source_key_not_blank"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "result_kind IS NULL OR length(btrim(result_kind)) > 0",
            name="result_kind_not_blank",
        ),
        CheckConstraint(
            "(status = 'running' AND owner_token IS NOT NULL "
            "AND finished_at IS NULL AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at > started_at) "
            "OR (status IN ('succeeded', 'failed', 'skipped_locked', "
            "'skipped_rate_limited', 'interrupted') AND finished_at IS NOT NULL)",
            name="timestamps_match_status",
        ),
        Index("ix_source_execution_runs_source_started", "source_id", "started_at"),
        Index("ix_source_execution_runs_status_lease", "status", "lease_expires_at"),
        Index("ix_source_execution_runs_ingestion_run", "ingestion_run_id"),
    )


class SourceExecutionAttempt(Base):
    """Append-only terminal record for one retry attempt of a managed execution."""

    __tablename__ = "source_execution_attempts"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_execution_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("source_execution_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SourceExecutionAttemptStatus] = mapped_column(
        source_execution_attempt_status_enum,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT"),
    )
    retry_class: Mapped[str | None] = mapped_column(String(32))
    backoff_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint("finished_at >= started_at", name="finished_after_started"),
        CheckConstraint(
            "retry_class IS NULL OR length(btrim(retry_class)) > 0",
            name="retry_class_not_blank",
        ),
        CheckConstraint("backoff_seconds >= 0", name="backoff_nonnegative"),
        UniqueConstraint(
            "source_execution_run_id",
            "attempt_number",
            name="uq_source_execution_attempts_run_number",
        ),
        Index(
            "ix_source_execution_attempts_run_created",
            "source_execution_run_id",
            "created_at",
        ),
        Index("ix_source_execution_attempts_ingestion_run", "ingestion_run_id"),
    )


class AnalyticsSnapshot(Base):
    """An immutable calculation input and result for catalog quality metrics."""

    __tablename__ = "analytics_snapshots"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    freshness_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    registry_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    input_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    limitations: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(scope)) > 0", name="scope_not_blank"),
        CheckConstraint(
            "length(btrim(calculation_version)) > 0",
            name="calculation_version_not_blank",
        ),
        CheckConstraint(
            "freshness_window_days >= 1 AND freshness_window_days <= 3650",
            name="freshness_window_days_in_range",
        ),
        CheckConstraint(
            "registry_fingerprint ~ '^[a-f0-9]{64}$'",
            name="registry_fingerprint_sha256",
        ),
        CheckConstraint(
            "input_fingerprint ~ '^[a-f0-9]{64}$'",
            name="input_fingerprint_sha256",
        ),
        CheckConstraint(
            "jsonb_typeof(source_scope) = 'object'",
            name="source_scope_is_object",
        ),
        CheckConstraint(
            "jsonb_typeof(input_manifest) = 'object'",
            name="input_manifest_is_object",
        ),
        CheckConstraint("jsonb_typeof(metrics) = 'object'", name="metrics_is_object"),
        CheckConstraint(
            "jsonb_typeof(limitations) = 'array'",
            name="limitations_is_array",
        ),
        UniqueConstraint("input_fingerprint", name="uq_analytics_snapshots_input_fingerprint"),
        Index("ix_analytics_snapshots_scope_as_of_id", "scope", "as_of", "id"),
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


class DeduplicationMatch(Base):
    __tablename__ = "deduplication_matches"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    candidate_staged_record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "staged_records.id",
            ondelete="RESTRICT",
            name="fk_dedup_matches_candidate_stage",
        ),
        nullable=False,
    )
    target_staged_record_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "staged_records.id",
            ondelete="RESTRICT",
            name="fk_dedup_matches_target_stage",
        ),
    )
    target_program_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "programs.id",
            ondelete="RESTRICT",
            name="fk_dedup_matches_target_program",
        ),
    )
    match_level: Mapped[DeduplicationMatchLevel] = mapped_column(
        deduplication_match_level_enum,
        nullable=False,
    )
    disposition: Mapped[DeduplicationMatchDisposition] = mapped_column(
        deduplication_match_disposition_enum,
        nullable=False,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(target_staged_record_id IS NOT NULL AND target_program_id IS NULL) "
            "OR (target_staged_record_id IS NULL AND target_program_id IS NOT NULL)",
            name="exactly_one_target",
        ),
        CheckConstraint(
            "target_staged_record_id IS NULL "
            "OR candidate_staged_record_id <> target_staged_record_id",
            name="candidate_differs_from_staged_target",
        ),
        Index(
            "ix_deduplication_matches_candidate_created_at",
            "candidate_staged_record_id",
            "created_at",
        ),
        Index(
            "ix_deduplication_matches_target_staged_record_id",
            "target_staged_record_id",
        ),
        Index(
            "ix_deduplication_matches_target_program_id",
            "target_program_id",
        ),
        Index(
            "uq_deduplication_matches_candidate_staged_target_level",
            "candidate_staged_record_id",
            "target_staged_record_id",
            "match_level",
            unique=True,
            postgresql_where=text("target_staged_record_id IS NOT NULL"),
        ),
        Index(
            "uq_deduplication_matches_candidate_program_target_level",
            "candidate_staged_record_id",
            "target_program_id",
            "match_level",
            unique=True,
            postgresql_where=text("target_program_id IS NOT NULL"),
        ),
    )


class ReviewCase(Base):
    __tablename__ = "review_cases"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    staged_record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "staged_records.id",
            ondelete="RESTRICT",
            name="fk_review_cases_stage",
        ),
        nullable=False,
    )
    status: Mapped[ReviewCaseStatus] = mapped_column(
        review_case_status_enum,
        nullable=False,
        default=ReviewCaseStatus.OPEN,
        server_default=ReviewCaseStatus.OPEN.value,
    )
    opened_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("staged_record_id", name="uq_review_cases_staged_record_id"),
        CheckConstraint(
            "(status IN ('open', 'needs_clarification') AND resolved_at IS NULL) "
            "OR (status = 'resolved' AND resolved_at IS NOT NULL)",
            name="resolution_timestamp_matches_status",
        ),
        Index("ix_review_cases_status_opened_at", "status", "opened_at"),
    )


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    review_case_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "review_cases.id",
            ondelete="RESTRICT",
            name="fk_review_actions_case",
        ),
        nullable=False,
    )
    action: Mapped[ReviewActionType] = mapped_column(review_action_type_enum, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    deduplication_match_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "deduplication_matches.id",
            ondelete="RESTRICT",
            name="fk_review_actions_match",
        ),
    )
    target_staged_record_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "staged_records.id",
            ondelete="RESTRICT",
            name="fk_review_actions_target_stage",
        ),
    )
    target_program_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "programs.id",
            ondelete="RESTRICT",
            name="fk_review_actions_target_program",
        ),
    )
    review_decision_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "review_decisions.id",
            ondelete="RESTRICT",
            name="fk_review_actions_decision",
        ),
    )
    prior_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    result_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        CheckConstraint(
            "(action IN ('merge', 'auto_merge') "
            "AND ((target_staged_record_id IS NOT NULL AND target_program_id IS NULL) "
            "OR (target_staged_record_id IS NULL AND target_program_id IS NOT NULL)) "
            "AND review_decision_id IS NULL) "
            "OR (action IN ('accept', 'reject') "
            "AND target_staged_record_id IS NULL AND target_program_id IS NULL "
            "AND review_decision_id IS NOT NULL) "
            "OR (action = 'needs_clarification' "
            "AND target_staged_record_id IS NULL AND target_program_id IS NULL "
            "AND review_decision_id IS NULL)",
            name="targets_match_action",
        ),
        Index("ix_review_actions_review_case_id_created_at", "review_case_id", "created_at"),
        Index("ix_review_actions_deduplication_match_id", "deduplication_match_id"),
    )


class ReviewRevision(Base):
    """An immutable operator correction layered over one staged candidate."""

    __tablename__ = "review_revisions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    review_case_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("review_cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    staged_record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("staged_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_record: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    changed_fields: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    deduplication_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("revision_number > 0", name="revision_number_positive"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        CheckConstraint("jsonb_typeof(effective_record) = 'object'", name="effective_record_is_object"),
        CheckConstraint("jsonb_typeof(changed_fields) = 'array'", name="changed_fields_is_array"),
        CheckConstraint(
            "jsonb_typeof(deduplication_snapshot) = 'object'",
            name="deduplication_snapshot_is_object",
        ),
        UniqueConstraint("review_case_id", "revision_number", name="uq_review_revisions_case_number"),
        Index("ix_review_revisions_case_created", "review_case_id", "created_at"),
        Index("ix_review_revisions_staged_record", "staged_record_id"),
    )


class ReviewIssueResolution(Base):
    """The explicit review revision that resolved one quality issue."""

    __tablename__ = "review_issue_resolutions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    review_revision_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("review_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    data_quality_issue_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("data_quality_issues.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        UniqueConstraint("data_quality_issue_id", name="uq_review_issue_resolutions_issue"),
        Index("ix_review_issue_resolutions_revision", "review_revision_id"),
    )


class ProgramPublicationAction(Base):
    """An append-only publication lifecycle action backed by prior review evidence."""

    __tablename__ = "program_publication_actions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_case_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("review_cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    publication_review_decision_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("review_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    prior_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    result_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('archive', 'republish')",
            name="publication_lifecycle_action_allowed",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        CheckConstraint("jsonb_typeof(prior_values) = 'object'", name="prior_values_is_object"),
        CheckConstraint("jsonb_typeof(result_values) = 'object'", name="result_values_is_object"),
        Index("ix_program_publication_actions_program_created", "program_id", "created_at"),
        Index("ix_program_publication_actions_review_case_created", "review_case_id", "created_at"),
    )


class OperatorOperation(Base):
    """An append-only idempotency record linked to one operator audit action."""

    __tablename__ = "operator_operations"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    review_action_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("review_actions.id", ondelete="RESTRICT"),
    )
    discovery_review_action_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("discovery_review_actions.id", ondelete="RESTRICT"),
    )
    program_publication_action_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("program_publication_actions.id", ondelete="RESTRICT"),
    )
    review_revision_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("review_revisions.id", ondelete="RESTRICT"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        CheckConstraint("length(btrim(idempotency_key)) > 0", name="idempotency_key_not_blank"),
        CheckConstraint("length(btrim(action)) > 0", name="action_not_blank"),
        CheckConstraint("length(btrim(target_type)) > 0", name="target_type_not_blank"),
        CheckConstraint(
            "request_fingerprint ~ '^[a-f0-9]{64}$'",
            name="request_fingerprint_sha256",
        ),
        CheckConstraint("jsonb_typeof(result_payload) = 'object'", name="result_payload_is_object"),
        CheckConstraint(
            "((review_action_id IS NOT NULL)::integer + "
            "(discovery_review_action_id IS NOT NULL)::integer + "
            "(program_publication_action_id IS NOT NULL)::integer + "
            "(review_revision_id IS NOT NULL)::integer) = 1",
            name="exactly_one_audit_action",
        ),
        UniqueConstraint("actor", "idempotency_key", name="uq_operator_operations_actor_key"),
        Index("ix_operator_operations_target_created", "target_type", "target_id", "created_at"),
    )


class TelegramDiscoveryCursor(Base):
    __tablename__ = "telegram_discovery_cursors"

    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    last_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("last_message_id > 0", name="last_message_id_positive"),
    )


class TelegramDiscoveryMessage(Base):
    __tablename__ = "telegram_discovery_messages"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    raw_capture_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("raw_captures.id", ondelete="RESTRICT"),
        nullable=False,
    )
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    service_label: Mapped[str | None] = mapped_column(String(280))
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    discovery_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("message_id > 0", name="message_id_positive"),
        CheckConstraint("length(btrim(message_url)) > 0", name="message_url_not_blank"),
        CheckConstraint(
            "service_label IS NULL OR length(btrim(service_label)) > 0",
            name="service_label_not_blank",
        ),
        CheckConstraint("content_sha256 ~ '^[a-f0-9]{64}$'", name="content_sha256_format"),
        CheckConstraint("last_observed_at >= received_at", name="observed_after_received"),
        CheckConstraint("expires_at > received_at", name="expiry_after_received"),
        UniqueConstraint("source_id", "message_id", name="uq_telegram_messages_source_message"),
        Index("ix_telegram_messages_source_expires", "source_id", "expires_at"),
        Index("ix_telegram_messages_review_expires", "review_required", "expires_at"),
        Index("ix_telegram_messages_raw_capture", "raw_capture_id"),
    )


class TelegramDiscoveryMessageObservation(Base):
    """Append-only observation of one Telegram message in a specific source run."""

    __tablename__ = "telegram_discovery_message_observations"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    telegram_discovery_message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("telegram_discovery_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    raw_capture_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("raw_captures.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    service_label: Mapped[str | None] = mapped_column(String(280))
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    discovery_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(message_url)) > 0", name="message_url"),
        CheckConstraint(
            "service_label IS NULL OR length(btrim(service_label)) > 0",
            name="service_label",
        ),
        CheckConstraint("content_sha256 ~ '^[a-f0-9]{64}$'", name="content_hash"),
        CheckConstraint("expires_at > observed_at", name="expiry"),
        UniqueConstraint(
            "telegram_discovery_message_id",
            "ingestion_run_id",
            name="uq_tg_message_observations_message_run",
        ),
        Index(
            "ix_tg_message_observations_message_observed",
            "telegram_discovery_message_id",
            "observed_at",
        ),
        Index("ix_tg_message_observations_raw_capture", "raw_capture_id"),
    )


class TelegramDiscoveryUrl(Base):
    __tablename__ = "telegram_discovery_urls"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    route: Mapped[TelegramDiscoveryRoute] = mapped_column(
        telegram_discovery_route_enum,
        nullable=False,
    )
    target_source_key: Mapped[str | None] = mapped_column(String(64))
    manual_review_reason: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seen_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(normalized_url)) > 0", name="normalized_url_not_blank"),
        CheckConstraint(
            "(route = 'source_adapter' AND target_source_key IS NOT NULL "
            "AND manual_review_reason IS NULL) "
            "OR (route = 'manual_review' AND target_source_key IS NULL "
            "AND manual_review_reason IS NOT NULL)",
            name="route_target_matches_state",
        ),
        CheckConstraint(
            "manual_review_reason IS NULL OR length(btrim(manual_review_reason)) > 0",
            name="manual_review_reason_not_blank",
        ),
        CheckConstraint("last_seen_at >= first_seen_at", name="last_seen_after_first_seen"),
        CheckConstraint("expires_at > last_seen_at", name="expiry_after_last_seen"),
        CheckConstraint("seen_count > 0", name="seen_count_positive"),
        UniqueConstraint("normalized_url", name="uq_telegram_urls_normalized_url"),
        Index("ix_telegram_urls_route_expires", "route", "expires_at"),
    )


class TelegramDiscoveryMessageUrl(Base):
    __tablename__ = "telegram_discovery_message_urls"

    message_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("telegram_discovery_messages.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    discovery_url_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("telegram_discovery_urls.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    link_role: Mapped[TelegramLinkRole] = mapped_column(telegram_link_role_enum, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_telegram_message_urls_discovery_url", "discovery_url_id"),
    )


class DiscoveryReviewCase(Base):
    """A bounded operator task for a Telegram discovery signal, not a program candidate."""

    __tablename__ = "discovery_review_cases"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    telegram_discovery_message_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("telegram_discovery_messages.id", ondelete="RESTRICT"),
    )
    telegram_discovery_url_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("telegram_discovery_urls.id", ondelete="RESTRICT"),
    )
    status: Mapped[ReviewCaseStatus] = mapped_column(
        review_case_status_enum,
        nullable=False,
        default=ReviewCaseStatus.OPEN,
        server_default=ReviewCaseStatus.OPEN.value,
    )
    opened_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(telegram_discovery_message_id IS NOT NULL AND telegram_discovery_url_id IS NULL) "
            "OR (telegram_discovery_message_id IS NULL AND telegram_discovery_url_id IS NOT NULL)",
            name="exactly_one_subject",
        ),
        CheckConstraint(
            "(status IN ('open', 'needs_clarification') AND resolved_at IS NULL) "
            "OR (status = 'resolved' AND resolved_at IS NOT NULL)",
            name="resolution_timestamp_matches_status",
        ),
        UniqueConstraint(
            "telegram_discovery_message_id",
            name="uq_discovery_review_cases_message",
        ),
        UniqueConstraint(
            "telegram_discovery_url_id",
            name="uq_discovery_review_cases_url",
        ),
        Index("ix_discovery_review_cases_status_opened", "status", "opened_at"),
    )


class DiscoveryReviewAction(Base):
    """An immutable decision in the discovery queue."""

    __tablename__ = "discovery_review_actions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    discovery_review_case_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("discovery_review_cases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[DiscoveryReviewActionType] = mapped_column(
        discovery_review_action_type_enum,
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    target_source_key: Mapped[str | None] = mapped_column(String(64))
    prior_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    result_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint("length(btrim(actor)) > 0", name="actor_not_blank"),
        CheckConstraint(
            "target_source_key IS NULL OR length(btrim(target_source_key)) > 0",
            name="target_source_key_not_blank",
        ),
        CheckConstraint(
            "(action = 'link_to_registered_source' AND target_source_key IS NOT NULL) "
            "OR (action IN ('reject', 'needs_clarification') AND target_source_key IS NULL)",
            name="target_matches_action",
        ),
        Index(
            "ix_discovery_review_actions_case_created",
            "discovery_review_case_id",
            "created_at",
        ),
    )

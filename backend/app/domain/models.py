from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
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
        UniqueConstraint("canonical_url", name="canonical_url_unique"),
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
        ForeignKeyConstraint(
            ["id", "primary_source_id"],
            ["program_sources.program_id", "program_sources.source_id"],
            name="primary_source_link",
            deferrable=True,
            initially="DEFERRED",
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
    )


class ProgramDeadline(Base):
    __tablename__ = "program_deadlines"

    program_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    deadline_on: Mapped[date] = mapped_column(Date, nullable=False)


class Geography(Base):
    __tablename__ = "geographies"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(slug)) > 0", name="slug_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        UniqueConstraint("slug", name="slug_unique"),
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


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(slug)) > 0", name="slug_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        UniqueConstraint("slug", name="slug_unique"),
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
    )

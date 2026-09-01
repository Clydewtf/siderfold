from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import FundingValueKind


class PublicSchema(BaseModel):
    """Base model for fields intentionally exposed by the read API."""

    model_config = ConfigDict(extra="forbid")


class ApiErrorDetail(PublicSchema):
    field: str
    reason: str


class ApiError(PublicSchema):
    code: str
    message: str
    details: list[ApiErrorDetail] = Field(default_factory=list)


class ApiErrorResponse(PublicSchema):
    error: ApiError


class SourceRef(PublicSchema):
    """Public identity and canonical homepage of a source."""

    id: UUID
    name: str
    canonical_url: str


class SourcePublic(SourceRef):
    published_program_count: int = Field(ge=1)


class SourceLinkPublic(PublicSchema):
    """Attribution for one public program page observed at a source."""

    source: SourceRef
    source_url: str = Field(min_length=1, max_length=2048)
    observed_at: datetime


class TaxonomyOption(PublicSchema):
    slug: str
    name: str


class FundingPublic(PublicSchema):
    value_kind: FundingValueKind
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    exact_amount: Decimal | None = Field(default=None, gt=0)
    min_amount: Decimal | None = Field(default=None, gt=0)
    max_amount: Decimal | None = Field(default=None, gt=0)


class ProgramListItem(PublicSchema):
    """Public catalog card; every field is safe for an unauthenticated reader."""

    id: UUID
    title: str
    publication_status: Literal["published"]
    published_at: datetime
    updated_at: datetime
    deadline_on: date | None = None
    funding: FundingPublic | None = None
    primary_source: SourceLinkPublic


class ProgramDetail(ProgramListItem):
    """Public program card with its visible taxonomy and source attributions."""

    sources: list[SourceLinkPublic]
    geographies: list[TaxonomyOption]
    themes: list[TaxonomyOption]


class SourceFilterOption(PublicSchema):
    id: UUID
    name: str
    canonical_url: str


class DeadlineBounds(PublicSchema):
    min_deadline: date | None = None
    max_deadline: date | None = None


class FilterOptions(PublicSchema):
    sources: list[SourceFilterOption]
    geographies: list[TaxonomyOption]
    themes: list[TaxonomyOption]
    funding_kinds: list[FundingValueKind]
    deadline: DeadlineBounds


PageItem = TypeVar("PageItem")


class Page(PublicSchema, Generic[PageItem]):
    items: list[PageItem]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)

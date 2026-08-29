from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from enum import StrEnum
from typing import Any, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import asc, desc, exists, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.schemas import (
    ApiError,
    ApiErrorDetail,
    ApiErrorResponse,
    DeadlineBounds,
    FilterOptions,
    FundingPublic,
    Page,
    ProgramDetail,
    ProgramListItem,
    SourceFilterOption,
    SourceLinkPublic,
    SourcePublic,
    SourceRef,
    TaxonomyOption,
)
from app.domain.models import (
    FundingValueKind,
    Geography,
    Program,
    ProgramDeadline,
    ProgramFunding,
    ProgramGeography,
    ProgramSource,
    ProgramTheme,
    PublicationStatus,
    Source,
    Theme,
)


class ProgramSort(StrEnum):
    PUBLISHED_AT = "published_at"
    DEADLINE = "deadline"
    TITLE = "title"


class SourceSort(StrEnum):
    NAME = "name"
    PROGRAM_COUNT = "program_count"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class ReadApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Sequence[ApiErrorDetail] = (),
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = ApiErrorResponse(
            error=ApiError(code=code, message=message, details=list(details))
        )


router = APIRouter(prefix="/api/v1", tags=["catalog"])
HTTP_422_STATUS = 422

COMMON_ERROR_RESPONSES = {
    HTTP_422_STATUS: {
        "model": ApiErrorResponse,
        "description": "The request parameters are invalid.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ApiErrorResponse,
        "description": "The read database is temporarily unavailable.",
    },
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ApiErrorResponse,
        "description": "An unexpected server error occurred.",
    },
}


def register_read_api_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(ReadApiError, _handle_read_api_error)
    application.add_exception_handler(RequestValidationError, _handle_request_validation_error)
    application.add_exception_handler(SQLAlchemyError, _handle_database_error)
    application.add_exception_handler(Exception, _handle_unexpected_error)


async def _handle_read_api_error(_request: Request, exc: ReadApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.response.model_dump(mode="json"),
    )


async def _handle_request_validation_error(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [
        ApiErrorDetail(
            field=".".join(str(part) for part in item.get("loc", ())) or "request",
            reason=item["msg"],
        )
        for item in exc.errors()
    ]
    response = ApiErrorResponse(
        error=ApiError(
            code="invalid_request",
            message="Request validation failed.",
            details=details,
        )
    )
    return JSONResponse(
        status_code=HTTP_422_STATUS,
        content=response.model_dump(mode="json"),
    )


async def _handle_database_error(_request: Request, _exc: SQLAlchemyError) -> JSONResponse:
    response = ApiErrorResponse(
        error=ApiError(
            code="database_unavailable",
            message="The read database is temporarily unavailable.",
        )
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(mode="json"),
    )


async def _handle_unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
    response = ApiErrorResponse(
        error=ApiError(
            code="internal_error",
            message="Internal server error.",
        )
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response.model_dump(mode="json"),
    )


def get_database_connection(request: Request) -> Iterator[Connection]:
    with request.app.state.db_engine.connect() as connection:
        yield connection


def _program_summary_select():
    return (
        select(
            Program.id.label("program_id"),
            Program.title,
            Program.published_at,
            ProgramDeadline.deadline_on,
            ProgramFunding.value_kind.label("funding_kind"),
            ProgramFunding.currency_code.label("funding_currency"),
            ProgramFunding.exact_amount.label("funding_exact"),
            ProgramFunding.min_amount.label("funding_min"),
            ProgramFunding.max_amount.label("funding_max"),
            Source.id.label("primary_source_id"),
            Source.name.label("primary_source_name"),
            Source.canonical_url.label("primary_source_url"),
        )
        .select_from(Program)
        .join(
            ProgramSource,
            (ProgramSource.program_id == Program.id)
            & (ProgramSource.source_id == Program.primary_source_id),
        )
        .join(Source, Source.id == Program.primary_source_id)
        .outerjoin(ProgramDeadline, ProgramDeadline.program_id == Program.id)
        .outerjoin(ProgramFunding, ProgramFunding.program_id == Program.id)
    )


def _program_filter_clauses(
    *,
    query: str | None,
    source_ids: Sequence[UUID] | None,
    theme_slugs: Sequence[str] | None,
    geography_slugs: Sequence[str] | None,
    funding_kinds: Sequence[FundingValueKind] | None,
    deadline_from: date | None,
    deadline_to: date | None,
) -> list[Any]:
    clauses: list[Any] = [Program.publication_status == PublicationStatus.PUBLISHED]

    if query is not None and query.strip():
        clauses.append(Program.title.ilike(f"%{query.strip()}%"))

    if source_ids:
        clauses.append(
            select(1)
                .select_from(ProgramSource)
                .where(
                    ProgramSource.program_id == Program.id,
                    ProgramSource.source_id.in_(source_ids),
                )
                .correlate(Program)
                .exists()
        )

    if theme_slugs:
        clauses.append(
            select(1)
                .select_from(ProgramTheme)
                .join(Theme, Theme.id == ProgramTheme.theme_id)
                .where(
                    ProgramTheme.program_id == Program.id,
                    Theme.slug.in_(theme_slugs),
                )
                .correlate(Program)
                .exists()
        )

    if geography_slugs:
        clauses.append(
            select(1)
                .select_from(ProgramGeography)
                .join(Geography, Geography.id == ProgramGeography.geography_id)
                .where(
                    ProgramGeography.program_id == Program.id,
                    Geography.slug.in_(geography_slugs),
                )
                .correlate(Program)
                .exists()
        )

    if funding_kinds:
        clauses.append(
            select(1)
                .select_from(ProgramFunding)
                .where(
                    ProgramFunding.program_id == Program.id,
                    ProgramFunding.value_kind.in_(funding_kinds),
                )
                .correlate(Program)
                .exists()
        )

    if deadline_from is not None or deadline_to is not None:
        deadline_clauses: list[Any] = [ProgramDeadline.program_id == Program.id]
        if deadline_from is not None:
            deadline_clauses.append(ProgramDeadline.deadline_on >= deadline_from)
        if deadline_to is not None:
            deadline_clauses.append(ProgramDeadline.deadline_on <= deadline_to)
        clauses.append(
            select(1)
            .select_from(ProgramDeadline)
            .where(*deadline_clauses)
            .correlate(Program)
            .exists()
        )

    return clauses


def _program_order_by(sort: ProgramSort, order: SortOrder) -> tuple[Any, Any]:
    if sort is ProgramSort.DEADLINE:
        expression = ProgramDeadline.deadline_on
    elif sort is ProgramSort.TITLE:
        expression = func.lower(Program.title)
    else:
        expression = Program.published_at

    ordered_expression = asc(expression) if order is SortOrder.ASC else desc(expression)
    return ordered_expression.nulls_last(), asc(Program.id)


def _source_ref(row: Mapping[str, Any], prefix: str = "primary_source_") -> SourceRef:
    return SourceRef(
        id=row[f"{prefix}id"],
        name=row[f"{prefix}name"],
        canonical_url=row[f"{prefix}url"],
    )


def _funding(row: Mapping[str, Any]) -> FundingPublic | None:
    if row["funding_kind"] is None:
        return None
    return FundingPublic(
        value_kind=row["funding_kind"],
        currency_code=row["funding_currency"],
        exact_amount=row["funding_exact"],
        min_amount=row["funding_min"],
        max_amount=row["funding_max"],
    )


def _program_list_item(row: Mapping[str, Any]) -> ProgramListItem:
    return ProgramListItem(
        id=row["program_id"],
        title=row["title"],
        publication_status="published",
        published_at=row["published_at"],
        deadline_on=row["deadline_on"],
        funding=_funding(row),
        primary_source=_source_ref(row),
    )


def _validate_deadline_range(
    deadline_from: date | None,
    deadline_to: date | None,
) -> None:
    if deadline_from is not None and deadline_to is not None and deadline_from > deadline_to:
        raise ReadApiError(
            status_code=HTTP_422_STATUS,
            code="invalid_request",
            message="deadline_from must not be after deadline_to.",
            details=(
                ApiErrorDetail(
                    field="deadline",
                    reason="deadline_from must be less than or equal to deadline_to",
                ),
            ),
        )


@router.get(
    "/programs",
    response_model=Page[ProgramListItem],
    responses=COMMON_ERROR_RESPONSES,
    summary="List published programs",
)
def list_programs(
    connection: Connection = Depends(get_database_connection),
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page, maximum 100."),
    sort: ProgramSort = Query(default=ProgramSort.PUBLISHED_AT),
    order: SortOrder = Query(default=SortOrder.DESC),
    q: str | None = Query(default=None, min_length=1, max_length=200),
    source_id: list[UUID] | None = Query(default=None, description="Repeat for multiple sources."),
    theme: list[str] | None = Query(default=None, description="Repeat for multiple theme slugs."),
    geography: list[str] | None = Query(
        default=None,
        description="Repeat for multiple geography slugs.",
    ),
    funding_kind: list[FundingValueKind] | None = Query(
        default=None,
        description="Repeat for multiple funding kinds.",
    ),
    deadline_from: date | None = Query(default=None),
    deadline_to: date | None = Query(default=None),
) -> Page[ProgramListItem]:
    _validate_deadline_range(deadline_from, deadline_to)
    clauses = _program_filter_clauses(
        query=q,
        source_ids=source_id,
        theme_slugs=theme,
        geography_slugs=geography,
        funding_kinds=funding_kind,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
    )
    total = int(
        connection.scalar(select(func.count(Program.id)).select_from(Program).where(*clauses)) or 0
    )
    rows = connection.execute(
        _program_summary_select()
        .where(*clauses)
        .order_by(*_program_order_by(sort, order))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).mappings()
    items = [_program_list_item(row) for row in rows]
    return Page[ProgramListItem](items=items, page=page, page_size=page_size, total=total)


@router.get(
    "/programs/{program_id}",
    response_model=ProgramDetail,
    responses={
        **COMMON_ERROR_RESPONSES,
        status.HTTP_404_NOT_FOUND: {
            "model": ApiErrorResponse,
            "description": "The published program was not found.",
        },
    },
    summary="Get one published program",
)
def get_program(
    program_id: UUID,
    connection: Connection = Depends(get_database_connection),
) -> ProgramDetail:
    row = connection.execute(
        _program_summary_select().where(
            Program.id == program_id,
            Program.publication_status == PublicationStatus.PUBLISHED,
        )
    ).mappings().first()
    if row is None:
        raise ReadApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="program_not_found",
            message="Published program was not found.",
        )

    source_rows = connection.execute(
        select(
            Source.id.label("source_id"),
            Source.name.label("source_name"),
            Source.canonical_url.label("source_canonical_url"),
            ProgramSource.source_url,
            ProgramSource.observed_at,
        )
        .select_from(ProgramSource)
        .join(Source, Source.id == ProgramSource.source_id)
        .where(ProgramSource.program_id == program_id)
        .order_by(asc(Source.name), asc(Source.id))
    ).mappings()
    sources = [
        SourceLinkPublic(
            source=SourceRef(
                id=source_row["source_id"],
                name=source_row["source_name"],
                canonical_url=source_row["source_canonical_url"],
            ),
            source_url=source_row["source_url"],
            observed_at=source_row["observed_at"],
        )
        for source_row in source_rows
    ]

    geography_rows = connection.execute(
        select(Geography.slug, Geography.name)
        .select_from(ProgramGeography)
        .join(Geography, Geography.id == ProgramGeography.geography_id)
        .where(ProgramGeography.program_id == program_id)
        .order_by(asc(Geography.name), asc(Geography.slug))
    ).mappings()
    geographies = [TaxonomyOption(**geography_row) for geography_row in geography_rows]

    theme_rows = connection.execute(
        select(Theme.slug, Theme.name)
        .select_from(ProgramTheme)
        .join(Theme, Theme.id == ProgramTheme.theme_id)
        .where(ProgramTheme.program_id == program_id)
        .order_by(asc(Theme.name), asc(Theme.slug))
    ).mappings()
    themes = [TaxonomyOption(**theme_row) for theme_row in theme_rows]

    return ProgramDetail(
        **_program_list_item(row).model_dump(),
        sources=sources,
        geographies=geographies,
        themes=themes,
    )


@router.get(
    "/sources",
    response_model=Page[SourcePublic],
    responses=COMMON_ERROR_RESPONSES,
    summary="List sources used by published programs",
)
def list_sources(
    connection: Connection = Depends(get_database_connection),
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page, maximum 100."),
    sort: SourceSort = Query(default=SourceSort.NAME),
    order: SortOrder = Query(default=SortOrder.ASC),
    q: str | None = Query(default=None, min_length=1, max_length=200),
) -> Page[SourcePublic]:
    published_program_exists = exists(
        select(1)
        .select_from(ProgramSource)
        .join(Program, Program.id == ProgramSource.program_id)
        .where(
            ProgramSource.source_id == Source.id,
            Program.publication_status == PublicationStatus.PUBLISHED,
        )
    )
    clauses: list[Any] = [published_program_exists]
    if q is not None and q.strip():
        clauses.append(Source.name.ilike(f"%{q.strip()}%"))

    published_program_count = (
        select(func.count(ProgramSource.program_id))
        .select_from(ProgramSource)
        .join(Program, Program.id == ProgramSource.program_id)
        .where(
            ProgramSource.source_id == Source.id,
            Program.publication_status == PublicationStatus.PUBLISHED,
        )
        .correlate(Source)
        .scalar_subquery()
    )
    total = int(connection.scalar(select(func.count(Source.id)).where(*clauses)) or 0)
    source_query = select(
        Source.id,
        Source.name,
        Source.canonical_url,
        published_program_count.label("published_program_count"),
    ).where(*clauses)
    source_order_expression = Source.name if sort is SourceSort.NAME else published_program_count
    ordered_expression = asc(source_order_expression) if order is SortOrder.ASC else desc(source_order_expression)
    rows = connection.execute(
        source_query
        .order_by(ordered_expression.nulls_last(), asc(Source.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).mappings()
    items = [SourcePublic(**row) for row in rows]
    return Page[SourcePublic](items=items, page=page, page_size=page_size, total=total)


@router.get(
    "/filters",
    response_model=FilterOptions,
    responses=COMMON_ERROR_RESPONSES,
    summary="List filter values available for published programs",
)
def get_filters(
    connection: Connection = Depends(get_database_connection),
) -> FilterOptions:
    published_program = Program.publication_status == PublicationStatus.PUBLISHED
    source_rows = connection.execute(
        select(Source.id, Source.name, Source.canonical_url)
        .select_from(Source)
        .join(ProgramSource, ProgramSource.source_id == Source.id)
        .join(Program, Program.id == ProgramSource.program_id)
        .where(published_program)
        .distinct()
        .order_by(asc(Source.name), asc(Source.id))
    ).mappings()
    sources = [SourceFilterOption(**row) for row in source_rows]

    geography_rows = connection.execute(
        select(Geography.slug, Geography.name)
        .select_from(Geography)
        .join(ProgramGeography, ProgramGeography.geography_id == Geography.id)
        .join(Program, Program.id == ProgramGeography.program_id)
        .where(published_program)
        .distinct()
        .order_by(asc(Geography.name), asc(Geography.slug))
    ).mappings()
    geographies = [TaxonomyOption(**row) for row in geography_rows]

    theme_rows = connection.execute(
        select(Theme.slug, Theme.name)
        .select_from(Theme)
        .join(ProgramTheme, ProgramTheme.theme_id == Theme.id)
        .join(Program, Program.id == ProgramTheme.program_id)
        .where(published_program)
        .distinct()
        .order_by(asc(Theme.name), asc(Theme.slug))
    ).mappings()
    themes = [TaxonomyOption(**row) for row in theme_rows]

    funding_rows = connection.execute(
        select(ProgramFunding.value_kind)
        .select_from(ProgramFunding)
        .join(Program, Program.id == ProgramFunding.program_id)
        .where(published_program)
        .distinct()
    ).scalars()
    available_funding_kinds = set(funding_rows)
    funding_kinds = [kind for kind in FundingValueKind if kind in available_funding_kinds]

    deadline_row = connection.execute(
        select(
            func.min(ProgramDeadline.deadline_on).label("min_deadline"),
            func.max(ProgramDeadline.deadline_on).label("max_deadline"),
        )
        .select_from(ProgramDeadline)
        .join(Program, Program.id == ProgramDeadline.program_id)
        .where(published_program)
    ).mappings().one()

    return FilterOptions(
        sources=sources,
        geographies=geographies,
        themes=themes,
        funding_kinds=funding_kinds,
        deadline=DeadlineBounds(**deadline_row),
    )

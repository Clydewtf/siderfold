from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError

from app.api.v1.schemas import Page, ProgramDetail, ProgramListItem
from app.domain.models import (
    FundingValueKind,
    Geography,
    Program,
    ProgramDeadline,
    ProgramFunding,
    ProgramGeography,
    ProgramTheme,
    PublicationStatus,
    Source,
    Theme,
)
from app.main import create_app
from tests.fixtures.canonical import PUBLISHED_AT, insert_program_with_source


pytestmark = pytest.mark.postgres


class UnavailableEngine:
    def connect(self) -> None:
        raise OperationalError("SELECT 1", {}, ConnectionError("database is down"))


class BrokenEngine:
    def connect(self) -> None:
        raise RuntimeError("unexpected test failure")


def _insert_named_source(connection: Connection, name: str) -> UUID:
    source_id = uuid4()
    connection.execute(
        insert(Source).values(
            id=source_id,
            name=name,
            canonical_url=f"https://{name.lower().replace(' ', '-')}.example.test",
        )
    )
    return source_id


def _seed_catalog(connection: Connection) -> dict[str, UUID]:
    main_source_id = _insert_named_source(connection, "Main Source")
    alpha_id = insert_program_with_source(
        connection,
        source_id=main_source_id,
        title="Published Alpha",
        publication_status=PublicationStatus.PUBLISHED,
        published_at=PUBLISHED_AT,
    )
    beta_id = insert_program_with_source(
        connection,
        source_id=main_source_id,
        title="Published Beta",
        publication_status=PublicationStatus.PUBLISHED,
        published_at=PUBLISHED_AT,
    )

    hidden_source_id = _insert_named_source(connection, "Hidden Source")
    draft_id = insert_program_with_source(
        connection,
        source_id=hidden_source_id,
        title="Draft Hidden",
    )
    archived_source_id = _insert_named_source(connection, "Archived Source")
    archived_id = insert_program_with_source(
        connection,
        source_id=archived_source_id,
        title="Archived Hidden",
        publication_status=PublicationStatus.ARCHIVED,
        published_at=PUBLISHED_AT,
    )

    geography_id = uuid4()
    hidden_geography_id = uuid4()
    theme_id = uuid4()
    hidden_theme_id = uuid4()
    connection.execute(
        insert(Geography),
        [
            {"id": geography_id, "slug": "russia", "name": "Russia"},
            {"id": hidden_geography_id, "slug": "hidden-region", "name": "Hidden region"},
        ],
    )
    connection.execute(
        insert(Theme),
        [
            {"id": theme_id, "slug": "education", "name": "Education"},
            {"id": hidden_theme_id, "slug": "hidden-theme", "name": "Hidden theme"},
        ],
    )
    connection.execute(
        insert(ProgramDeadline),
        [
            {"program_id": alpha_id, "deadline_on": date(2026, 9, 15)},
            {"program_id": beta_id, "deadline_on": date(2026, 12, 1)},
            {"program_id": draft_id, "deadline_on": date(2025, 1, 1)},
        ],
    )
    connection.execute(
        insert(ProgramFunding),
        [
            {
                "program_id": alpha_id,
                "value_kind": FundingValueKind.MAXIMUM,
                "currency_code": "RUB",
                "exact_amount": None,
                "min_amount": None,
                "max_amount": Decimal("1000000.00"),
            },
            {
                "program_id": beta_id,
                "value_kind": FundingValueKind.EXACT,
                "currency_code": "RUB",
                "min_amount": None,
                "max_amount": None,
                "exact_amount": Decimal("500000.00"),
            },
        ],
    )
    connection.execute(
        insert(ProgramGeography),
        [
            {"program_id": alpha_id, "geography_id": geography_id},
            {"program_id": draft_id, "geography_id": hidden_geography_id},
        ],
    )
    connection.execute(
        insert(ProgramTheme),
        [
            {"program_id": alpha_id, "theme_id": theme_id},
            {"program_id": draft_id, "theme_id": hidden_theme_id},
        ],
    )
    return {
        "main_source_id": main_source_id,
        "alpha_id": alpha_id,
        "beta_id": beta_id,
        "draft_id": draft_id,
        "archived_id": archived_id,
        "hidden_source_id": hidden_source_id,
        "archived_source_id": archived_source_id,
    }


def test_program_list_is_published_only_and_supports_pagination_and_filters(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        ids = _seed_catalog(connection)

    client = TestClient(create_app(engine=migrated_engine))
    response = client.get(
        "/api/v1/programs",
        params={"page_size": 1, "sort": "title", "order": "asc"},
    )

    assert response.status_code == 200
    page = Page[ProgramListItem].model_validate(response.json())
    assert page.total == 2
    assert page.page == 1
    assert page.page_size == 1
    assert len(page.items) == 1
    assert page.items[0].title == "Published Alpha"
    assert page.items[0].updated_at == PUBLISHED_AT
    assert page.items[0].primary_source.source.id == ids["main_source_id"]
    assert page.items[0].primary_source.source_url.endswith(str(ids["alpha_id"]))

    filtered = client.get(
        "/api/v1/programs",
        params={
            "source_id": str(ids["main_source_id"]),
            "theme": "education",
            "geography": "russia",
            "funding_kind": "maximum",
        },
    )

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == str(ids["alpha_id"])


def test_program_search_filter_and_empty_state_semantics_are_stable(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        ids = _seed_catalog(connection)
        connection.execute(
            update(Program)
            .where(Program.id == ids["beta_id"])
            .values(updated_at=PUBLISHED_AT + timedelta(days=1))
        )

    client = TestClient(create_app(engine=migrated_engine))
    searched = client.get("/api/v1/programs", params={"q": "published alpha"})
    alternatives = client.get(
        "/api/v1/programs",
        params=[("theme", "education"), ("theme", "missing"), ("sort", "updated_at")],
    )
    empty = client.get("/api/v1/programs", params={"theme": "missing"})
    outside_page = client.get("/api/v1/programs", params={"page": 2, "page_size": 2})

    assert searched.status_code == 200
    assert [item["id"] for item in searched.json()["items"]] == [str(ids["alpha_id"])]
    assert alternatives.status_code == 200
    assert alternatives.json()["total"] == 1
    assert alternatives.json()["items"][0]["id"] == str(ids["alpha_id"])
    assert empty.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}
    assert outside_page.json() == {"items": [], "page": 2, "page_size": 2, "total": 2}

    updated_order = client.get(
        "/api/v1/programs",
        params={"sort": "updated_at", "order": "desc"},
    )
    assert [item["id"] for item in updated_order.json()["items"]] == [
        str(ids["beta_id"]),
        str(ids["alpha_id"]),
    ]


def test_program_search_handles_russian_word_forms_typos_and_relevance_sort(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        source_id = _insert_named_source(connection, "Russian Search Source")
        morphology_id = insert_program_with_source(
            connection,
            source_id=source_id,
            title="Грантовая программа для НКО",
            publication_status=PublicationStatus.PUBLISHED,
            published_at=PUBLISHED_AT,
        )
        fuzzy_id = insert_program_with_source(
            connection,
            source_id=source_id,
            title="Конкурс для некоммерческих организаций",
            publication_status=PublicationStatus.PUBLISHED,
            published_at=PUBLISHED_AT,
        )
        insert_program_with_source(
            connection,
            source_id=source_id,
            title="Конкурс для некоммерческих организаций — архив",
            publication_status=PublicationStatus.ARCHIVED,
            published_at=PUBLISHED_AT,
        )

    client = TestClient(create_app(engine=migrated_engine))
    morphology = client.get(
        "/api/v1/programs",
        params={"q": "грантовой программы", "sort": "relevance"},
    )
    typo_tolerant = client.get(
        "/api/v1/programs",
        params={"q": "конкурсс некоммерчиских", "sort": "relevance"},
    )
    relevance_without_query = client.get("/api/v1/programs", params={"sort": "relevance"})
    ascending_relevance = client.get(
        "/api/v1/programs",
        params={"q": "грантовая", "sort": "relevance", "order": "asc"},
    )

    assert morphology.status_code == 200
    assert [item["id"] for item in morphology.json()["items"]] == [str(morphology_id)]
    assert typo_tolerant.status_code == 200
    assert [item["id"] for item in typo_tolerant.json()["items"]] == [str(fuzzy_id)]
    assert relevance_without_query.status_code == 422
    assert relevance_without_query.json()["error"]["details"] == [
        {"field": "sort", "reason": "relevance requires q"}
    ]
    assert ascending_relevance.status_code == 422
    assert ascending_relevance.json()["error"]["details"] == [
        {"field": "order", "reason": "relevance only supports desc"}
    ]


def test_program_detail_has_only_public_fields_and_nested_catalog_data(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        ids = _seed_catalog(connection)

    client = TestClient(create_app(engine=migrated_engine))
    response = client.get(f"/api/v1/programs/{ids['alpha_id']}")

    assert response.status_code == 200
    detail = ProgramDetail.model_validate(response.json())
    assert detail.id == ids["alpha_id"]
    assert detail.publication_status == "published"
    assert detail.updated_at == PUBLISHED_AT
    assert detail.sources[0].source.id == ids["main_source_id"]
    assert [item.model_dump() for item in detail.themes] == [
        {"slug": "education", "name": "Education"}
    ]
    assert [item.model_dump() for item in detail.geographies] == [
        {"slug": "russia", "name": "Russia"}
    ]
    assert detail.funding is not None
    assert detail.funding.value_kind is FundingValueKind.MAXIMUM

    response_text = json.dumps(response.json())
    for internal_field in (
        "raw_capture",
        "staged_record",
        "data_quality",
        "candidate_payload",
        "review_decision",
        "input_fingerprint",
        "adapter_name",
        "warnings",
        "external_content_uri",
        "source_execution",
        "responsible",
        "analytics_snapshot",
        "quality_metric",
        "source_scope",
    ):
        assert internal_field not in response_text


def test_sources_and_filters_only_use_published_programs(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        ids = _seed_catalog(connection)

    client = TestClient(create_app(engine=migrated_engine))
    sources_response = client.get("/api/v1/sources")
    filters_response = client.get("/api/v1/filters")

    assert sources_response.status_code == 200
    sources = sources_response.json()
    assert sources["total"] == 1
    assert sources["items"][0]["id"] == str(ids["main_source_id"])
    assert sources["items"][0]["published_program_count"] == 2

    assert filters_response.status_code == 200
    filters = filters_response.json()
    assert [item["id"] for item in filters["sources"]] == [str(ids["main_source_id"])]
    assert filters["themes"] == [{"slug": "education", "name": "Education"}]
    assert filters["geographies"] == [{"slug": "russia", "name": "Russia"}]
    assert filters["funding_kinds"] == ["exact", "maximum"]
    assert filters["deadline"] == {
        "min_deadline": "2026-09-15",
        "max_deadline": "2026-12-01",
    }


def test_read_api_returns_stable_validation_not_found_and_database_errors(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        ids = _seed_catalog(connection)

    client = TestClient(create_app(engine=migrated_engine))
    invalid_page = client.get("/api/v1/programs", params={"page": 0})
    invalid_range = client.get(
        "/api/v1/programs",
        params={"deadline_from": "2026-12-01", "deadline_to": "2026-01-01"},
    )
    blank_query = client.get("/api/v1/programs", params={"q": "   "})
    invalid_id = client.get("/api/v1/programs/not-a-uuid")
    draft = client.get(f"/api/v1/programs/{ids['draft_id']}")
    archived = client.get(f"/api/v1/programs/{ids['archived_id']}")

    assert invalid_page.status_code == 422
    assert invalid_page.json()["error"]["code"] == "invalid_request"
    assert invalid_page.json()["error"]["details"][0]["field"] == "query.page"
    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "invalid_request"
    assert invalid_range.json()["error"]["details"][0]["field"] == "deadline"
    assert blank_query.status_code == 422
    assert blank_query.json()["error"] == {
        "code": "invalid_request",
        "message": "q must not be blank.",
        "details": [{"field": "q", "reason": "must not be blank"}],
    }
    assert invalid_id.status_code == 422
    assert invalid_id.json()["error"]["code"] == "invalid_request"
    assert draft.status_code == archived.status_code == 404
    assert draft.json() == archived.json()
    assert draft.json()["error"]["code"] == "program_not_found"

    unavailable_client = TestClient(create_app(engine=UnavailableEngine()))
    unavailable = unavailable_client.get("/api/v1/programs")
    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "error": {
            "code": "database_unavailable",
            "message": "The read database is temporarily unavailable.",
            "details": [],
        }
    }

    broken_client = TestClient(
        create_app(engine=BrokenEngine()),
        raise_server_exceptions=False,
    )
    broken = broken_client.get("/api/v1/programs")
    assert broken.status_code == 500
    assert broken.json() == {
        "error": {
            "code": "internal_error",
            "message": "Internal server error.",
            "details": [],
        }
    }


def test_openapi_documents_versioned_public_contract_without_internal_fields(
    migrated_engine: Engine,
) -> None:
    spec = create_app(engine=migrated_engine).openapi()
    assert spec["info"]["version"] == "0.8.0"
    paths = spec["paths"]
    assert {
        "/api/v1/programs",
        "/api/v1/programs/{program_id}",
        "/api/v1/sources",
        "/api/v1/filters",
    } <= set(paths)

    program_parameters = {
        parameter["name"]
        for parameter in paths["/api/v1/programs"]["get"]["parameters"]
    }
    assert {
        "page",
        "page_size",
        "sort",
        "order",
        "q",
        "source_id",
        "theme",
        "geography",
        "funding_kind",
        "deadline_from",
        "deadline_to",
    } <= program_parameters
    sort_parameter = next(
        parameter
        for parameter in paths["/api/v1/programs"]["get"]["parameters"]
        if parameter["name"] == "sort"
    )
    sort_schema_name = sort_parameter["schema"]["$ref"].rsplit("/", maxsplit=1)[-1]
    assert "updated_at" in spec["components"]["schemas"][sort_schema_name]["enum"]
    assert "relevance" in spec["components"]["schemas"][sort_schema_name]["enum"]
    source_parameters = {
        parameter["name"]
        for parameter in paths["/api/v1/sources"]["get"]["parameters"]
    }
    assert {"page", "page_size", "sort", "order", "q"} <= source_parameters

    program_list_response = paths["/api/v1/programs"]["get"]["responses"]["200"]
    detail_response = paths["/api/v1/programs/{program_id}"]["get"]["responses"]["200"]
    assert program_list_response["content"]["application/json"]["schema"]["$ref"].startswith(
        "#/components/schemas/Page_"
    )
    assert detail_response["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ProgramDetail"
    )
    assert paths["/api/v1/programs/{program_id}"]["get"]["responses"]["404"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/ApiErrorResponse")
    assert paths["/api/v1/programs"]["get"]["responses"]["500"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/ApiErrorResponse")

    components = spec["components"]["schemas"]
    public_schema_names = {
        "ProgramListItem",
        "ProgramDetail",
        "SourceRef",
        "SourceLinkPublic",
        "SourcePublic",
        "SourceFilterOption",
        "TaxonomyOption",
        "FundingPublic",
        "FilterOptions",
        "DeadlineBounds",
    }
    public_schema_text = json.dumps(
        {name: components[name] for name in public_schema_names},
        ensure_ascii=False,
    )
    for internal_name in (
        "RawCapture",
        "StagedRecord",
        "DataQualityIssue",
        "ReviewDecision",
        "candidate_payload",
        "warnings",
        "input_fingerprint",
        "adapter_name",
        "external_content_uri",
        "source_execution",
        "responsible",
    ):
        assert internal_name not in public_schema_text

    program_list_properties = components["ProgramListItem"]["properties"]
    assert {"updated_at", "primary_source"} <= set(program_list_properties)
    assert program_list_properties["primary_source"]["$ref"].endswith("/SourceLinkPublic")

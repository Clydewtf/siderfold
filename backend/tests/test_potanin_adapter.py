from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.domain.models import (
    DataQualityIssue,
    Program,
    RawCapture,
    StagedRecord,
    StagedRecordState,
)
from app.import_bridge.service import import_package
from app.sources.adapters.potanin.adapter import (
    POTANIN_SITEMAP_URL,
    PotaninCompetitionsAdapter,
)
from app.sources.contract import AdapterContext, DiscoveredResource, FetchResult
from app.sources.adapters.potanin.http import HttpResponse
from app.sources.adapters.potanin.normalization import (
    extract_per_program_funding,
    normalize_competition_url,
)
from app.sources.adapters.potanin.parsing import (
    parse_competition_page,
    parse_competitions_sitemap,
)
from app.sources.registry import DEFAULT_REGISTRY_PATH, load_registry
from app.sources.runner import execute_adapter


BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = BACKEND_ROOT / "tests" / "fixtures" / "adapters" / "potanin"
OPEN_URL = "https://fondpotanin.ru/competitions/quality-reference-open/"
HISTORIC_URL = "https://fondpotanin.ru/competitions/quality-reference-historic/"
FIXTURE_CAPTURED_AT = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES_ROOT / name).read_bytes()


@dataclass
class FixtureResponseFetcher:
    responses: dict[str, bytes]
    final_urls: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> HttpResponse:
        del timeout_seconds
        self.calls.append(url)
        content = self.responses[url]
        assert len(content) <= max_response_bytes
        return HttpResponse(
            requested_url=url,
            final_url=self.final_urls.get(url, url),
            content=content,
            content_format="application/xml" if url == POTANIN_SITEMAP_URL else "text/html",
            received_at=FIXTURE_CAPTURED_AT,
            response_metadata={"access_method": "fixture-http"},
        )


def _definition():
    return load_registry(DEFAULT_REGISTRY_PATH).get("potanin-competitions")


def _context() -> AdapterContext:
    return AdapterContext(
        source=_definition(),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )


def _adapter_with_catalog(
    *,
    sitemap_name: str = "sitemap.xml",
    open_page_name: str = "open.html",
    historic_page_name: str = "historic.html",
    final_urls: dict[str, str] | None = None,
) -> tuple[PotaninCompetitionsAdapter, FixtureResponseFetcher]:
    fetcher = FixtureResponseFetcher(
        responses={
            POTANIN_SITEMAP_URL: _fixture_bytes(sitemap_name),
            OPEN_URL: _fixture_bytes(open_page_name),
            HISTORIC_URL: _fixture_bytes(historic_page_name),
        },
        final_urls=final_urls or {},
    )
    return PotaninCompetitionsAdapter(fetcher=fetcher), fetcher


def test_sitemap_accepts_only_canonical_competition_cards() -> None:
    parsed = parse_competitions_sitemap(_fixture_bytes("sitemap.xml"))

    assert parsed.issues == ()
    assert [entry.url for entry in parsed.entries] == [OPEN_URL, HISTORIC_URL]
    assert parsed.entries[0].last_modified_at == "2026-08-28T12:59:02+03:00"


def test_competition_page_maps_source_fields_without_following_external_links() -> None:
    parsed = parse_competition_page(
        _fixture_bytes("open.html"),
        source_url=OPEN_URL,
        sitemap_last_modified_at="2026-08-28T12:59:02+03:00",
    )

    assert parsed.issues == ()
    assert parsed.record_payload["record_key"] == OPEN_URL
    assert parsed.record_payload["deadline_on"] == "2026-11-30"
    assert parsed.record_payload["funding"] == {
        "value_kind": "maximum",
        "currency_code": "RUB",
        "max_amount": "500000",
    }
    payload = parsed.record_payload["payload"]
    assert payload["source_status"] == "open"
    assert payload["source_last_modified_at"] == "2026-08-28T12:59:02+03:00"
    assert payload["application"] == {
        "start_on": "2025-12-19",
        "end_on": "2026-11-30",
        "url": "https://zayavka.fondpotanin.ru/ru/",
        "candidate_urls": ["https://zayavka.fondpotanin.ru/ru/"],
        "date_evidence": [
            "Прием заявок проводится с 19 декабря 2025 года по 30 ноября 2026 года."
        ],
    }
    assert payload["funding"]["total_grant_fund"]["value"] == {
        "value_kind": "exact",
        "currency_code": "RUB",
        "exact_amount": "25000000",
    }
    assert payload["links"]["document_urls"] == [
        "https://fondpotanin.ru/upload/documents/rules.pdf"
    ]
    assert payload["links"]["result_urls"] == [
        "https://fondpotanin.ru/press/news/quality-reference-results/"
    ]
    assert {theme["slug"] for theme in payload["taxonomy"]["themes"]} == {
        "civil-society",
        "culture",
        "education",
        "philanthropy",
        "science",
        "social-sport",
    }
    assert payload["taxonomy"]["geographies"] == [{"slug": "russia", "name": "Россия"}]


def test_page_normalizes_range_and_ambiguous_per_program_funding_without_guessing() -> None:
    range_page = parse_competition_page(
        _fixture_bytes("range-support.html"),
        source_url="https://fondpotanin.ru/competitions/quality-reference-range/",
        sitemap_last_modified_at=None,
    )
    ambiguous_page = parse_competition_page(
        _fixture_bytes("multi-support.html"),
        source_url="https://fondpotanin.ru/competitions/quality-reference-multi/",
        sitemap_last_modified_at=None,
    )

    assert range_page.issues == ()
    assert range_page.record_payload["deadline_on"] == "2026-08-31"
    assert range_page.record_payload["funding"] == {
        "value_kind": "range",
        "currency_code": "RUB",
        "min_amount": "100000",
        "max_amount": "300000",
    }
    assert ambiguous_page.issues == ()
    assert ambiguous_page.record_payload["funding"] == {"value_kind": "unknown"}
    assert ambiguous_page.record_payload["warnings"] == ["per_program_funding_ambiguous"]
    assert len(ambiguous_page.record_payload["payload"]["funding"]["per_program"]["breakdown"]) == 2


def test_per_program_funding_preserves_each_supported_value_kind() -> None:
    exact = extract_per_program_funding(
        ["Размер гранта составляет 250 000 рублей."]
    )
    minimum = extract_per_program_funding(
        ["Минимальный размер поддержки — 50 000 рублей."]
    )
    maximum = extract_per_program_funding(
        ["Максимальный размер поддержки — 500 000 рублей."]
    )
    unknown = extract_per_program_funding(
        [
            "Максимальный размер поддержки для организаций — 1 млн рублей.",
            "Максимальный размер поддержки для авторов — 500 тыс. рублей.",
        ]
    )
    not_stated = extract_per_program_funding(["Условия финансирования опубликованы отдельно."])

    assert exact.funding.value_kind == "exact"
    assert minimum.funding.value_kind == "minimum"
    assert maximum.funding.value_kind == "maximum"
    assert unknown.funding.value_kind == "unknown"
    assert unknown.warning == "per_program_funding_ambiguous"
    assert not_stated.funding.value_kind == "not_stated"


def test_unexpected_page_and_conflicting_total_fund_are_explicit_parser_errors() -> None:
    unexpected = parse_competition_page(
        _fixture_bytes("unexpected-shape.html"),
        source_url="https://fondpotanin.ru/competitions/quality-reference-unexpected/",
        sitemap_last_modified_at=None,
    )
    conflicting = parse_competition_page(
        _fixture_bytes("conflicting-fund.html"),
        source_url="https://fondpotanin.ru/competitions/quality-reference-conflict/",
        sitemap_last_modified_at=None,
    )

    assert {issue.code for issue in unexpected.issues} >= {"title_missing"}
    assert {issue.code for issue in conflicting.issues} == {"total_grant_fund_conflict"}


def test_unexpected_card_content_type_becomes_a_reviewable_row_error() -> None:
    adapter, _fetcher = _adapter_with_catalog()
    extracted = adapter.extract(
        FetchResult(
            resource=DiscoveredResource(
                external_key="potanin:competition:format",
                url=OPEN_URL,
                metadata={"kind": "competition-card", "discovery_index": 1},
            ),
            final_url=OPEN_URL,
            content=b"not HTML",
            content_format="application/pdf",
            received_at=FIXTURE_CAPTURED_AT,
            external_content_uri="urn:sha256:format",
        ),
        context=_context(),
    )
    validation = adapter.validate(extracted.records, context=_context())

    assert validation.rows[0].record is not None
    assert {issue.code for issue in validation.rows[0].issues} == {
        "unexpected_card_content_type"
    }


@pytest.mark.parametrize(
    "url",
    (
        "https://fondpotanin.ru/competitions/../activity/",
        "https://fondpotanin.ru/competitions/%2e%2e/activity/",
        "https://fondpotanin.ru/competitions/%2Factivity/",
    ),
)
def test_card_url_rejects_path_traversal_or_encoded_separators(url: str) -> None:
    with pytest.raises(ValueError, match="path traversal"):
        normalize_competition_url(url)


def test_duplicate_normalized_sitemap_url_stops_before_any_card_fetch() -> None:
    adapter, fetcher = _adapter_with_catalog(sitemap_name="duplicate-sitemap.xml")

    execution = execute_adapter(
        _definition(),
        adapter,
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )

    assert execution.package is None
    assert execution.report.status == "failed"
    assert execution.report.statistics.duplicates == 1
    assert {issue.code for issue in execution.report.issues} == {"duplicate_sitemap_url"}
    assert fetcher.calls == [POTANIN_SITEMAP_URL]


def test_fixture_dry_run_has_complete_capture_trace_and_quality_metrics() -> None:
    adapter, fetcher = _adapter_with_catalog()

    execution = execute_adapter(
        _definition(),
        adapter,
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )

    assert execution.package is not None
    assert execution.report.status == "completed"
    assert execution.report.statistics.model_dump(exclude={"response_bytes"}) == {
        "discovered": 2,
        "fetched": 3,
        "extracted": 2,
        "valid": 2,
        "warnings": 0,
        "errors": 0,
        "duplicates": 0,
        "requests": 3,
    }
    assert execution.report.quality is not None
    assert execution.report.quality.completeness.model_dump() == {
        "numerator": 2,
        "denominator": 2,
        "value": 1.0,
    }
    assert execution.report.quality.validity.value == 1.0
    assert execution.report.quality.duplicate_rate.value == 0.0
    assert execution.report.quality.freshness.model_dump() == {
        "numerator": 2,
        "denominator": 2,
        "value": 1.0,
        "newest_source_last_modified_at": "2026-08-28T12:59:02+03:00",
        "captured_at": FIXTURE_CAPTURED_AT,
    }
    assert len(execution.package.captures) == 3
    assert execution.package.captures[0].rows == ()
    assert [capture.capture.source_url for capture in execution.package.captures] == [
        POTANIN_SITEMAP_URL,
        OPEN_URL,
        HISTORIC_URL,
    ]
    assert fetcher.calls == [POTANIN_SITEMAP_URL, OPEN_URL, HISTORIC_URL]


def test_non_dry_run_archives_each_raw_response_outside_the_repository(
    tmp_path: Path,
) -> None:
    adapter, _fetcher = _adapter_with_catalog()

    execution = execute_adapter(
        _definition(),
        adapter,
        dry_run=False,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
        raw_capture_dir=tmp_path,
    )

    assert execution.package is not None
    capture_uris = [
        capture.capture.external_content_uri for capture in execution.package.captures
    ]
    assert len(capture_uris) == 3
    assert all(uri.startswith(tmp_path.resolve().as_uri()) for uri in capture_uris)
    assert {Path(urlparse(uri).path).suffix for uri in capture_uris} == {".xml", ".html"}
    assert all(Path(urlparse(uri).path).is_file() for uri in capture_uris)


def test_redirect_outside_allowlist_is_rejected_before_extract() -> None:
    adapter, _fetcher = _adapter_with_catalog(
        final_urls={OPEN_URL: "https://outside.example.test/competition"}
    )

    execution = execute_adapter(
        _definition(),
        adapter,
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )

    assert execution.package is None
    assert execution.report.status == "failed"
    assert execution.report.issues[-1].code == "url_not_allowed"


@pytest.mark.postgres
def test_conflicting_source_data_is_staged_as_quality_issue_without_publication(
    migrated_engine: Engine,
) -> None:
    adapter, _fetcher = _adapter_with_catalog(open_page_name="conflicting-fund.html")
    execution = execute_adapter(
        _definition(),
        adapter,
        dry_run=False,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )

    assert execution.package is not None
    assert execution.report.status == "completed"
    assert execution.report.statistics.errors == 1
    with migrated_engine.begin() as connection:
        report = import_package(connection, execution.package)

    assert report.error_count == 1
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 3
        assert connection.scalar(select(func.count()).select_from(Program)) == 0
        assert set(connection.scalars(select(StagedRecord.state))) == {
            StagedRecordState.ERROR,
            StagedRecordState.REVIEW,
        }
        quality_codes = set(connection.scalars(select(DataQualityIssue.code)))
        assert "import_total_grant_fund_conflict_1" in quality_codes

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.sources.adapters.potanin.http import HttpResponse
from app.sources.adapters.timchenko.adapter import (
    TIMCHENKO_CATALOG_URLS,
    TimchenkoCompetitionsAdapter,
)
from app.sources.adapters.timchenko.normalization import normalize_competition_url, theme_from_source_category
from app.sources.adapters.timchenko.parsing import parse_catalog_page, parse_competition_page
from app.sources.contract import AdapterContext, DiscoveredResource, FetchResult
from app.sources.registry import DEFAULT_REGISTRY_PATH, load_registry
from app.sources.runner import execute_adapter, resolve_adapter


BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = BACKEND_ROOT / "tests" / "fixtures" / "adapters" / "timchenko"
OPEN_URL = "https://fondtimchenko.ru/contests/programs/novye-iskateli-2026/"
SILA_URL = "https://fondtimchenko.ru/contests/programs/sila-vnimaniya-2026/"
READY_URL = "https://fondtimchenko.ru/contests/ready/novye-iskateli-2025/"
ARCHIVE_URL = "https://fondtimchenko.ru/contests/archive/novye-iskateli-2024/"
OPEN_DOCUMENT_URL = "https://fondtimchenko.ru/upload/iblock/timchenko/novye-iskateli-2026.pdf"
READY_WINNERS_URL = "https://fondtimchenko.ru/upload/iblock/timchenko/winners-2025.pdf"
VK_URL = "https://vk.me/novyeiskateli2026"
FIXTURE_CAPTURED_AT = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES_ROOT / name).read_bytes()


def _pdf_bytes() -> bytes:
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(stream)
    return stream.getvalue()


@dataclass
class FixtureResponseFetcher:
    responses: dict[str, bytes]
    content_formats: dict[str, str] = field(default_factory=dict)
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
            content_format=self.content_formats.get(
                url,
                "application/pdf" if url.endswith(".pdf") else "text/html",
            ),
            received_at=FIXTURE_CAPTURED_AT,
            response_metadata={"access_method": "fixture-http"},
        )


def _definition():
    return load_registry(DEFAULT_REGISTRY_PATH).get("timchenko-competitions")


def _context() -> AdapterContext:
    return AdapterContext(
        source=_definition(),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )


def _responses() -> dict[str, bytes]:
    return {
        TIMCHENKO_CATALOG_URLS["programs"]: _fixture_bytes("programs.html"),
        TIMCHENKO_CATALOG_URLS["ready"]: _fixture_bytes("ready.html"),
        TIMCHENKO_CATALOG_URLS["archive"]: _fixture_bytes("archive.html"),
        OPEN_URL: _fixture_bytes("open.html"),
        SILA_URL: _fixture_bytes("sila.html"),
        READY_URL: _fixture_bytes("ready-detail.html"),
        ARCHIVE_URL: _fixture_bytes("archive-detail.html"),
        OPEN_DOCUMENT_URL: _pdf_bytes(),
        READY_WINNERS_URL: _pdf_bytes(),
        "https://fondtimchenko.ru/upload/iblock/timchenko/rules-2025.pdf": _pdf_bytes(),
        "https://fondtimchenko.ru/upload/iblock/timchenko/archive-winners.pdf": _pdf_bytes(),
    }


def _adapter_with_catalog(
    *,
    final_urls: dict[str, str] | None = None,
    content_formats: dict[str, str] | None = None,
) -> tuple[TimchenkoCompetitionsAdapter, FixtureResponseFetcher]:
    fetcher = FixtureResponseFetcher(
        responses=_responses(),
        final_urls=final_urls or {},
        content_formats=content_formats or {},
    )
    return TimchenkoCompetitionsAdapter(fetcher=fetcher), fetcher


def test_catalog_discovery_reads_only_the_three_scoped_card_containers() -> None:
    for section, filename in (
        ("programs", "programs.html"),
        ("ready", "ready.html"),
        ("archive", "archive.html"),
    ):
        parsed = parse_catalog_page(
            _fixture_bytes(filename),
            source_url=TIMCHENKO_CATALOG_URLS[section],
            catalog_section=section,
        )
        assert parsed.entries
        assert all("ignored" not in entry.url and "footer" not in entry.url for entry in parsed.entries)
        assert all(entry.url.startswith(f"https://fondtimchenko.ru/contests/{section}/") or entry.url == OPEN_URL for entry in parsed.entries)


def test_catalog_keeps_valid_card_when_other_contest_is_a_later_sibling() -> None:
    content = """
    <html><body><div id="programs"><div class="card-list">
      <a class="preview-card competition-preview" href="/contests/programs/valid/"><span>Valid</span></a>
      <section><h2>Другие конкурсы Фонда</h2>
        <a class="preview-card competition-preview" href="/contests/programs/other/"><span>Other</span></a>
      </section>
    </div></div></body></html>
    """.encode()

    parsed = parse_catalog_page(content, source_url=TIMCHENKO_CATALOG_URLS["programs"], catalog_section="programs")

    assert [entry.url for entry in parsed.entries] == [
        "https://fondtimchenko.ru/contests/programs/valid/"
    ]


def test_discovery_deduplicates_cards_and_preserves_catalog_metadata() -> None:
    adapter, fetcher = _adapter_with_catalog()
    result = adapter.discover(_context())

    assert [capture.resource.url for capture in result.captures[:3]] == [
        TIMCHENKO_CATALOG_URLS["programs"],
        TIMCHENKO_CATALOG_URLS["ready"],
        TIMCHENKO_CATALOG_URLS["archive"],
    ]
    assert len(result.record_resources) == 4
    assert {resource.metadata["source_status"] for resource in result.record_resources} == {"open", "closed"}
    assert {resource.metadata["catalog_section"] for resource in result.record_resources} == {
        "programs",
        "ready",
        "archive",
    }
    assert sum(issue.code == "duplicate_normalized_url" for issue in result.issues) == 1
    assert fetcher.calls[:3] == list(TIMCHENKO_CATALOG_URLS.values())


def test_open_competition_maps_dates_maximum_funding_documents_and_vk_reference() -> None:
    parsed = parse_competition_page(
        _fixture_bytes("open.html"),
        source_url=OPEN_URL,
        source_status="open",
        catalog_section="programs",
        source_category="Развитие",
    )

    assert parsed.issues == ()
    record = parsed.record_payload
    assert record["title"] == "Новые искатели 2026"
    assert record["payload"]["source_title"] == "Конкурс «Новые искатели» 2026"
    assert record["deadline_on"] == "2026-10-19"
    assert record["funding"] == {
        "value_kind": "maximum",
        "currency_code": "RUB",
        "max_amount": "100000",
    }
    payload = record["payload"]
    assert payload["application"]["start_on"] == "2026-09-03"
    assert payload["application"]["end_on"] == "2026-10-19"
    assert payload["application"]["candidate_urls"] == [VK_URL]
    assert payload["eligibility"]["access_mode"] == "open"
    assert payload["funding"]["total_grant_fund"]["value"] == {"value_kind": "not_stated"}
    assert payload["funding"]["per_program"]["value"]["max_amount"] == "100000"
    assert payload["links"]["document_urls"] == [
        "https://fondtimchenko.ru/ajax/downloads.php?iblock_id=42",
        OPEN_DOCUMENT_URL,
    ]
    inventory = {entry["url"]: entry for entry in payload["content_inventory"]["blocks"][3]["links"]}
    assert inventory[VK_URL]["collection"] == "reference_only"
    assert all("mailto:" not in entry["url"] and "tel:" not in entry["url"] for entry in payload["artifacts"])


def test_stage_widgets_keep_source_titles_dates_document_names_and_paragraphs() -> None:
    content = """
    <html><body><main>
      <h1>Конкурс «Новые искатели» 2026</h1>
      <h2>О конкурсе</h2>
      <p>Первый абзац краткого описания конкурса.</p>
      <p>Второй абзац остаётся отдельной смысловой частью.</p>
      <p>Третий абзац не должен склеиваться с предыдущими.</p>
      <h2>Этапы проведения</h2>
      <div class="section5050-container js-section5050 competition-stage">
        <div class="event-date-display event-date-display--h5">3 сентября 2026</div>
        <h3>Старт приёма заявок</h3>
      </div>
      <div class="section5050-container js-section5050 competition-stage">
        <div class="event-date-display event-date-display--h5">19 октября 2026</div>
        <h3>Окончание приёма заявок</h3>
      </div>
      <div class="section5050-container js-section5050 competition-stage">
        <div class="event-date-display event-date-display--h5">Сентябрь 2026</div>
        <h3>Вебинары для заявителей</h3>
      </div>
      <div class="section5050-container js-section5050 competition-stage">
        <div class="event-date-display event-date-display--h5">с 20 октября по 23 ноября 2026</div>
        <h3>Отбор заявок по формальным признакам</h3>
      </div>
      <div class="section5050-container js-section5050 competition-stage">
        <div class="event-date-display event-date-display--h5">24 ноября 2026</div>
        <h3>Объявление победителей Конкурса</h3>
      </div>
      <section class="docs-download">
        <h2>Документы</h2>
        <div class="docs-download__head"><a href="/ajax/downloads.php?id=7749&amp;file[]=2534">Скачать все</a></div>
        <div class="ui-file-download">
          <div class="ui-file-download__content">
            <div lass="ui-file-download__name weight-medium">Положение о конкурсе Новые искатели 2026</div>
            <div class="ui-file-download__file"><div class="ui-file-download__link">
              <a href="/upload/iblock/638/rules-2026.pdf">Скачать</a>
            </div></div>
          </div>
        </div>
      </section>
    </main></body></html>
    """.encode()

    parsed = parse_competition_page(
        content,
        source_url=OPEN_URL,
        source_status="open",
        catalog_section="programs",
    )

    payload = parsed.record_payload["payload"]
    assert payload["summary"] == (
        "Первый абзац краткого описания конкурса.\n\n"
        "Второй абзац остаётся отдельной смысловой частью.\n\n"
        "Третий абзац не должен склеиваться с предыдущими."
    )
    assert [event["label"] for event in payload["timeline"]] == [
        "Старт приёма заявок",
        "Окончание приёма заявок",
        "Вебинары для заявителей",
        "Отбор заявок по формальным признакам",
        "Объявление победителей Конкурса",
    ]
    assert [event["kind"] for event in payload["timeline"]] == [
        "application_open",
        "application_close",
        "other",
        "evaluation",
        "results",
    ]
    assert [event["date_label"] for event in payload["timeline"]] == [
        "3 сентября 2026",
        "19 октября 2026",
        "Сентябрь 2026",
        "с 20 октября по 23 ноября 2026",
        "24 ноября 2026",
    ]
    assert payload["timeline"][0]["start_on"] == "2026-09-03"
    assert payload["timeline"][1]["end_on"] == "2026-10-19"
    assert payload["timeline"][2]["start_on"] is None
    assert payload["timeline"][2]["end_on"] is None
    assert parsed.record_payload["deadline_on"] == "2026-10-19"

    inventory = {entry["url"]: entry for entry in payload["links"]["inventory"]}
    bundle = next(entry for url, entry in inventory.items() if "/ajax/downloads.php" in url)
    assert bundle["label"] == "Все документы конкурса"
    assert inventory["https://fondtimchenko.ru/upload/iblock/638/rules-2026.pdf"]["label"] == (
        "Положение о конкурсе Новые искатели 2026"
    )


def test_closed_and_archive_pages_keep_h1_year_and_deadline() -> None:
    ready = parse_competition_page(
        _fixture_bytes("ready-detail.html"),
        source_url=READY_URL,
        source_status="closed",
        catalog_section="ready",
        source_category="Развитие",
    )
    archive = parse_competition_page(
        _fixture_bytes("archive-detail.html"),
        source_url=ARCHIVE_URL,
        source_status="closed",
        catalog_section="archive",
        source_category="Развитие",
    )

    assert ready.issues == ()
    assert archive.issues == ()
    assert ready.record_payload["deadline_on"] == "2025-11-12"
    assert archive.record_payload["deadline_on"] == "2024-12-17"
    assert ready.record_payload["payload"]["catalog_section"] == "ready"
    assert archive.record_payload["payload"]["catalog_section"] == "archive"


def test_explicit_invitation_only_text_overrides_timchenko_open_default() -> None:
    parsed = parse_competition_page(
        """
        <main>
          <h1>Конкурс «Тест» 2026</h1>
          <h2>Кто может участвовать</h2>
          <p>Конкурс проводится только по приглашению Фонда.</p>
        </main>
        """.encode(),
        source_url=OPEN_URL,
        source_status="open",
        catalog_section="programs",
    )

    assert parsed.record_payload["payload"]["eligibility"]["access_mode"] == "invitation_only"


def test_taxonomy_geography_contacts_sections_and_inventory_are_review_ready() -> None:
    parsed = parse_competition_page(
        _fixture_bytes("open.html"),
        source_url=OPEN_URL,
        source_status="open",
        catalog_section="programs",
        source_category="Развитие",
    )
    payload = parsed.record_payload["payload"]
    assert {item["slug"] for item in payload["taxonomy"]["themes"]} >= {
        "timchenko-development",
        "education",
        "sports-health",
        "ecology",
        "culture-traditions",
    }
    assert {item["slug"] for item in payload["taxonomy"]["geographies"]} == {
        "central",
        "northwestern",
        "volga",
        "southern",
        "north-caucasian",
        "ural",
        "siberian",
        "far-eastern",
    }
    assert payload["contacts"][0]["email"] == "novyeiskateli@fondtimchenko.ru"
    assert payload["contacts"][0]["phone"] == "8 903 564 49 71"
    assert "Кто может принять участие" in payload["sections"]
    assert payload["content_inventory"]["raw_capture_contains_full_content"] is True
    assert payload["content_inventory"]["blocks"]


@pytest.mark.parametrize(
    ("source_category", "expected"),
    (
        ("Забота", {"slug": "timchenko-care", "name": "Забота"}),
        ("Развитие", {"slug": "timchenko-development", "name": "Развитие"}),
        ("Спецпроекты", {"slug": "timchenko-special-projects", "name": "Спецпроекты"}),
    ),
)
def test_source_categories_become_visible_themes(
    source_category: str,
    expected: dict[str, str],
) -> None:
    assert theme_from_source_category(source_category) == expected


def test_standalone_application_cta_is_not_hidden_by_later_other_contests_block() -> None:
    content = """
    <html><body><main>
      <div class="main-header"><a href="https://vk.me/navigation">Подать заявку</a></div>
      <h1>Конкурс «Тест» 2026</h1>
      <a href="https://vk.me/top-application">Подать заявку</a>
      <section>
        <h2>Другие конкурсы Фонда</h2>
        <a href="https://vk.me/other-competition">Другой конкурс</a>
      </section>
    </main></body></html>
    """.encode()
    parsed = parse_competition_page(content, source_url=OPEN_URL, source_status="open", catalog_section="programs")

    assert parsed.record_payload["payload"]["application"]["candidate_urls"] == [
        "https://vk.me/top-application"
    ]


def test_http_and_https_variants_of_one_application_choose_https_once() -> None:
    content = """
    <html><body><main>
      <h1>Конкурс «Тест» 2026</h1>
      <p>Приём заявок с 1 сентября по 20 октября 2026 года.</p>
      <a href="http://vk.me/test-application">Подать заявку</a>
      <a href="https://vk.me/test-application">Подать заявку</a>
    </main></body></html>
    """.encode()

    parsed = parse_competition_page(
        content,
        source_url=OPEN_URL,
        source_status="open",
        catalog_section="programs",
    )

    application = parsed.record_payload["payload"]["application"]
    assert application["candidate_urls"] == ["https://vk.me/test-application"]
    assert application["url"] == "https://vk.me/test-application"
    assert "application_url_ambiguous" not in parsed.record_payload["warnings"]


def test_subscription_modal_is_excluded_from_content_and_local_upload_is_not_cta() -> None:
    content = """
    <html><body><main>
      <h1>Конкурс «Тест» 2026</h1>
      <p>Приём заявок с 1 сентября по 20 октября 2026 года.</p>
      <h2>Документы конкурса</h2>
      <a href="/upload/instructions/application.pdf">Инструкция по подаче заявки</a>
      <div class="subscription-modal" role="dialog">
        <h2>Подписка успешно оформлена</h2>
        <p>Спасибо за подписку.</p>
      </div>
    </main></body></html>
    """.encode()

    parsed = parse_competition_page(
        content,
        source_url=OPEN_URL,
        source_status="open",
        catalog_section="programs",
    )
    payload = parsed.record_payload["payload"]

    assert payload["application"]["candidate_urls"] == []
    assert payload["links"]["document_urls"] == [
        "https://fondtimchenko.ru/upload/instructions/application.pdf"
    ]
    assert all("Подписка успешно оформлена" not in warning for warning in parsed.record_payload["warnings"])
    assert all(
        block["heading"] != "Подписка успешно оформлена"
        for block in payload["content_inventory"]["blocks"]
    )


def test_artifact_total_byte_limit_preserves_all_cards_and_explains_deferral() -> None:
    responses = _responses()
    baseline_fetcher = FixtureResponseFetcher(responses)
    execute_adapter(
        _definition(),
        TimchenkoCompetitionsAdapter(fetcher=baseline_fetcher),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )
    artifact_urls = [url for url in baseline_fetcher.calls if "/upload/" in url]
    non_artifact_bytes = sum(
        len(responses[url]) for url in baseline_fetcher.calls if url not in artifact_urls
    )
    limited_definition = _definition().model_copy(
        update={
            "limits": _definition().limits.model_copy(
                update={"max_total_bytes": non_artifact_bytes + len(responses[artifact_urls[0]]) - 1}
            )
        }
    )
    limited_fetcher = FixtureResponseFetcher(responses)
    execution = execute_adapter(
        limited_definition,
        TimchenkoCompetitionsAdapter(fetcher=limited_fetcher),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )

    assert execution.report.statistics.discovered == 4
    assert [url for url in limited_fetcher.calls if "/upload/" in url] == [artifact_urls[0]]
    assert execution.report.statistics.artifact_fetched == 0
    assert execution.report.statistics.artifact_deferred >= len(artifact_urls)
    assert any(issue.code == "artifact_response_limit_reached" for issue in execution.report.issues)
    assert execution.package is not None
    rows = [row.record for row in execution.package.rows if row.record is not None]
    assert any(
        artifact.get("collection_reason") == "total_bytes_limit"
        for row in rows
        for artifact in row.payload["artifacts"]
    )


@pytest.mark.parametrize(
    "url",
    (
        "https://fondtimchenko.ru/contests/programs/../foo/",
        "https://fondtimchenko.ru/contests/programs/%2e%2e/foo/",
        "https://fondtimchenko.ru/contests/programs/%2Ffoo/",
        "https://fondtimchenko.ru/contests/",
        "https://outside.example.test/contests/programs/foo/",
    ),
)
def test_competition_url_is_strictly_bounded(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_competition_url(url)


def test_invalid_catalog_shape_and_pagination_are_explicit_errors() -> None:
    missing = parse_catalog_page(
        b"<main><p>changed template</p></main>",
        source_url=TIMCHENKO_CATALOG_URLS["programs"],
        catalog_section="programs",
    )
    paginated = parse_catalog_page(
        _fixture_bytes("pagination.html"),
        source_url=TIMCHENKO_CATALOG_URLS["programs"],
        catalog_section="programs",
    )

    assert "catalog_shape_changed" in {issue.code for issue in missing.issues}
    assert "catalog_pagination_detected" in {issue.code for issue in paginated.issues}


def test_missing_h1_and_conflicting_dates_are_parser_issues() -> None:
    malformed = parse_competition_page(
        _fixture_bytes("malformed.html"),
        source_url=OPEN_URL,
        source_status="open",
        catalog_section="programs",
    )
    conflicting = parse_competition_page(
        "<main><h1>Новые искатели 2026</h1><p>Прием заявок с 3 сентября по 19 октября 2026 года.</p><h2>Этапы</h2><ul><li><h3>Старт приема заявок</h3>4 сентября 2026</li><li><h3>Окончание приема заявок</h3>19 октября 2026</li></ul></main>".encode(),
        source_url=OPEN_URL,
        source_status="open",
        catalog_section="programs",
    )

    assert "title_missing" in {issue.code for issue in malformed.issues}
    assert "application_period_conflict" in {issue.code for issue in conflicting.issues}


def test_explicit_application_stages_override_a_broader_top_campaign_period() -> None:
    parsed = parse_competition_page(
        """
        <main>
          <h1>Конкурс «Среда возможностей» 2026</h1>
          <p>Приём заявок. Приёмная кампания 17.03.2026 – 15.07.2026.</p>
          <h2>Этапы</h2>
          <div class="competition-stage">
            <div class="event-date-display">17 марта 2026</div>
            <h3>Старт приёма заявок</h3>
          </div>
          <div class="competition-stage">
            <div class="event-date-display">28 апреля 2026</div>
            <h3>Окончание приёма заявок</h3>
          </div>
        </main>
        """.encode(),
        source_url=OPEN_URL,
        source_status="closed",
        catalog_section="ready",
    )

    record = parsed.record_payload
    assert record["deadline_on"] == "2026-04-28"
    assert record["payload"]["application"]["start_on"] == "2026-03-17"
    assert record["payload"]["application"]["end_on"] == "2026-04-28"
    conflict = next(issue for issue in parsed.issues if issue.code == "application_period_conflict")
    assert conflict.severity == "warning"


def test_invalid_card_content_type_is_a_row_error() -> None:
    adapter, _fetcher = _adapter_with_catalog()
    extracted = adapter.extract(
        FetchResult(
            resource=DiscoveredResource(
                external_key="timchenko:competition:format",
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
    assert {issue.code for issue in validation.rows[0].issues} == {"unexpected_card_content_type"}


def test_allowlist_redirect_and_request_limits_fail_safely() -> None:
    redirected, _fetcher = _adapter_with_catalog(
        final_urls={
            TIMCHENKO_CATALOG_URLS["programs"]: "https://outside.example.test/catalog",
        }
    )
    execution = execute_adapter(
        _definition(),
        redirected,
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )
    assert execution.report.status == "failed"
    assert any(issue.code == "url_not_allowed" for issue in execution.report.issues)

    limited_definition = _definition().model_copy(
        update={"limits": _definition().limits.model_copy(update={"max_requests": 3})}
    )
    limited_adapter, limited_fetcher = _adapter_with_catalog()
    limited = execute_adapter(
        limited_definition,
        limited_adapter,
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )
    assert limited.report.status == "failed"
    assert len(limited_fetcher.calls) == 3
    assert any(issue.code == "card_request_limit_reached" for issue in limited.report.issues)


def test_dry_run_keeps_hash_uris_and_deduplicates_identical_pdf_captures() -> None:
    adapter, fetcher = _adapter_with_catalog()
    execution = execute_adapter(
        _definition(),
        adapter,
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )

    assert execution.report.status == "completed"
    assert execution.package is not None
    assert execution.report.statistics.artifact_discovered >= execution.report.statistics.artifact_fetched
    assert all(capture.capture.external_content_uri.startswith("urn:sha256:") for capture in execution.package.captures)
    assert execution.report.quality is not None
    assert execution.report.quality.completeness.value == 1.0
    assert len([url for url in fetcher.calls if url.endswith(".pdf")]) > len(
        [capture for capture in execution.package.captures if capture.capture.content_format == "application/pdf"]
    )
    assert VK_URL not in fetcher.calls


def test_registry_registration_and_factory_version_resolution() -> None:
    definition = _definition()
    adapter = resolve_adapter(definition)
    assert isinstance(adapter, TimchenkoCompetitionsAdapter)
    assert adapter.name == "timchenko-competitions"
    assert adapter.version == "1.1.3"
    assert definition.allowed_url_prefixes == (
        "https://fondtimchenko.ru/contests",
        "https://fondtimchenko.ru/upload",
        "https://fondtimchenko.ru/press-center",
    )

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

import app.sources.adapters.fasie.adapter as fasie_adapter_module
from app.review.deduplication import exact_origin_url_match, staged_fingerprint
from app.sources.adapters.fasie.adapter import FasieCompetitionsAdapter, _group_publications
from app.sources.adapters.fasie.artifacts import inspect_fasie_artifact
from app.sources.adapters.fasie.normalization import (
    feed_page_url,
    normalize_fasie_url,
    normalize_online_fasie_api_url,
    normalize_online_fasie_url,
    normalize_title,
    normalize_upload_url,
    parse_publication_datetime,
)
from app.sources.adapters.fasie.parsing import (
    parse_competitions_archive_page,
    parse_feed_page,
    parse_home_page,
    parse_online_competitions_api,
    parse_program_page,
    parse_programs_index_page,
    parse_publication_page,
)
from app.sources.adapters.potanin.http import HttpResponse, SourceFetchError
from app.sources.contract import AdapterContext, DiscoveredResource
from app.sources.registry import DEFAULT_REGISTRY_PATH, is_url_allowed, load_registry
from app.sources.runner import execute_adapter, resolve_adapter


BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = BACKEND_ROOT / "tests" / "fixtures" / "adapters" / "fasie"
CAPTURED_AT = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
HOME_URL = "https://fasie.ru/"
FEED_URL = "https://fasie.ru/press/fund/"
AJAX_URL = "https://fasie.ru/press/news/?ajax=Y&PAGEN_1=2"
ONLINE_URL = "https://online.fasie.ru/m/"
ONLINE_API_URL = "https://online.fasie.ru/api/v2/get-public-common-info"
PROGRAMS_URL = "https://fasie.ru/programs/"
PROGRAM_START_URL = "https://fasie.ru/programs/programma-start/"
ARCHIVE_URL = "https://fasie.ru/competitions/"


ONLINE_API_JSON = """
{
  "activeContests": [
    {"name": "Развитие-ИИ 2026 (очередь 3)", "queriesOpeningDate": "2026-10-22T10:00:00+03:00"}
  ],
  "activeInterestsGetheringContests": [
    {"name": "Аккредитация МТК", "submissionEndDate": null}
  ]
}
""".encode()

PROGRAMS_INDEX_HTML = """
<html><body><h1>Программы</h1>
  <a href="/programs/programma-start/">Старт</a>
</body></html>
""".encode()

PROGRAM_START_HTML = """
<html><body><h1>Программа «Старт»</h1>
<section id="content-tab3"><table class="table-konkurs"><tbody>
<tr><th>Конкурс</th><th>Условия</th><th>Статус</th></tr>
<tr>
  <td>Развитие-ИИ</td>
  <td>Размер гранта: до 5 млн рублей. Участники: малые предприятия.</td>
  <td><a href="https://fasie.ru/press/fund/launch-ai-2026/">Приём заявок до 30 сентября 2026 г.</a></td>
</tr>
</tbody></table></section></body></html>
""".encode()

ARCHIVE_HTML = """
<html><body><ul class="js-result-block">
  <li><h2><a href="/press/fund/result-med-2026/">ПОДВЕДЕНЫ ИТОГИ ПО КОНКУРСУ «СТАРТ-МЕД» (ОЧЕРЕДЬ 1)</a></h2><b>01.09.2026</b></li>
  <li><h2><a href="/press/fund/archive-old-2025/">ПОДВЕДЕНЫ ИТОГИ ПО КОНКУРСУ «АРХИВНЫЙ-2025»</a></h2><b>01.09.2025</b></li>
</ul></body></html>
""".encode()

DATE_FEED_2_HTML = """
<html><body><ul class="js-result">
  <a href="/press/fund/old-launch-before-cutoff/"><h5>Запуск конкурса \xabСтарый\xbb</h5><b>01.09.2025</b></a>
</ul></body></html>
""".encode()


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES_ROOT / name).read_bytes()


def _pdf_bytes(*, pages: int = 1) -> bytes:
    stream = BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    writer.write(stream)
    return stream.getvalue()


def _office_bytes(*, kind: str, xml: bytes | None = None) -> bytes:
    xml = xml or "<root><p>Документ конкурса</p></root>".encode()
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        if kind == "docx":
            archive.writestr("word/document.xml", xml)
            archive.writestr("[Content_Types].xml", b"<Types/>")
        else:
            archive.writestr("xl/sharedStrings.xml", xml)
            archive.writestr("[Content_Types].xml", b"<Types/>")
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
            content_format=self.content_formats.get(url, "text/html"),
            received_at=CAPTURED_AT,
            response_metadata={"access_method": "fixture-http"},
        )

    def post_json(
        self,
        url: str,
        *,
        payload: dict[str, object],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> HttpResponse:
        assert payload == {"newsShowOnStartPage": True, "newsShowOnInnerPages": False}
        return self.get(
            url,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )


class FailingResponseFetcher:
    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> HttpResponse:
        del url, timeout_seconds, max_response_bytes
        raise OSError("simulated network failure")


@dataclass
class RestrictedResponseFetcher:
    calls: list[str] = field(default_factory=list)

    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> HttpResponse:
        del timeout_seconds, max_response_bytes
        self.calls.append(url)
        raise SourceFetchError(f"HTTP 403 for {url}")


def _definition():
    return load_registry(DEFAULT_REGISTRY_PATH).get("fasie-competitions")


def _context() -> AdapterContext:
    return AdapterContext(
        source=_definition(),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )


def _detail_url(slug: str) -> str:
    return f"https://fasie.ru/press/fund/{slug}/"


def _responses() -> tuple[dict[str, bytes], dict[str, str]]:
    pages = {
        HOME_URL: "home.html",
        FEED_URL: "feed.html",
        AJAX_URL: None,
        ONLINE_API_URL: None,
        PROGRAMS_URL: None,
        PROGRAM_START_URL: None,
        ARCHIVE_URL: None,
        _detail_url("launch-ai-2026"): "launch-ai-2026.html",
        _detail_url("extension-ai-2026"): "extension-ai-2026.html",
        _detail_url("amendment-ai-2026"): "amendment-ai-2026.html",
        _detail_url("launch-med-2026"): "launch-med-2026.html",
        _detail_url("result-med-2026"): "result-med-2026.html",
        _detail_url("rating-2026"): "rating-2026.html",
        _detail_url("launch-ai-queue-4-2026"): "launch-ai-queue-4-2026.html",
        _detail_url("ordinary-news"): "ordinary-news.html",
    }
    inline_pages = {
        ONLINE_API_URL: ONLINE_API_JSON,
        PROGRAMS_URL: PROGRAMS_INDEX_HTML,
        PROGRAM_START_URL: PROGRAM_START_HTML,
        ARCHIVE_URL: ARCHIVE_HTML,
        AJAX_URL: DATE_FEED_2_HTML,
    }
    responses = {
        url: inline_pages[url] if filename is None else _fixture_bytes(filename)
        for url, filename in pages.items()
    }
    formats = {url: "text/html" for url in pages}
    formats[ONLINE_API_URL] = "application/json"
    artifacts = {
        "https://fasie.ru/upload/docs/ai-rules.pdf": _pdf_bytes(),
        "https://fasie.ru/upload/docs/ai-extension.pdf": _pdf_bytes(pages=2),
        "https://fasie.ru/upload/docs/ai-amendment.docx": _office_bytes(kind="docx"),
        "https://fasie.ru/upload/docs/ai-queue-4.xlsx": _office_bytes(kind="xlsx"),
        "https://fasie.ru/upload/docs/med-rules.pdf": _pdf_bytes(pages=3),
        "https://fasie.ru/upload/docs/med-winners.xlsx": _office_bytes(
            kind="xlsx",
            xml="<root><p>Список победителей конкурса</p></root>".encode(),
        ),
    }
    responses.update(artifacts)
    formats.update(
        {
            url: (
                "application/pdf"
                if url.endswith(".pdf")
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if url.endswith(".docx")
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            for url in artifacts
        }
    )
    return responses, formats


def test_home_priority_only_accepts_press_detail_links() -> None:
    parsed = parse_home_page(_fixture_bytes("home.html"), source_url=HOME_URL)

    assert parsed.competition_urls == (_detail_url("launch-ai-2026"),)
    assert parsed.issues == ()


def test_feed_accepts_route_changing_pagers_and_rejects_malformed_pager() -> None:
    parsed = parse_feed_page(_fixture_bytes("feed.html"), source_url=FEED_URL)
    malformed = parse_feed_page(
        _fixture_bytes("feed-malformed-pager.html"),
        source_url=FEED_URL,
    )

    assert len(parsed.entries) == 8
    assert parsed.next_url == AJAX_URL
    assert parse_feed_page(_fixture_bytes("feed-2.html"), source_url=AJAX_URL).next_url is None
    route_changing = parse_feed_page(
        """
        <ul class='js-result'><a href='/press/fund/example/'><h5>Конкурс</h5><b>16.09.2026</b></a></ul>
        <a href='/press/?ajax=Y&ajax=Y&PAGEN_1=3'>Следующая</a>
        """.encode(),
        source_url=AJAX_URL,
    )
    assert route_changing.next_url == "https://fasie.ru/press/?ajax=Y&PAGEN_1=3"
    assert "malformed_feed_pager" in {issue.code for issue in malformed.issues}


def test_public_inventories_expose_programme_enrichment_and_archive_lifecycle() -> None:
    programs = parse_programs_index_page(PROGRAMS_INDEX_HTML, source_url=PROGRAMS_URL)
    program = parse_program_page(PROGRAM_START_HTML, source_url=PROGRAM_START_URL)
    archive = parse_competitions_archive_page(ARCHIVE_HTML, source_url=ARCHIVE_URL)
    online = parse_online_competitions_api(ONLINE_API_JSON, source_url=ONLINE_URL)

    assert programs.program_urls == (PROGRAM_START_URL,)
    assert len(program.entries) == 1
    entry = program.entries[0]
    assert entry.name == "Развитие-ИИ"
    assert entry.source_status == "open"
    assert entry.detail_url == _detail_url("launch-ai-2026")
    assert entry.funding is not None
    assert entry.funding.max_amount == 5_000_000
    assert archive.entries[0].url == _detail_url("result-med-2026")
    assert online.entries[0].name == "Развитие-ИИ 2026 (очередь 3)"
    assert online.entries[0].deadline_on.isoformat() == "2026-10-22"


def test_publication_types_dates_money_and_references_are_source_specific() -> None:
    launch = parse_publication_page(
        _fixture_bytes("launch-ai-2026.html"),
        source_url=_detail_url("launch-ai-2026"),
    )
    extension = parse_publication_page(
        _fixture_bytes("extension-ai-2026.html"),
        source_url=_detail_url("extension-ai-2026"),
    )
    amendment = parse_publication_page(
        _fixture_bytes("amendment-ai-2026.html"),
        source_url=_detail_url("amendment-ai-2026"),
    )
    result = parse_publication_page(
        _fixture_bytes("result-med-2026.html"),
        source_url=_detail_url("result-med-2026"),
    )
    external = parse_publication_page(
        _fixture_bytes("rating-2026.html"),
        source_url=_detail_url("rating-2026"),
    )

    assert launch.classification == "launch"
    assert launch.queue == "3"
    assert launch.identity == "развитие ии|queue=3|stage=-|year=2026"
    assert launch.funding is not None
    assert launch.funding.max_amount == 5_000_000
    assert launch.application_windows[0].end_on.isoformat() == "2026-09-30"
    assert launch.application_windows[0].end_at.hour == 23
    assert launch.origin_urls == ("https://fasie.ru/competitions/razvitie-ai-3/",)
    assert "https://online.fasie.ru/" in launch.reference_urls
    assert {"slug": "russia", "name": "Россия"} in launch.geographies
    assert all("name" in item for item in launch.themes)
    assert extension.classification == "extension"
    assert extension.application_windows[0].end_at.hour == 10
    assert amendment.classification == "amendment"
    assert amendment.application_windows == ()
    assert result.classification == "result"
    assert result.application_windows == ()
    assert result.funding is None
    assert external.classification == "opportunity"
    assert external.identity is None
    assert external.funding is None
    assert external.origin_kind == "third_party"
    assert external.origin_urls == ("https://sociocenter.info/1000stratups",)


def test_discovery_reads_all_inventories_groups_lifecycle_and_excludes_partner_noise() -> None:
    responses, formats = _responses()
    fetcher = FixtureResponseFetcher(responses, formats)
    adapter = FasieCompetitionsAdapter(fetcher=fetcher)
    execution = execute_adapter(
        _definition(),
        adapter,
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )

    assert execution.report.status == "completed"
    assert execution.report.statistics.errors == 0
    assert execution.report.statistics.valid == 4
    assert execution.report.statistics.artifact_discovered == 6
    assert execution.report.statistics.artifact_fetched == 6
    assert _detail_url("result-med-2026") in fetcher.calls
    assert ONLINE_API_URL in fetcher.calls
    assert PROGRAMS_URL in fetcher.calls
    assert PROGRAM_START_URL in fetcher.calls
    assert ARCHIVE_URL in fetcher.calls
    assert FEED_URL in fetcher.calls
    assert "https://sociocenter.info/1000stratups" not in fetcher.calls
    assert _detail_url("ordinary-news") not in fetcher.calls
    assert _detail_url("old-launch-before-cutoff") not in fetcher.calls
    assert _detail_url("archive-old-2025") not in fetcher.calls

    assert execution.package is not None
    records = [row.record for row in execution.package.rows if row.record is not None]
    assert len(records) == 4
    assert all("ТОП-1000" not in record.title for record in records)
    queue3 = next(record for record in records if "ОЧЕРЕДЬ 3" in record.title)
    assert queue3.deadline_on.isoformat() == "2026-10-22"
    assert queue3.funding is not None
    assert queue3.funding.max_amount == 5_000_000
    assert len(queue3.payload["source_publications"]) == 3
    assert queue3.payload["artifact_summary"] == {"discovered": 3, "captured": 3, "deferred": 0}
    assert queue3.payload["origin_kind"] == "first_party"
    assert queue3.payload["source_status"] == "open"
    assert queue3.payload["online_status"][0]["deadline_on"] == "2026-10-22"
    assert queue3.payload["program_catalog"][0]["program_name"] == "Программа «Старт»"

    queue4 = next(record for record in records if "ОЧЕРЕДЬ 4" in record.title)
    assert queue4.record_key != queue3.record_key
    assert queue4.deadline_on.isoformat() == "2026-09-30"
    completed = next(record for record in records if "СТАРТ-МЕД" in record.title)
    assert completed.payload["source_status"] == "completed"
    assert completed.payload["source_lifecycle_state"] == "archived"
    archive_only = next(record for record in records if "АРХИВНЫЙ-2025" in record.title)
    assert archive_only.payload["source_status"] == "completed"
    assert archive_only.payload["content_inventory"]["raw_capture_contains_full_content"] is False

    # The runner package must contain each raw response only once, even when
    # two FASIE document links happen to have identical bytes.
    captures = execution.package.resolved_captures()
    assert len({capture.capture_key for capture in captures}) == len(captures)
    assert len({capture.raw_bytes for capture in captures}) == len(captures)


def test_online_inventory_updates_a_changed_press_deadline_without_a_second_card() -> None:
    responses, formats = _responses()
    responses[ONLINE_API_URL] = """
    {
      "activeContests": [
        {"name": "Развитие-ИИ 2026 (очередь 3)", "queriesOpeningDate": "2026-10-25T10:00:00+03:00"}
      ]
    }
    """.encode()

    execution = execute_adapter(
        _definition(),
        FasieCompetitionsAdapter(fetcher=FixtureResponseFetcher(responses, formats)),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )

    assert execution.package is not None
    records = [row.record for row in execution.package.rows if row.record is not None]
    queue3_records = [
        record
        for record in records
        if "РАЗВИТИЕ-ИИ" in record.title and "ОЧЕРЕДЬ 3" in record.title
    ]
    assert len(queue3_records) == 1
    queue3 = queue3_records[0]
    assert queue3.deadline_on.isoformat() == "2026-10-25"
    assert queue3.payload["application"]["end_on"] == "2026-10-25"
    assert "online_deadline_overrides_press_deadline" in queue3.warnings


def test_online_only_competition_keeps_the_public_inventory_as_its_raw_evidence() -> None:
    responses, formats = _responses()
    responses[ONLINE_API_URL] = """
    {
      "activeContests": [
        {"name": "Развитие-ИИ 2026 (очередь 3)", "queriesOpeningDate": "2026-10-22T10:00:00+03:00"},
        {"name": "УМНИК-2026 (очередь 1)", "queriesOpeningDate": "2026-10-31T10:00:00+03:00"}
      ]
    }
    """.encode()

    execution = execute_adapter(
        _definition(),
        FasieCompetitionsAdapter(fetcher=FixtureResponseFetcher(responses, formats)),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )

    assert execution.report.statistics.errors == 0
    assert execution.package is not None
    online_only = next(
        row.record
        for row in execution.package.rows
        if row.record is not None and row.record.title == "УМНИК-2026 (очередь 1)"
    )
    assert online_only.payload["source_status"] == "open"
    assert online_only.deadline_on.isoformat() == "2026-10-31"
    assert online_only.payload["links"]["reference_urls"] == [ONLINE_URL]
    capture = next(
        item
        for item in execution.package.resolved_captures()
        if item.capture_key == "fasie-competitions:online"
    )
    assert capture.rows[0].record is not None
    assert capture.rows[0].record.title == "УМНИК-2026 (очередь 1)"


def test_url_hardening_and_registry_factory() -> None:
    definition = _definition()
    assert resolve_adapter(definition).__class__ is FasieCompetitionsAdapter
    assert definition.fasie is not None
    assert definition.fasie.lookback_days == 365
    assert definition.fasie.max_feed_pages == 90
    assert definition.fasie.home_url == HOME_URL
    assert definition.fasie.online_competitions_url == ONLINE_URL
    assert definition.fasie.online_competitions_api_url == ONLINE_API_URL
    assert definition.fasie.programs_url == PROGRAMS_URL
    assert definition.fasie.competitions_archive_url == ARCHIVE_URL
    assert normalize_fasie_url("https://www.fasie.ru/") == HOME_URL
    assert normalize_online_fasie_url("https://online.fasie.ru/m/") == ONLINE_URL
    assert normalize_online_fasie_api_url(ONLINE_API_URL) == ONLINE_API_URL
    assert normalize_upload_url("https://www.fasie.ru/upload/docs/rules.pdf") == (
        "https://fasie.ru/upload/docs/rules.pdf"
    )
    assert is_url_allowed("https://www.fasie.ru/upload/docs/rules.pdf", definition)
    assert is_url_allowed(ONLINE_URL, definition)
    assert is_url_allowed(ONLINE_API_URL, definition)
    assert not is_url_allowed("http://fasie.ru/upload/docs/rules.pdf", definition)
    with pytest.raises(ValueError):
        normalize_fasie_url("http://fasie.ru/")
    with pytest.raises(ValueError):
        normalize_fasie_url("https://fasie.ru/press/fund/%2e%2e/secret/")
    with pytest.raises(ValueError):
        normalize_upload_url("https://evil.example/upload/rules.pdf")
    with pytest.raises(ValueError):
        feed_page_url("https://fasie.ru/press/news/?ajax=Y&PAGEN_1=2&tag=grant")
    with pytest.raises(ValueError):
        normalize_online_fasie_url("https://online.fasie.ru/login/")
    with pytest.raises(ValueError):
        normalize_online_fasie_api_url("https://online.fasie.ru/api/v2/login")

    artifact_url = "https://fasie.ru/upload/docs/rules.pdf"
    redirecting = FixtureResponseFetcher(
        {artifact_url: _pdf_bytes()},
        {artifact_url: "application/pdf"},
        {artifact_url: "https://fasie.ru/press/fund/not-an-artifact/"},
    )
    with pytest.raises(ValueError):
        FasieCompetitionsAdapter(fetcher=redirecting).fetch(
            DiscoveredResource(
                external_key="fasie:test-artifact",
                url=artifact_url,
                metadata={"kind": "fasie-artifact"},
            ),
            _context(),
        )


def test_dates_are_moscow_local_and_month_without_year_uses_fallback() -> None:
    parsed = parse_publication_datetime("07.09.2026 16:05:00")
    fallback = parse_publication_datetime("12 октября", fallback_year=2026)

    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 3 * 60 * 60
    assert parsed.hour == 16
    assert fallback is not None
    assert fallback.date().isoformat() == "2026-10-12"


def test_current_application_wording_keeps_deadline_and_balanced_title_quotes() -> None:
    publication = parse_publication_page(
        """
        <div class="plane_text">
          <h1>Запуск конкурса «Цифровые решения»</h1>
          <div itemprop="text">
            <p>Заявки на конкурс «Цифровые решения» (очередь 3) будут приниматься до 10:00 (мск) 12 октября 2026 года.</p>
            <a href="https://external.example.test/application">Подать заявку</a>
          </div>
        </div>
        """.encode(),
        source_url=_detail_url("digital-solutions-2026"),
        feed_published_at=CAPTURED_AT,
    )

    assert normalize_title(publication.source_title) == "«Цифровые решения»"
    assert publication.application_windows[0].end_on.isoformat() == "2026-10-12"
    assert publication.application_windows[0].end_at.hour == 10


def test_third_party_application_is_not_emitted_as_a_fasie_grant_candidate() -> None:
    publication = parse_publication_page(
        """
        <div class="plane_text">
          <h1>Конкурс «Внешняя возможность» 2026</h1>
          <div itemprop="text">
            <p>Открыт приём заявок на конкурс.</p>
            <a href="https://external.example.test/competition/primary/">Подать заявку</a>
          </div>
        </div>
        """.encode(),
        source_url=_detail_url("external-opportunity-2026"),
        feed_published_at=CAPTURED_AT,
    )
    groups, issues = _group_publications(
        (publication,),
        as_of=CAPTURED_AT,
        cutoff=CAPTURED_AT.date(),
    )

    assert issues == ()
    assert groups == ()


def test_explicit_fasie_press_link_merges_a_general_announcement_into_canonical_card() -> None:
    canonical = parse_publication_page(
        """
        <div class='plane_text'><h1>Запуск конкурса «Развитие-МТК» (очередь 1)</h1>
        <div itemprop='text'><p>Фонд содействия инновациям объявляет о начале конкурса.
        Приём заявок до 19 октября 2026 года.</p></div></div>
        """.encode(),
        source_url=_detail_url("razvitie-mtk"),
        feed_published_at=CAPTURED_AT,
    )
    announcement = parse_publication_page(
        """
        <div class='plane_text'><h1>Фонд запускает новый конкурс для МТК</h1>
        <div itemprop='text'><p>Фонд содействия инновациям запускает новый конкурс
        «Развитие-МТК» (очередь 1). <a href='/press/fund/razvitie-mtk/'>Развитие-МТК</a>
        Приём заявок до 19 октября 2026 года.</p></div></div>
        """.encode(),
        source_url=_detail_url("mtk-announcement"),
        feed_published_at=CAPTURED_AT,
    )
    groups, issues = _group_publications(
        (canonical, announcement),
        as_of=CAPTURED_AT,
        cutoff=CAPTURED_AT.date(),
    )

    assert issues == ()
    assert len(groups) == 1
    record = groups[0].payload
    assert record["record_url"] == _detail_url("razvitie-mtk")
    assert len(record["payload"]["source_publications"]) == 2


def test_explicit_press_link_merges_all_conflicting_identity_siblings_once() -> None:
    linked_announcement = parse_publication_page(
        """
        <div class='plane_text'><h1>Запуск конкурса «Альфа»</h1>
        <div itemprop='text'><p>Фонд запускает конкурс «Альфа».
        <a href='/press/fund/canonical-beta/'>Основная карточка</a></p></div></div>
        """.encode(),
        source_url=_detail_url("linked-alpha"),
        feed_published_at=CAPTURED_AT,
    )
    alpha_extension = parse_publication_page(
        """
        <div class='plane_text'><h1>Продление приема заявок по конкурсу «Альфа»</h1>
        <div itemprop='text'><p>Заявки принимаются до 30 сентября 2026 года.</p></div></div>
        """.encode(),
        source_url=_detail_url("alpha-extension"),
        feed_published_at=CAPTURED_AT,
    )
    canonical_beta = parse_publication_page(
        """
        <div class='plane_text'><h1>Запуск конкурса «Бета»</h1>
        <div itemprop='text'><p>Официальная карточка конкурса.</p></div></div>
        """.encode(),
        source_url=_detail_url("canonical-beta"),
        feed_published_at=CAPTURED_AT,
    )

    groups, issues = _group_publications(
        (linked_announcement, alpha_extension, canonical_beta),
        as_of=CAPTURED_AT,
        cutoff=CAPTURED_AT.date(),
    )

    assert len(groups) == 1
    assert len(groups[0].payload["payload"]["source_publications"]) == 3
    assert "related_publication_identity_override" in {issue.code for issue in issues}


def test_expired_fasie_launch_is_retained_with_closed_source_status() -> None:
    publication = parse_publication_page(
        """
        <div class='plane_text'><h1>Запуск конкурса «Старт-ИИ» (очередь 1)</h1>
        <div itemprop='text'><p>Фонд содействия инновациям открыл приём заявок.
        Приём заявок до 1 сентября 2026 года.</p></div></div>
        """.encode(),
        source_url=_detail_url("start-ai-closed"),
        feed_published_at=CAPTURED_AT,
    )
    groups, issues = _group_publications(
        (publication,),
        as_of=CAPTURED_AT,
        cutoff=CAPTURED_AT.date(),
    )

    assert issues == ()
    assert len(groups) == 1
    assert groups[0].payload["payload"]["source_status"] == "closed"


def test_fasie_limit_and_error_branches_return_issues_without_constructor_failures() -> None:
    responses, formats = _responses()

    page_limited_definition = _definition().model_copy(
        update={"fasie": _definition().fasie.model_copy(update={"max_feed_pages": 1})}
    )
    page_limited = execute_adapter(
        page_limited_definition,
        FasieCompetitionsAdapter(fetcher=FixtureResponseFetcher(responses, formats)),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )
    assert any(issue.code == "feed_page_limit_reached" for issue in page_limited.report.issues)

    wrong_mime = execute_adapter(
        _definition(),
        FasieCompetitionsAdapter(
            fetcher=FixtureResponseFetcher(
                responses,
                {**formats, FEED_URL: "application/pdf"},
            )
        ),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )
    assert any(issue.code == "unexpected_feed_content_type" for issue in wrong_mime.report.issues)

    record_limited_definition = _definition().model_copy(
        update={"limits": _definition().limits.model_copy(update={"max_records": 1})}
    )
    record_limited = execute_adapter(
        record_limited_definition,
        FasieCompetitionsAdapter(fetcher=FixtureResponseFetcher(responses, formats)),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )
    assert any(issue.code == "record_limit_exceeded" for issue in record_limited.report.issues)

    failed_fetch = execute_adapter(
        _definition(),
        FasieCompetitionsAdapter(fetcher=FailingResponseFetcher()),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )
    assert any(issue.code == "home_fetch_failed" for issue in failed_fetch.report.issues)
    assert any(issue.code == "feed_fetch_failed" for issue in failed_fetch.report.issues)


def test_fasie_access_restriction_stops_the_run_before_hammering_the_source() -> None:
    fetcher = RestrictedResponseFetcher()
    execution = execute_adapter(
        _definition(),
        FasieCompetitionsAdapter(fetcher=fetcher),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )

    assert fetcher.calls == [HOME_URL]
    assert any(issue.code == "source_access_restricted" for issue in execution.report.issues)


def test_fasie_live_request_pacing_uses_the_registry_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FasieCompetitionsAdapter()
    adapter._last_request_at = 100.0
    delays: list[float] = []
    monkeypatch.setattr(fasie_adapter_module, "monotonic", lambda: 101.25)
    monkeypatch.setattr(fasie_adapter_module, "sleep", delays.append)

    adapter._pace_request(_context())

    assert delays == [0.75]


def test_fasie_total_byte_limit_defers_remaining_artifacts_without_fetching_them() -> None:
    responses, formats = _responses()
    baseline_fetcher = FixtureResponseFetcher(responses, formats)
    execute_adapter(
        _definition(),
        FasieCompetitionsAdapter(fetcher=baseline_fetcher),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
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
    limited_fetcher = FixtureResponseFetcher(responses, formats)
    execution = execute_adapter(
        limited_definition,
        FasieCompetitionsAdapter(fetcher=limited_fetcher),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )

    assert [url for url in limited_fetcher.calls if "/upload/" in url] == [artifact_urls[0]]
    assert execution.report.statistics.artifact_fetched == 0
    assert execution.report.statistics.artifact_deferred == len(artifact_urls)
    assert any(issue.code == "artifact_response_limit_reached" for issue in execution.report.issues)
    assert execution.package is not None
    rows = [row.record for row in execution.package.rows if row.record is not None]
    assert rows
    assert all(
        artifact.get("collection_reason") == "total_bytes_limit"
        for row in rows
        for artifact in row.payload["artifacts"]
    )


def test_fasie_artifact_budget_defers_remaining_files_before_rate_limit() -> None:
    responses, formats = _responses()
    definition = _definition().model_copy(
        update={"fasie": _definition().fasie.model_copy(update={"max_artifact_requests": 1})}
    )
    fetcher = FixtureResponseFetcher(responses, formats)
    execution = execute_adapter(
        definition,
        FasieCompetitionsAdapter(fetcher=fetcher),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=CAPTURED_AT,
    )

    artifact_calls = [url for url in fetcher.calls if "/upload/" in url]
    assert len(artifact_calls) == 1
    assert execution.report.statistics.artifact_fetched == 1
    assert execution.report.statistics.artifact_deferred == 5
    assert any(issue.code == "artifact_fetch_budget_reached" for issue in execution.report.issues)
    assert execution.package is not None
    rows = [row.record for row in execution.package.rows if row.record is not None]
    assert any(
        artifact.get("collection_reason") == "artifact_fetch_budget"
        for row in rows
        for artifact in row.payload["artifacts"]
    )


def test_artifact_inspector_handles_pdf_office_zip_and_unsafe_inputs() -> None:
    pdf = inspect_fasie_artifact(
        _pdf_bytes(pages=121),
        content_format="application/pdf",
        source_url="https://fasie.ru/upload/docs/long.pdf",
    )
    docx = inspect_fasie_artifact(
        _office_bytes(kind="docx"),
        content_format="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        source_url="https://fasie.ru/upload/docs/rules.docx",
    )
    xlsx = inspect_fasie_artifact(
        _office_bytes(kind="xlsx"),
        content_format="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        source_url="https://fasie.ru/upload/docs/rules.xlsx",
    )
    unsafe_stream = BytesIO()
    with ZipFile(unsafe_stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("../escape.xml", b"<root/>")
    unsafe = inspect_fasie_artifact(
        unsafe_stream.getvalue(),
        content_format="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        source_url="https://fasie.ru/upload/docs/unsafe.docx",
    )
    macro_stream = BytesIO()
    with ZipFile(macro_stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/vbaProject.bin", b"macro")
    macro = inspect_fasie_artifact(
        macro_stream.getvalue(),
        content_format="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        source_url="https://fasie.ru/upload/docs/macro.docx",
    )

    assert pdf.payload["kind"] == "pdf"
    assert pdf.payload["text_truncated"] is True
    assert docx.payload["status"] == "inspected"
    assert xlsx.payload["status"] == "inspected"
    assert "artifact_zip_unsafe_path" in {issue.code for issue in unsafe.issues}
    assert "artifact_macro_project" in {issue.code for issue in macro.issues}


def test_cross_source_exact_origin_match_is_explicit_but_portal_is_not() -> None:
    fasie_id = uuid4()
    other_id = uuid4()
    candidate = staged_fingerprint(
        source_id=fasie_id,
        record_key="fasie:publication:test",
        candidate_payload={
            "record_key": "fasie:publication:test",
            "title": "Внешняя возможность",
            "record_url": "https://fasie.ru/press/fund/test/",
            "payload": {
                "origin_urls": ["https://other.example/competition/primary/"],
            },
        },
    )
    target = staged_fingerprint(
        source_id=other_id,
        record_key="other:competition:test",
        candidate_payload={
            "record_key": "other:competition:test",
            "title": "Другая запись",
            "record_url": "https://other.example/competition/primary/",
            "payload": {},
        },
    )
    portal_candidate = staged_fingerprint(
        source_id=fasie_id,
        record_key="fasie:publication:portal",
        candidate_payload={
            "record_key": "fasie:publication:portal",
            "title": "Портал подачи",
            "record_url": "https://fasie.ru/press/fund/portal/",
            "payload": {"origin_urls": ["https://online.fasie.ru/"]},
        },
    )

    assert exact_origin_url_match(candidate, target) == "https://other.example/competition/primary"
    assert exact_origin_url_match(portal_candidate, target) is None

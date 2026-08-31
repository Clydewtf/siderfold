from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.domain.models import (
    IngestionRun,
    Program,
    RawCapture,
    Source,
    StagedRecord,
    TelegramDiscoveryCursor,
    TelegramDiscoveryMessage,
    TelegramDiscoveryMessageUrl,
    TelegramDiscoveryRoute,
    TelegramDiscoveryUrl,
)
from app.sources.adapters.telegram.adapter import TelegramDiscoveryAdapter
from app.sources.adapters.telegram.http import TelegramHttpResponse
from app.sources.adapters.telegram.parsing import parse_telegram_channel_page
from app.sources.registry import DEFAULT_REGISTRY_PATH, is_url_allowed, load_registry
from app.sources.runner import ADAPTER_FACTORIES, run_registered_source
from app.sources.telegram_runner import execute_telegram_discovery


BACKEND_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = BACKEND_ROOT / "tests" / "fixtures" / "adapters" / "telegram"
CHANNEL_URL = "https://t.me/s/cptgrantov"
OLDER_PAGE_URL = "https://t.me/s/cptgrantov?before=103"
FIXTURE_CAPTURED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES_ROOT / name).read_bytes()


@dataclass
class FixtureTelegramFetcher:
    responses: dict[str, bytes]
    content_formats: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> TelegramHttpResponse:
        del timeout_seconds
        self.calls.append(url)
        content = self.responses[url]
        assert len(content) <= max_response_bytes
        return TelegramHttpResponse(
            requested_url=url,
            final_url=url,
            content=content,
            content_format=self.content_formats.get(url, "text/html"),
            received_at=FIXTURE_CAPTURED_AT,
            response_metadata={"access_method": "fixture-http"},
        )


def _registry():
    return load_registry(DEFAULT_REGISTRY_PATH)


def _definition():
    return _registry().get("telegram-cptgrantov-discovery")


def _adapter() -> tuple[TelegramDiscoveryAdapter, FixtureTelegramFetcher]:
    fetcher = FixtureTelegramFetcher(
        responses={
            CHANNEL_URL: _fixture_bytes("public_history_page_1.html"),
            OLDER_PAGE_URL: _fixture_bytes("public_history_page_2.html"),
        }
    )
    return (
        TelegramDiscoveryAdapter(
            fetcher=fetcher,
            clock=lambda: 0.0,
            sleeper=lambda _delay: None,
        ),
        fetcher,
    )


def test_registry_limits_discovery_to_the_public_cptgrantov_channel() -> None:
    definition = _definition()

    assert definition.telegram_channel is not None
    assert definition.telegram_channel.channel_handle == "cptgrantov"
    assert definition.telegram_channel.retention_days == 90
    assert is_url_allowed(CHANNEL_URL, definition)
    assert is_url_allowed(OLDER_PAGE_URL, definition)
    assert not is_url_allowed("https://t.me/s/another-channel", definition)
    assert not is_url_allowed("https://telegram.org/blog", definition)


def test_parser_keeps_only_compact_label_metadata_and_external_urls() -> None:
    parsed = parse_telegram_channel_page(
        _fixture_bytes("public_history_page_1.html"),
        page_url=CHANNEL_URL,
        channel_handle="cptgrantov",
    )

    assert parsed.issues == ()
    assert [message.message_id for message in parsed.messages] == [105, 104]
    assert parsed.messages[0].service_label is not None
    assert len(parsed.messages[0].service_label) <= 280
    assert [(link.normalized_url, link.role) for link in parsed.messages[0].external_urls] == [
        (
            "https://fondpotanin.ru/competitions/quality-reference-open/",
            "possible_source",
        ),
        ("https://zayavka.fondpotanin.ru/ru/", "registration"),
    ]
    assert parsed.next_page_url == OLDER_PAGE_URL


def test_fixture_run_routes_only_registered_sources_and_preserves_manual_cases() -> None:
    adapter, fetcher = _adapter()

    execution = execute_telegram_discovery(
        _definition(),
        _registry(),
        adapter,
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )

    report = execution.report
    assert report.status == "completed"
    assert report.dry_run is True
    assert report.statistics.model_dump() == {
        "discovered": 4,
        "fetched": 2,
        "extracted": 4,
        "valid": 4,
        "warnings": 3,
        "errors": 0,
        "duplicates": 1,
        "requests": 2,
        "response_bytes": sum(
            len(_fixture_bytes(name))
            for name in ("public_history_page_1.html", "public_history_page_2.html")
        ),
        "artifact_discovered": 0,
        "artifact_fetched": 0,
        "artifact_deferred": 0,
    }
    assert fetcher.calls == [CHANNEL_URL, OLDER_PAGE_URL]
    assert report.quality is not None
    assert report.quality.completeness.model_dump() == {
        "numerator": 3,
        "denominator": 4,
        "value": 0.75,
    }
    assert report.quality.validity.value == 1
    assert report.quality.duplicate_rate.value == 0.25

    by_message = {record.message_id: record for record in execution.records}
    source_link = by_message[105].external_urls[0]
    assert source_link.route is TelegramDiscoveryRoute.SOURCE_ADAPTER
    assert source_link.target_source_key == "potanin-competitions"
    assert by_message[105].review_required is True
    assert by_message[104].review_required is True
    assert by_message[102].review_required is True
    assert any(
        issue.code == "missing_reliable_external_url" for issue in by_message[102].issues
    )
    snapshot = execution.snapshot_bytes.decode()
    assert "tgme_widget_message_text" not in snapshot
    assert "<html" not in snapshot


def test_unexpected_public_page_shape_fails_without_silent_records() -> None:
    fetcher = FixtureTelegramFetcher(
        responses={CHANNEL_URL: _fixture_bytes("unexpected_page.html")}
    )
    adapter = TelegramDiscoveryAdapter(
        fetcher=fetcher,
        clock=lambda: 0.0,
        sleeper=lambda _delay: None,
    )

    execution = execute_telegram_discovery(
        _definition(),
        _registry(),
        adapter,
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=FIXTURE_CAPTURED_AT,
    )

    assert execution.report.status == "failed"
    assert execution.records == ()
    assert any(issue.code == "message_markup_missing" for issue in execution.report.issues)


@pytest.mark.postgres
def test_dry_run_keeps_telegram_discovery_out_of_the_database(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        ADAPTER_FACTORIES,
        "telegram-discovery",
        lambda: _adapter()[0],
    )

    report = run_registered_source(
        "telegram-cptgrantov-discovery",
        registry_path=DEFAULT_REGISTRY_PATH,
        engine=migrated_engine,
        dry_run=True,
        project_root=BACKEND_ROOT,
    )

    assert report.status == "completed"
    assert report.source_id is None
    assert report.ingestion_run_id is None
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Source)) == 0
        assert connection.scalar(select(func.count()).select_from(IngestionRun)) == 0
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 0
        assert connection.scalar(select(func.count()).select_from(TelegramDiscoveryMessage)) == 0


@pytest.mark.postgres
def test_normal_run_is_idempotent_and_never_creates_programs(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fixture_factory() -> TelegramDiscoveryAdapter:
        adapter, _fetcher = _adapter()
        return adapter

    monkeypatch.setitem(ADAPTER_FACTORIES, "telegram-discovery", fixture_factory)

    first = run_registered_source(
        "telegram-cptgrantov-discovery",
        registry_path=DEFAULT_REGISTRY_PATH,
        engine=migrated_engine,
        project_root=BACKEND_ROOT,
    )
    repeated = run_registered_source(
        "telegram-cptgrantov-discovery",
        registry_path=DEFAULT_REGISTRY_PATH,
        engine=migrated_engine,
        project_root=BACKEND_ROOT,
    )

    assert first.status == "completed"
    assert first.import_counts == {
        "new": 4,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "routed_to_source": 2,
        "manual_review": 3,
    }
    assert repeated.status == "completed"
    assert repeated.import_counts == {
        "new": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "routed_to_source": 0,
        "manual_review": 0,
    }

    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Source)) == 1
        assert connection.scalar(select(func.count()).select_from(IngestionRun)) == 1
        assert connection.scalar(select(func.count()).select_from(RawCapture)) == 1
        assert connection.scalar(select(func.count()).select_from(TelegramDiscoveryMessage)) == 4
        assert connection.scalar(select(func.count()).select_from(TelegramDiscoveryUrl)) == 3
        assert connection.scalar(select(func.count()).select_from(TelegramDiscoveryMessageUrl)) == 4
        assert connection.scalar(select(func.count()).select_from(Program)) == 0
        assert connection.scalar(select(func.count()).select_from(StagedRecord)) == 0
        assert connection.scalar(
            select(TelegramDiscoveryCursor.last_message_id)
        ) == 105
        routes = {
            row.normalized_url: row.route
            for row in connection.execute(
                select(
                    TelegramDiscoveryUrl.normalized_url,
                    TelegramDiscoveryUrl.route,
                )
            )
        }
        assert (
            routes["https://fondpotanin.ru/competitions/quality-reference-open/"]
            is TelegramDiscoveryRoute.SOURCE_ADAPTER
        )
        message_without_link = connection.execute(
            select(
                TelegramDiscoveryMessage.review_required,
                TelegramDiscoveryMessage.discovery_issues,
            ).where(TelegramDiscoveryMessage.message_id == 102)
        ).one()
        assert message_without_link.review_required is True
        assert message_without_link.discovery_issues == [
            {
                "stage": "validate",
                "severity": "warning",
                "code": "missing_reliable_external_url",
            }
        ]
        raw_metadata = connection.scalar(select(RawCapture.response_metadata))
        assert raw_metadata == {
            "capture_policy": "minimal_metadata_and_external_urls_only",
            "channel_handle": "cptgrantov",
            "page_count": 2,
            "retention_days": 90,
            "expires_at": (
                first.quality.freshness.captured_at + timedelta(days=90)
            ).isoformat(),
        }
        assert "message_text" not in TelegramDiscoveryMessage.__table__.columns.keys()
        assert "media" not in TelegramDiscoveryMessage.__table__.columns.keys()

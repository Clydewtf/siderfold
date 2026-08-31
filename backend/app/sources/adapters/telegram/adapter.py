from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from time import monotonic, sleep
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.sources.adapters.telegram.http import (
    TelegramHttpResponse,
    TelegramResponseFetcher,
    UrllibTelegramResponseFetcher,
)
from app.sources.adapters.telegram.parsing import (
    ParsedTelegramLink,
    ParsedTelegramMessage,
    TelegramParserIssue,
    parse_telegram_channel_page,
)
from app.sources.contract import (
    AdapterContext,
    AdapterIssue,
    AdapterReport,
    AdapterRunSummary,
    AdapterStage,
    DiscoveredResource,
    DiscoveryResult,
    FetchResult,
    adapter_report,
)
from app.sources.registry import TelegramChannelConfig, UrlAllowlistError


TELEGRAM_DISCOVERY_ADAPTER_NAME = "telegram-discovery"
TELEGRAM_DISCOVERY_ADAPTER_VERSION = "1.0.0"


@dataclass(frozen=True)
class TelegramFetchedPages:
    pages: tuple[FetchResult, ...]
    request_count: int
    response_bytes: int
    issues: tuple[AdapterIssue, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class TelegramExtractedMessage:
    message_id: int
    message_url: str
    published_at: datetime
    service_label: str | None
    external_urls: tuple[ParsedTelegramLink, ...]
    issues: tuple[AdapterIssue, ...] = ()


@dataclass(frozen=True)
class TelegramExtractResult:
    records: tuple[TelegramExtractedMessage, ...]
    discovered_message_count: int
    skipped_by_cursor: int
    issues: tuple[AdapterIssue, ...]


@dataclass(frozen=True)
class TelegramValidationResult:
    records: tuple[TelegramExtractedMessage, ...]
    issues: tuple[AdapterIssue, ...]
    duplicate_url_count: int


def _parser_issue(issue: TelegramParserIssue, *, resource_key: str) -> AdapterIssue:
    return AdapterIssue(
        stage=AdapterStage.EXTRACT,
        severity=issue.severity,  # type: ignore[arg-type]
        code=issue.code,
        message=issue.message,
        resource_key=resource_key,
    )


class TelegramDiscoveryAdapter:
    name = TELEGRAM_DISCOVERY_ADAPTER_NAME
    version = TELEGRAM_DISCOVERY_ADAPTER_VERSION

    def __init__(
        self,
        *,
        fetcher: TelegramResponseFetcher | None = None,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._fetcher = fetcher or UrllibTelegramResponseFetcher()
        self._clock = clock
        self._sleeper = sleeper

    def _channel(self, context: AdapterContext) -> TelegramChannelConfig:
        channel = context.source.telegram_channel
        if channel is None:
            raise ValueError("telegram-discovery requires telegram_channel configuration")
        return channel

    def _require_page_url(self, url: str, context: AdapterContext) -> str:
        channel = self._channel(context)
        normalized = context.require_allowed_url(url)
        parsed = urlsplit(normalized)
        expected_path = f"/s/{channel.channel_handle}"
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname is None
            or parsed.hostname.lower() != "t.me"
            or parsed.path.rstrip("/") != expected_path
        ):
            raise UrlAllowlistError("Telegram request is outside the configured public channel")
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if not query:
            return normalized
        if (
            len(query) != 1
            or query[0][0] != "before"
            or not query[0][1].isdigit()
            or int(query[0][1]) <= 0
        ):
            raise UrlAllowlistError("Telegram request has an unsupported query parameter")
        return normalized

    @staticmethod
    def _resource(url: str, channel_handle: str) -> DiscoveredResource:
        digest = sha256(url.encode("utf-8")).hexdigest()[:20]
        return DiscoveredResource(
            external_key=f"telegram:{channel_handle}:page:{digest}",
            url=url,
            metadata={"channel_handle": channel_handle, "resource_role": "discovery"},
        )

    def discover(self, context: AdapterContext) -> DiscoveryResult:
        channel = self._channel(context)
        url = self._require_page_url(channel.public_read_url, context)
        return DiscoveryResult(
            resources=(self._resource(url, channel.channel_handle),),
            coverage_scope=(
                "public message pages returned by the configured Telegram channel"
            ),
            quality_limitations=(
                "Only publicly available posts returned without authentication are in scope.",
                "Message text and media are not retained.",
            ),
        )

    def _fetch_page(
        self,
        resource: DiscoveredResource,
        context: AdapterContext,
    ) -> tuple[FetchResult, TelegramHttpResponse]:
        response = self._fetcher.get(
            resource.url,
            timeout_seconds=context.limits.timeout_seconds,
            max_response_bytes=context.limits.max_response_bytes,
        )
        final_url = self._require_page_url(response.final_url, context)
        return (
            FetchResult(
                resource=resource,
                final_url=final_url,
                content=response.content,
                content_format=response.content_format,
                received_at=response.received_at,
                external_content_uri=f"urn:sha256:{sha256(response.content).hexdigest()}",
                response_metadata=response.response_metadata,
            ),
            response,
        )

    def fetch(
        self,
        resources: Sequence[DiscoveredResource],
        context: AdapterContext,
        *,
        cursor_message_id: int | None,
    ) -> TelegramFetchedPages:
        channel = self._channel(context)
        if len(resources) != 1:
            raise ValueError("telegram-discovery requires exactly one channel resource")

        pages: list[FetchResult] = []
        issues: list[AdapterIssue] = []
        limitations: list[str] = []
        pending_url = resources[0].url
        seen_page_urls: set[str] = set()
        response_bytes = 0
        last_request_at: float | None = None

        while pending_url is not None:
            if len(pages) >= context.limits.max_requests:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.FETCH,
                        severity="warning",
                        code="history_request_limit_reached",
                        message=(
                            "Historical discovery stopped at the configured request limit."
                        ),
                    )
                )
                limitations.append("The configured request limit truncated public history.")
                break
            page_url = self._require_page_url(pending_url, context)
            if page_url in seen_page_urls:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.FETCH,
                        severity="error",
                        code="pagination_loop",
                        message="Telegram pagination repeated a previously fetched page.",
                    )
                )
                break
            if last_request_at is not None:
                elapsed = self._clock() - last_request_at
                delay = channel.min_request_interval_seconds - elapsed
                if delay > 0:
                    self._sleeper(delay)
            resource = self._resource(page_url, channel.channel_handle)
            fetched, _response = self._fetch_page(resource, context)
            response_bytes += len(fetched.content)
            if response_bytes > context.limits.max_total_bytes:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.FETCH,
                        severity="error",
                        code="response_limit_exceeded",
                        message="Telegram responses exceeded the configured total byte limit.",
                    )
                )
                break
            pages.append(fetched)
            seen_page_urls.add(page_url)
            last_request_at = self._clock()

            parsed = parse_telegram_channel_page(
                fetched.content,
                page_url=fetched.final_url,
                channel_handle=channel.channel_handle,
            )
            if any(issue.severity == "error" for issue in parsed.issues):
                break
            if (
                cursor_message_id is not None
                and any(message.message_id <= cursor_message_id for message in parsed.messages)
            ):
                limitations.append("Incremental discovery stopped at the persisted message cursor.")
                break
            pending_url = parsed.next_page_url

        return TelegramFetchedPages(
            pages=tuple(pages),
            request_count=len(pages),
            response_bytes=response_bytes,
            issues=tuple(issues),
            limitations=tuple(dict.fromkeys(limitations)),
        )

    def extract(
        self,
        fetched: TelegramFetchedPages,
        context: AdapterContext,
        *,
        cursor_message_id: int | None,
    ) -> TelegramExtractResult:
        channel = self._channel(context)
        records: list[TelegramExtractedMessage] = []
        issues: list[AdapterIssue] = []
        seen_message_ids: set[int] = set()
        discovered_message_count = 0
        skipped_by_cursor = 0

        for page in fetched.pages:
            if "html" not in page.content_format.casefold():
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.EXTRACT,
                        severity="error",
                        code="unexpected_content_type",
                        message="Telegram discovery requires an HTML public page response.",
                        resource_key=page.resource.external_key,
                    )
                )
                continue
            parsed = parse_telegram_channel_page(
                page.content,
                page_url=page.final_url,
                channel_handle=channel.channel_handle,
            )
            issues.extend(
                _parser_issue(issue, resource_key=page.resource.external_key)
                for issue in parsed.issues
            )
            for message in parsed.messages:
                discovered_message_count += 1
                if message.message_id in seen_message_ids:
                    issues.append(
                        AdapterIssue(
                            stage=AdapterStage.EXTRACT,
                            severity="warning",
                            code="duplicate_message_in_run",
                            message="The same Telegram message appeared on more than one page.",
                            resource_key=page.resource.external_key,
                        )
                    )
                    continue
                seen_message_ids.add(message.message_id)
                if (
                    cursor_message_id is not None
                    and message.message_id <= cursor_message_id
                ):
                    skipped_by_cursor += 1
                    continue
                records.append(
                    TelegramExtractedMessage(
                        message_id=message.message_id,
                        message_url=message.message_url,
                        published_at=message.published_at,
                        service_label=message.service_label,
                        external_urls=message.external_urls,
                    )
                )

        return TelegramExtractResult(
            records=tuple(records),
            discovered_message_count=discovered_message_count,
            skipped_by_cursor=skipped_by_cursor,
            issues=tuple(issues),
        )

    def validate(
        self,
        records: Sequence[TelegramExtractedMessage],
        context: AdapterContext,
    ) -> TelegramValidationResult:
        channel = self._channel(context)
        issues: list[AdapterIssue] = []
        valid_records: list[TelegramExtractedMessage] = []
        all_urls: set[str] = set()
        duplicate_url_count = 0

        if len(records) > min(channel.max_messages_per_run, context.limits.max_records):
            issues.append(
                AdapterIssue(
                    stage=AdapterStage.VALIDATE,
                    severity="error",
                    code="message_limit_exceeded",
                    message="Telegram discovery exceeded the configured message limit.",
                )
            )

        for record in records:
            if not record.external_urls:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.VALIDATE,
                        severity="warning",
                        code="missing_reliable_external_url",
                        message=(
                            "The Telegram message has no external HTTP(S) URL and needs manual review."
                        ),
                        resource_key=str(record.message_id),
                    )
                )
            for link in record.external_urls:
                if link.normalized_url in all_urls:
                    duplicate_url_count += 1
                all_urls.add(link.normalized_url)
            valid_records.append(record)

        return TelegramValidationResult(
            records=tuple(valid_records),
            issues=tuple(issues),
            duplicate_url_count=duplicate_url_count,
        )

    def report(self, summary: AdapterRunSummary) -> AdapterReport:
        return adapter_report(self, summary)


def telegram_discovery_adapter() -> TelegramDiscoveryAdapter:
    return TelegramDiscoveryAdapter()

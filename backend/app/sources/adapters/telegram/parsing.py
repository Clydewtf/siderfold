from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urljoin, urlsplit

from lxml import etree, html

from app.sources.registry import normalize_url


_TELEGRAM_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}
_MESSAGE_CLASS = (
    "contains(concat(' ', normalize-space(@class), ' '), "
    "' tgme_widget_message ')"
)
_TEXT_CLASS = (
    "contains(concat(' ', normalize-space(@class), ' '), "
    "' tgme_widget_message_text ')"
)


@dataclass(frozen=True)
class TelegramParserIssue:
    severity: str
    code: str
    message: str
    message_id: int | None = None


@dataclass(frozen=True)
class ParsedTelegramLink:
    normalized_url: str
    role: str


@dataclass(frozen=True)
class ParsedTelegramMessage:
    message_id: int
    message_url: str
    published_at: datetime
    service_label: str | None
    external_urls: tuple[ParsedTelegramLink, ...]


@dataclass(frozen=True)
class ParsedTelegramPage:
    messages: tuple[ParsedTelegramMessage, ...]
    next_page_url: str | None
    issues: tuple[TelegramParserIssue, ...]


def _collapse_text(value: str) -> str:
    return " ".join(value.split())


def _service_label(node: etree._Element) -> str | None:
    containers = node.xpath(f".//*[({_TEXT_CLASS})]")
    if not containers:
        return None
    label = _collapse_text(containers[0].text_content())
    if not label:
        return None
    return label[:280].rstrip() or None


def _is_internal_telegram_url(url: str) -> bool:
    hostname = urlsplit(url).hostname
    return hostname is not None and hostname.lower() in _TELEGRAM_HOSTS


def _classify_link(anchor: etree._Element, normalized_url: str) -> str:
    evidence = _collapse_text(anchor.text_content()).casefold()
    evidence = f"{evidence} {normalized_url.casefold()}"
    if any(
        marker in evidence
        for marker in ("регистрац", "заявк", "подать", "apply", "register")
    ):
        return "registration"
    if any(
        marker in evidence
        for marker in ("конкурс", "грант", "услови", "подроб", "source", "programme")
    ):
        return "possible_source"
    return "other"


def _external_urls(
    node: etree._Element,
    *,
    page_url: str,
) -> tuple[ParsedTelegramLink, ...]:
    links: list[ParsedTelegramLink] = []
    seen: set[str] = set()
    for anchor in node.xpath(".//a[@href]"):
        href = anchor.get("href")
        if not href:
            continue
        try:
            normalized = normalize_url(urljoin(page_url, href))
        except ValueError:
            continue
        if _is_internal_telegram_url(normalized) or normalized in seen:
            continue
        seen.add(normalized)
        links.append(
            ParsedTelegramLink(
                normalized_url=normalized,
                role=_classify_link(anchor, normalized),
            )
        )
    return tuple(links)


def _parse_published_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _next_page_url(
    document: etree._Element,
    *,
    page_url: str,
    channel_handle: str,
) -> str | None:
    expected_path = f"/s/{channel_handle}"
    for anchor in document.xpath("//a[@href]"):
        href = anchor.get("href")
        if not href:
            continue
        try:
            candidate = normalize_url(urljoin(page_url, href))
        except ValueError:
            continue
        parsed = urlsplit(candidate)
        if (
            parsed.hostname is None
            or parsed.hostname.lower() != "t.me"
            or parsed.path.rstrip("/") != expected_path
        ):
            continue
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if len(query) == 1 and query[0][0] == "before" and query[0][1].isdigit():
            return candidate
    return None


def parse_telegram_channel_page(
    content: bytes,
    *,
    page_url: str,
    channel_handle: str,
) -> ParsedTelegramPage:
    """Extract only compact metadata and outbound HTTP(S) links from one page."""

    try:
        document = html.fromstring(content.decode("utf-8"))
    except (etree.ParserError, ValueError, UnicodeDecodeError):
        return ParsedTelegramPage(
            messages=(),
            next_page_url=None,
            issues=(
                TelegramParserIssue(
                    severity="error",
                    code="unexpected_page_format",
                    message="The public Telegram page could not be parsed as HTML.",
                ),
            ),
        )

    nodes = document.xpath(f"//*[@data-post and ({_MESSAGE_CLASS})]")
    if not nodes:
        return ParsedTelegramPage(
            messages=(),
            next_page_url=_next_page_url(
                document,
                page_url=page_url,
                channel_handle=channel_handle,
            ),
            issues=(
                TelegramParserIssue(
                    severity="error",
                    code="message_markup_missing",
                    message="Expected public Telegram message markup was not found.",
                ),
            ),
        )

    messages: list[ParsedTelegramMessage] = []
    issues: list[TelegramParserIssue] = []
    expected_post_prefix = f"{channel_handle}/"
    for node in nodes:
        post_key = (node.get("data-post") or "").strip()
        if not post_key.casefold().startswith(expected_post_prefix.casefold()):
            issues.append(
                TelegramParserIssue(
                    severity="warning",
                    code="foreign_message_ignored",
                    message="A message outside the configured channel was ignored.",
                )
            )
            continue
        raw_message_id = post_key[len(expected_post_prefix) :]
        if not raw_message_id.isdigit() or int(raw_message_id) <= 0:
            issues.append(
                TelegramParserIssue(
                    severity="error",
                    code="invalid_message_id",
                    message="A public Telegram message did not provide a valid numeric ID.",
                )
            )
            continue
        message_id = int(raw_message_id)
        datetime_values = node.xpath(".//time[@datetime]/@datetime")
        published_at = _parse_published_at(datetime_values[0]) if datetime_values else None
        if published_at is None:
            issues.append(
                TelegramParserIssue(
                    severity="error",
                    code="missing_message_timestamp",
                    message="A public Telegram message did not provide a valid timestamp.",
                    message_id=message_id,
                )
            )
            continue
        messages.append(
            ParsedTelegramMessage(
                message_id=message_id,
                message_url=f"https://t.me/{channel_handle}/{message_id}",
                published_at=published_at,
                service_label=_service_label(node),
                external_urls=_external_urls(node, page_url=page_url),
            )
        )

    return ParsedTelegramPage(
        messages=tuple(messages),
        next_page_url=_next_page_url(
            document,
            page_url=page_url,
            channel_handle=channel_handle,
        ),
        issues=tuple(issues),
    )

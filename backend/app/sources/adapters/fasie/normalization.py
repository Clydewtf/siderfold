from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import re
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from app.domain.models import FundingValueKind
from app.import_bridge.contract import FundingInput
from app.sources.adapters.potanin.normalization import (
    RUSSIAN_MONTHS,
    normalize_whitespace as _normalize_whitespace,
    parse_rub_amounts,
)
from app.sources.registry import normalize_url


FASIE_HOST = "fasie.ru"
FASIE_HOST_ALIASES = frozenset({"fasie.ru", "www.fasie.ru"})
FASIE_TZ = ZoneInfo("Europe/Moscow")
FASIE_SOURCE_PUBLISHER = "Фонд содействия инновациям"

_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"}
_MONTHS_PATTERN = "|".join(RUSSIAN_MONTHS)
_DATE_TOKEN_RE = re.compile(
    rf"(?:\d{{1,2}}[./]\d{{1,2}}[./]\d{{4}}|\d{{1,2}}\s+(?:{_MONTHS_PATTERN})"
    rf"(?:\s+\d{{4}})?(?:\s*г(?:ода?|\.)?)?)",
    re.IGNORECASE,
)
_APPLICATION_CONTEXT_RE = re.compile(
    r"(?:при[её]м\s+заяв\w*|подач\w*\s+заяв\w*|"
    # FASIE commonly qualifies the subject before the predicate, for example
    # "Заявки на конкурс «…» (очередь 3) будут приниматься до …".  Keep the
    # bridge sentence-local and bounded so an unrelated later sentence cannot
    # turn into a submission deadline.
    r"заявк\w*(?:\s+[^.!?]{0,160}?)?\s+(?:будут\s+)?(?:можно|приним\w*|пода\w*)|"
    r"отбор\w*\s+проект\w*)",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    rf"\bс\s+(?P<start>{_DATE_TOKEN_RE.pattern})\s*(?:по|до|[-–—])\s*"
    rf"(?P<end>{_DATE_TOKEN_RE.pattern})",
    re.IGNORECASE,
)
_DEADLINE_RE = re.compile(
    rf"\bдо\s+(?P<value>(?:\d{{1,2}}:\d{{2}}\s*(?:\(\s*(?:мск|московск\w*)\s*\))?\s*)?"
    rf"{_DATE_TOKEN_RE.pattern})",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)\b")


def normalize_whitespace(value: str) -> str:
    return _normalize_whitespace(value)


def normalize_fasie_url(value: str, *, allow_query: bool = True) -> str:
    """Canonicalize a same-origin FASIE URL and its www alias."""

    normalized = normalize_url(value)
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or parsed.hostname not in FASIE_HOST_ALIASES:
        raise ValueError("FASIE URLs must use HTTPS on fasie.ru or www.fasie.ru")
    decoded_path = unquote(parsed.path or "/")
    if (
        "\\" in decoded_path
        or re.search(r"%(?:2e|2f|5c)", parsed.path, re.IGNORECASE)
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        raise ValueError("FASIE URL must not contain encoded or literal path traversal")
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    query_items = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_QUERY_KEYS
        and not key.casefold().startswith("utm_")
    ]
    if not allow_query and query_items:
        raise ValueError("this FASIE URL kind must not contain a query")
    return urlunsplit(
        (
            "https",
            FASIE_HOST,
            path,
            urlencode(query_items, doseq=True),
            "",
        )
    )


def normalize_reference_url(value: str, *, base_url: str | None = None) -> str | None:
    """Normalize a non-fetched reference URL without expanding its scope."""

    try:
        candidate = urljoin(base_url or f"https://{FASIE_HOST}/", value.strip())
        normalized = normalize_url(candidate)
    except (AttributeError, ValueError):
        return None
    parsed = urlsplit(normalized)
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_QUERY_KEYS
        and not key.casefold().startswith("utm_")
    ]
    host = parsed.hostname or ""
    if host in FASIE_HOST_ALIASES:
        return urlunsplit(("https", FASIE_HOST, parsed.path or "/", urlencode(query, doseq=True), ""))
    return urlunsplit((parsed.scheme.lower(), host.lower(), parsed.path or "/", urlencode(query, doseq=True), ""))


def press_detail_url(value: str, *, base_url: str | None = None) -> str:
    candidate = normalize_fasie_url(urljoin(base_url or f"https://{FASIE_HOST}/", value), allow_query=False)
    path = urlsplit(candidate).path
    if not re.fullmatch(r"/press/fund/[^/]+/", path):
        raise ValueError("FASIE detail URL must be under /press/fund/<slug>/")
    return candidate


def feed_page_url(value: str) -> str:
    candidate = normalize_fasie_url(value)
    parsed = urlsplit(candidate)
    if parsed.path.rstrip("/") == "/press/fund" and not parsed.query:
        return urlunsplit(("https", FASIE_HOST, "/press/fund/", "", ""))
    if parsed.path.rstrip("/") != "/press/news":
        raise ValueError("FASIE feed page must be /press/fund/ or /press/news/")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if any(key.casefold() not in {"ajax", "pagen_1"} for key, _value in pairs):
        raise ValueError("FASIE AJAX pager contains unsupported query parameters")
    ajax_values = [value for key, value in pairs if key.casefold() == "ajax"]
    page_values = [value for key, value in pairs if key.casefold() == "pagen_1"]
    if not ajax_values or any(value.upper() != "Y" for value in ajax_values) or len(page_values) != 1:
        raise ValueError("FASIE AJAX pager must contain ajax=Y and one PAGEN_1 value")
    if not page_values[0].isdigit() or int(page_values[0]) < 2:
        raise ValueError("FASIE AJAX page number must be an integer >= 2")
    return urlunsplit(
        ("https", FASIE_HOST, "/press/news/", "ajax=Y&PAGEN_1=" + str(int(page_values[0])), "")
    )


def is_upload_url(value: str) -> bool:
    try:
        parsed = urlsplit(normalize_fasie_url(value))
    except ValueError:
        return False
    return parsed.path.startswith("/upload/")


def normalize_upload_url(value: str, *, base_url: str | None = None) -> str:
    candidate = normalize_fasie_url(urljoin(base_url or f"https://{FASIE_HOST}/", value))
    if not urlsplit(candidate).path.startswith("/upload/"):
        raise ValueError("FASIE attachment must be under /upload/")
    return candidate


def normalize_title(value: str) -> str:
    # Do not use ``str.strip`` with quote characters here: it treats the
    # closing quote of a title as an independent removable character.  That
    # turned e.g. «Цифровые решения» into an unbalanced title.
    title = normalize_whitespace(value)
    title = re.sub(
        r"^(?:запуск|продление|продолжается|открыт\w*|подведен\w*)\s+"
        r"(?:конкурс\w*|преми\w*|рейтинг\w*|акселератор\w*|программ\w*)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"^(?:запуск|продление|продолжается|открыт\w*|подведен\w*)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^при[её]м\s+заявок\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^на\s+", "", title, flags=re.IGNORECASE)
    return title.strip(" -–—:;,. ")


def normalize_identity_name(value: str) -> str:
    normalized = normalize_whitespace(value).casefold().replace("ё", "е")
    normalized = re.sub(r"[^\w\d]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def identity_key(name: str, queue: str | None, stage: str | None, year: int) -> str:
    queue_value = queue or "-"
    stage_value = stage or "-"
    return f"{normalize_identity_name(name)}|queue={queue_value}|stage={stage_value}|year={year}"


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def parse_publication_datetime(value: str, *, fallback_year: int | None = None) -> datetime | None:
    text = normalize_whitespace(value)
    match = re.search(
        r"(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{4})"
        r"(?:\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?)?",
        text,
    )
    if match is None:
        match = re.search(
            rf"(?P<day>\d{{1,2}})\s+(?P<month_name>{_MONTHS_PATTERN})"
            rf"(?:\s+(?P<year>\d{{4}}))?(?:\s+(?P<hour>\d{{1,2}}):(?P<minute>\d{{2}}))?",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return None
        month = RUSSIAN_MONTHS[match.group("month_name").lower()]
    else:
        month = int(match.group("month"))
    year = int(match.group("year") or fallback_year) if (match.group("year") or fallback_year) else None
    if year is None:
        return None
    try:
        return datetime(
            year,
            month,
            int(match.group("day")),
            int(match.group("hour") or 0),
            int(match.group("minute") or 0),
            int(match.groupdict().get("second") or 0),
            tzinfo=FASIE_TZ,
        )
    except ValueError:
        return None


def parse_date_token(value: str, *, fallback_year: int | None = None) -> date | None:
    parsed = parse_publication_datetime(value, fallback_year=fallback_year)
    return parsed.date() if parsed is not None else None


@dataclass(frozen=True)
class ApplicationWindow:
    start_on: date | None
    end_on: date | None
    start_at: datetime | None
    end_at: datetime | None
    evidence: str


def _at_day_end(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59, 999999), tzinfo=FASIE_TZ)


def _parse_date_with_nearby_time(
    value_text: str,
    token: str,
    *,
    fallback_year: int | None,
) -> tuple[date | None, datetime | None]:
    value = parse_date_token(token, fallback_year=fallback_year)
    if value is None:
        return None, None
    time_match = list(_TIME_RE.finditer(value_text))
    if time_match:
        match = time_match[-1]
        return value, datetime(
            value.year,
            value.month,
            value.day,
            int(match.group("hour")),
            int(match.group("minute")),
            tzinfo=FASIE_TZ,
        )
    return value, _at_day_end(value)


def extract_application_windows(text: str, *, fallback_year: int | None = None) -> tuple[ApplicationWindow, ...]:
    """Extract only dates tied to application/submission language."""

    normalized = normalize_whitespace(text)
    windows: list[ApplicationWindow] = []
    for marker in _APPLICATION_CONTEXT_RE.finditer(normalized):
        window = normalized[marker.start() : min(len(normalized), marker.end() + 420)]
        if re.search(r"(?:заявк\w*\s+принимал\w*|принимал\w*\s+заявк\w*)", window[:100], re.IGNORECASE):
            continue
        range_match = _RANGE_RE.search(window)
        if range_match is not None:
            start_token = range_match.group("start")
            end_token = range_match.group("end")
            start_on = parse_date_token(start_token, fallback_year=fallback_year)
            end_on = parse_date_token(end_token, fallback_year=fallback_year)
            if start_on is not None and end_on is not None:
                windows.append(
                    ApplicationWindow(
                        start_on=start_on,
                        end_on=end_on,
                        start_at=_at_day_end(start_on).replace(hour=0, minute=0, second=0, microsecond=0),
                        end_at=_at_day_end(end_on),
                        evidence=window[:1_000],
                    )
                )
                continue
        deadline_match = _DEADLINE_RE.search(window)
        if deadline_match is None:
            continue
        value_text = deadline_match.group("value")
        date_match = re.search(_DATE_TOKEN_RE.pattern, value_text, re.IGNORECASE)
        if date_match is None:
            continue
        token = date_match.group(0)
        end_on, end_at = _parse_date_with_nearby_time(
            value_text,
            token,
            fallback_year=fallback_year,
        )
        if end_on is not None:
            windows.append(
                ApplicationWindow(
                    start_on=None,
                    end_on=end_on,
                    start_at=None,
                    end_at=end_at,
                    evidence=window[:1_000],
                )
            )
    unique: list[ApplicationWindow] = []
    seen: set[tuple[date | None, date | None, datetime | None, datetime | None]] = set()
    for item in windows:
        key = (item.start_on, item.end_on, item.start_at, item.end_at)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return tuple(unique)


@dataclass(frozen=True)
class FundingExtraction:
    funding: FundingInput | None
    evidence: str | None = None
    warning: str | None = None


def extract_grant_funding(text: str) -> FundingExtraction:
    """Extract applicant-level grant support, excluding aggregate result totals."""

    normalized = normalize_whitespace(text)
    sentences = [part for part in re.split(r"(?<=[.!?])\s+|\n+", normalized) if part]
    candidates: list[tuple[FundingInput, str]] = []
    for sentence in sentences:
        lower = sentence.casefold()
        if not re.search(r"грант\w*|финансирован\w*|размер\s+поддержк|поддержк\w*", lower):
            continue
        if re.search(r"заявк\w*\s+на\s+сумм|всего\s+выделен|общ(?:ая|ий)\s+сумм|рекомендован\w*\s+к\s+финансирован", lower):
            continue
        amounts = parse_rub_amounts(sentence)
        if not amounts:
            continue
        if re.search(r"\bот\b.+?\bдо\b", lower) and len(amounts) >= 2:
            funding = FundingInput(
                value_kind=FundingValueKind.RANGE,
                currency_code="RUB",
                min_amount=min(amounts),
                max_amount=max(amounts),
            )
        elif re.search(r"\bдо\b|максимальн\w*|не\s+более", lower):
            funding = FundingInput(
                value_kind=FundingValueKind.MAXIMUM,
                currency_code="RUB",
                max_amount=max(amounts),
            )
        elif re.search(r"минимальн\w*|не\s+менее", lower):
            funding = FundingInput(
                value_kind=FundingValueKind.MINIMUM,
                currency_code="RUB",
                min_amount=min(amounts),
            )
        else:
            funding = FundingInput(
                value_kind=FundingValueKind.EXACT,
                currency_code="RUB",
                exact_amount=amounts[0],
            )
        candidates.append((funding, sentence[:1_000]))
    if not candidates:
        return FundingExtraction(None)
    signatures = {
        (
            item.value_kind,
            item.currency_code,
            item.exact_amount,
            item.min_amount,
            item.max_amount,
        )
        for item, _evidence in candidates
    }
    if len(signatures) > 1:
        return FundingExtraction(None, warning="funding_evidence_conflict")
    return FundingExtraction(candidates[-1][0], evidence=candidates[-1][1])

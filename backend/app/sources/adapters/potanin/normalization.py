from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from app.domain.models import FundingValueKind
from app.import_bridge.contract import FundingInput
from app.sources.registry import normalize_url


POTANIN_HOST = "fondpotanin.ru"
COMPETITIONS_PATH = "/competitions"

RUSSIAN_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_MONTHS_PATTERN = "|".join(RUSSIAN_MONTHS)
_WORD_DATE_RE = re.compile(
    rf"(?P<day>\d{{1,2}})\s+(?P<month>{_MONTHS_PATTERN})(?:\s+(?P<year>\d{{4}}))?(?:\s*г(?:ода?|\.)?)?",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(
    r"(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{4})"
)
_DATE_TOKEN_PATTERN = (
    r"(?:\d{1,2}[./]\d{1,2}[./]\d{4}|"
    r"\d{1,2}\s+(?:"
    + _MONTHS_PATTERN
    + r")(?:\s+\d{4})?(?:\s*г(?:ода?|\.)?)?)"
)
_PERIOD_RE = re.compile(
    rf"(?:\bс\s+)?(?P<start>{_DATE_TOKEN_PATTERN})\s*"
    rf"(?:по|до|[-–—])\s*(?P<end>{_DATE_TOKEN_PATTERN})",
    re.IGNORECASE,
)
_SHARED_MONTH_PERIOD_RE = re.compile(
    rf"\bс\s+(?P<start_day>\d{{1,2}})\s*(?:по|до)\s*"
    rf"(?P<end_day>\d{{1,2}})\s+(?P<month>{_MONTHS_PATTERN})"
    rf"(?:\s+(?P<year>\d{{4}})(?:\s*г(?:ода?|\.)?)?)?",
    re.IGNORECASE,
)
_DATE_TOKEN_RE = re.compile(_DATE_TOKEN_PATTERN, re.IGNORECASE)
_SCHEDULE_EVENT_LABEL_RE = re.compile(
    r"(?P<cycle>\b(?:[IVXLCDM]+|\d+)\s+цикл\b\s*)?"
    r"(?P<label>"
    r"(?:начал\w*|открыти\w*)\s+(?:при[её]м\w*|подач\w*)\s+заяв\w*"
    r"|(?:окончани\w*|завершени\w*)\s+(?:при[её]м\w*|подач\w*)\s+заяв\w*"
    r"|при[её]м\w*\s+заяв\w*(?:\s+на\s+конкурс\w*)?"
    r"|подач\w*\s+заяв\w*(?:\s+на\s+конкурс\w*)?"
    r"|экспертиз\w*(?:\s+заяв\w*)?"
    r"|(?:оценк\w*|рассмотрени\w*)(?:\s+заяв\w*)?"
    r"|объявлен\w*(?:\s+(?:результат\w*|состав\w+\s+победител\w*))?"
    r"|итог\w*(?:\s+конкурс\w*)?"
    r"|вводн\w*\s+семинар\w*(?:\s+для\s+победител\w*)?"
    r"|заключен\w*\s+договор\w*(?:\s+с\s+победител\w*)?"
    r"|начал\w*\s+(?:проект\w*|программ\w*|реализац\w*|выплат\w*)"
    r"|голосован\w*(?:\s+[«\"].+?[»\"])?"
    r"|семинар\w*(?:\s+для\s+победител\w*)?"
    r"|выбор\w*\s+лучших\s+реализован\w*\s+проект\w*"
    r"|взнос\w*\s+в\s+целев\w*\s+капитал\w*"
    r")",
    re.IGNORECASE,
)
_CYCLE_PREFIX_RE = re.compile(r"^(?:[IVXLCDM]+|\d+)\s+цикл\b", re.IGNORECASE)
_MONEY_NUMBER_PATTERN = (
    r"\d{1,3}(?:[\s\u00a0,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
)
_MONEY_UNIT_PATTERN = (
    r"тыс\.?|тысяч(?:а|и)?|млн\.?|миллион(?:а|ов)?|млрд\.?|"
    r"миллиард(?:а|ов)?|руб(?:ль|ля|лей)?\.?|₽"
)
_MONEY_RE = re.compile(
    rf"(?<![\w.,])(?P<number>{_MONEY_NUMBER_PATTERN})\s*"
    rf"(?P<unit>{_MONEY_UNIT_PATTERN})(?!\w)",
    re.IGNORECASE,
)
_SHARED_CURRENCY_RANGE_RE = re.compile(
    rf"\bот\s+(?P<minimum>{_MONEY_NUMBER_PATTERN})\s+до\s+"
    rf"(?P<maximum>{_MONEY_NUMBER_PATTERN})\s*(?P<unit>{_MONEY_UNIT_PATTERN})(?!\w)",
    re.IGNORECASE,
)


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def normalize_heading(value: str) -> str:
    return re.sub(r"[^\w\s]", "", normalize_whitespace(value).lower()).strip()


def normalize_competition_url(value: str) -> str:
    """Return a canonical Potanin competition-card URL without tracking params."""

    normalized = normalize_url(value)
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or parsed.hostname != POTANIN_HOST:
        raise ValueError("competition URL must use the official Fond Potanin origin")

    raw_path = parsed.path
    decoded_path = unquote(raw_path)
    if (
        "\\" in decoded_path
        or re.search(r"%(?:2e|2f|5c)", raw_path, re.IGNORECASE)
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        raise ValueError("competition URL must not contain encoded path traversal")

    path = re.sub(r"/{2,}", "/", raw_path).rstrip("/")
    if not path.startswith(f"{COMPETITIONS_PATH}/"):
        raise ValueError("competition URL must be under /competitions/")
    if path == COMPETITIONS_PATH:
        raise ValueError("the competitions catalog is not a competition card")
    return urlunsplit(("https", POTANIN_HOST, f"{path}/", "", ""))


def normalize_outbound_url(value: str) -> str | None:
    """Normalize one safe outbound link without making a request to it."""

    try:
        normalized = normalize_url(value)
    except ValueError:
        return None
    parsed = urlsplit(normalized)
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in {"fbclid", "gclid", "yclid"}
            and not key.lower().startswith("utm_")
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def _parse_word_date(value: str, *, fallback_year: int | None = None) -> date | None:
    match = _WORD_DATE_RE.fullmatch(normalize_whitespace(value))
    if match is None:
        return None
    year = match.group("year")
    if year is None and fallback_year is None:
        return None
    try:
        return date(
            int(year or fallback_year),
            RUSSIAN_MONTHS[match.group("month").lower()],
            int(match.group("day")),
        )
    except ValueError:
        return None


def _parse_date_token(value: str, *, fallback_year: int | None = None) -> date | None:
    normalized = normalize_whitespace(value)
    numeric = _NUMERIC_DATE_RE.fullmatch(normalized)
    if numeric is not None:
        try:
            return date(
                int(numeric.group("year")),
                int(numeric.group("month")),
                int(numeric.group("day")),
            )
        except ValueError:
            return None
    return _parse_word_date(normalized, fallback_year=fallback_year)


def _explicit_year(value: str) -> int | None:
    numeric = _NUMERIC_DATE_RE.fullmatch(normalize_whitespace(value))
    if numeric is not None:
        return int(numeric.group("year"))
    word = _WORD_DATE_RE.fullmatch(normalize_whitespace(value))
    if word is not None and word.group("year") is not None:
        return int(word.group("year"))
    return None


def _parse_application_period(
    start_text: str,
    end_text: str,
    *,
    fallback_year: int | None = None,
) -> tuple[date, date] | None:
    """Parse a date range only when a year can be inferred without guessing."""

    start_year = _explicit_year(start_text)
    end_year = _explicit_year(end_text)
    start = _parse_date_token(start_text, fallback_year=end_year or fallback_year)
    end = _parse_date_token(end_text, fallback_year=start_year or fallback_year)
    if start is None or end is None:
        return None

    if start > end:
        if start_year is None and end_year is not None:
            start = _parse_date_token(start_text, fallback_year=end.year - 1)
        elif end_year is None and start_year is not None:
            end = _parse_date_token(end_text, fallback_year=start.year + 1)
        elif start_year is None and end_year is None and fallback_year is not None:
            end = _parse_date_token(end_text, fallback_year=fallback_year + 1)
    if start is None or end is None or start > end:
        return None
    return start, end


@dataclass(frozen=True)
class ApplicationDates:
    start_on: date | None
    end_on: date | None
    evidence: tuple[str, ...] = ()
    error: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class TimelineEvent:
    label: str
    kind: str
    start_on: date | None
    end_on: date | None
    evidence: str
    date_parse_error: bool = False


@dataclass(frozen=True)
class _ScheduleSegment:
    label: str
    detail: str
    evidence: str


def _shared_month_period(
    value: str,
    *,
    fallback_year: int | None = None,
) -> tuple[date, date] | None:
    match = _SHARED_MONTH_PERIOD_RE.search(value)
    if match is None:
        return None
    raw_year = match.group("year")
    if raw_year is None and fallback_year is None:
        return None
    try:
        month = RUSSIAN_MONTHS[match.group("month").lower()]
        year = int(raw_year) if raw_year is not None else fallback_year
        if year is None:
            return None
        return (
            date(year, month, int(match.group("start_day"))),
            date(year, month, int(match.group("end_day"))),
        )
    except ValueError:
        return None


def extract_date_span(
    value: str,
    *,
    fallback_year: int | None = None,
) -> tuple[date | None, date | None]:
    """Return explicit source dates, inferring a shared month/year only when written."""

    normalized = normalize_whitespace(value)
    if not normalized:
        return None, None
    shared_period = _shared_month_period(normalized, fallback_year=fallback_year)
    if shared_period is not None:
        return shared_period
    for match in _PERIOD_RE.finditer(normalized):
        period = _parse_application_period(
            match.group("start"),
            match.group("end"),
            fallback_year=fallback_year,
        )
        if period is not None:
            return period
    for match in _DATE_TOKEN_RE.finditer(normalized):
        parsed = _parse_date_token(match.group(), fallback_year=fallback_year)
        if parsed is not None:
            return None, parsed
    return None, None


def parse_source_date(value: str) -> date | None:
    """Parse a labelled source date only when the page includes an explicit year."""

    _start, end = extract_date_span(value)
    return end


def _timeline_kind(label: str) -> str:
    normalized = normalize_heading(label)
    if "экспертиз" in normalized or "оценк" in normalized or "рассмотрен" in normalized:
        return "evaluation"
    if "договор" in normalized or "контракт" in normalized:
        return "contracting"
    if "результат" in normalized or "победител" in normalized or "итог" in normalized:
        return "results"
    if (
        "реализац" in normalized
        or "исполнен" in normalized
        or ("начал" in normalized and ("проект" in normalized or "выплат" in normalized))
    ):
        return "implementation"
    if (
        ("начал" in normalized or "открыти" in normalized)
        and ("прием" in normalized or "приём" in normalized or "подач" in normalized)
        and "заяв" in normalized
    ):
        return "application_open"
    if (
        ("окончани" in normalized or "завершени" in normalized)
        and ("прием" in normalized or "приём" in normalized or "подач" in normalized)
        and "заяв" in normalized
    ):
        return "application_close"
    if "заяв" in normalized or "прием" in normalized or "приём" in normalized:
        return "application"
    return "other"


def _segment_label_and_detail(value: str) -> tuple[str, str]:
    label, separator, detail = value.partition(":")
    if not separator:
        date_match = _DATE_TOKEN_RE.search(value)
        if date_match is not None:
            label = value[: date_match.start()]
            detail = value[date_match.start() :]
        else:
            label = value
            detail = value
    label = re.sub(r"\b(?:с|по|до|не\s+позднее)\s*$", "", label, flags=re.IGNORECASE)
    return normalize_whitespace(label), normalize_whitespace(detail)


def _schedule_segments(value: str) -> tuple[_ScheduleSegment, ...]:
    normalized = normalize_whitespace(value)
    if not normalized:
        return ()
    matches = tuple(_SCHEDULE_EVENT_LABEL_RE.finditer(normalized))
    if not matches:
        return ()

    segments: list[_ScheduleSegment] = []
    current_cycle: str | None = None
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        evidence = normalized[match.start() : next_start].strip(" ;")
        if not evidence:
            continue
        cycle = normalize_whitespace(match.group("cycle") or "")
        if cycle:
            current_cycle = cycle
        label, detail = _segment_label_and_detail(evidence)
        if not label:
            continue
        if current_cycle and _CYCLE_PREFIX_RE.match(label) is None:
            label = f"{current_cycle} — {label}"
        segments.append(
            _ScheduleSegment(
                label=label[:500],
                detail=detail,
                evidence=evidence,
            )
        )
    return tuple(segments)


def extract_timeline_events(
    texts: Iterable[str],
    *,
    fallback_year: int | None = None,
) -> tuple[TimelineEvent, ...]:
    """Preserve labelled schedule events without treating evaluation as application."""

    events: list[TimelineEvent] = []
    seen: set[tuple[str, date | None, date | None]] = set()
    for raw_text in texts:
        for segment in _schedule_segments(raw_text):
            start_on, end_on = extract_date_span(
                segment.detail,
                fallback_year=fallback_year,
            )
            date_parse_error = (
                start_on is None
                and end_on is None
                and _DATE_TOKEN_RE.search(segment.detail) is not None
            )
            if start_on is None and end_on is None and not date_parse_error:
                continue
            key = (segment.label.casefold(), start_on, end_on)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                TimelineEvent(
                    label=segment.label,
                    kind=_timeline_kind(segment.label),
                    start_on=start_on,
                    end_on=end_on,
                    evidence=segment.evidence,
                    date_parse_error=date_parse_error,
                )
            )
    return tuple(events)


def _unique_evidence(events: Iterable[TimelineEvent]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(event.evidence for event in events if event.evidence))


def _multiple_application_windows_are_explicit(events: Iterable[TimelineEvent]) -> bool:
    event_list = tuple(events)
    return bool(event_list) and all("цикл" in normalize_heading(event.label) for event in event_list)


def extract_application_dates(events: Iterable[TimelineEvent]) -> ApplicationDates:
    """Return one canonical application interval only when the source states one."""

    application_events = tuple(
        event
        for event in events
        if event.kind in {"application", "application_open", "application_close"}
    )
    if not application_events:
        return ApplicationDates(start_on=None, end_on=None)
    invalid_events = tuple(event for event in application_events if event.date_parse_error)
    if invalid_events:
        return ApplicationDates(
            start_on=None,
            end_on=None,
            evidence=_unique_evidence(invalid_events),
            error="application_period_invalid",
        )

    ranged_events = tuple(
        event
        for event in application_events
        if event.kind == "application" and (event.start_on is not None or event.end_on is not None)
    )
    unique_ranges = tuple(
        dict.fromkeys((event.start_on, event.end_on) for event in ranged_events)
    )
    if len(unique_ranges) == 1:
        start_on, end_on = unique_ranges[0]
        return ApplicationDates(
            start_on=start_on,
            end_on=end_on,
            evidence=_unique_evidence(ranged_events),
        )
    if len(unique_ranges) > 1:
        evidence = _unique_evidence(ranged_events)
        if _multiple_application_windows_are_explicit(ranged_events):
            return ApplicationDates(
                start_on=None,
                end_on=None,
                evidence=evidence,
                warning="multiple_application_windows",
            )
        return ApplicationDates(
            start_on=None,
            end_on=None,
            evidence=evidence,
            error="application_period_conflict",
        )

    opening_events = tuple(
        event
        for event in application_events
        if event.kind == "application_open" and (event.start_on is not None or event.end_on is not None)
    )
    closing_events = tuple(
        event
        for event in application_events
        if event.kind == "application_close" and (event.start_on is not None or event.end_on is not None)
    )
    if len(opening_events) <= 1 and len(closing_events) <= 1:
        start_on = (
            opening_events[0].start_on or opening_events[0].end_on
            if opening_events
            else None
        )
        end_on = (
            closing_events[0].end_on or closing_events[0].start_on
            if closing_events
            else None
        )
        if start_on is None and end_on is None:
            return ApplicationDates(start_on=None, end_on=None)
        if start_on is not None and end_on is not None and start_on > end_on:
            return ApplicationDates(
                start_on=None,
                end_on=None,
                evidence=_unique_evidence((*opening_events, *closing_events)),
                error="application_period_conflict",
            )
        return ApplicationDates(
            start_on=start_on,
            end_on=end_on,
            evidence=_unique_evidence((*opening_events, *closing_events)),
        )

    return ApplicationDates(
        start_on=None,
        end_on=None,
        evidence=_unique_evidence(application_events),
        error="application_period_conflict",
    )


def _money_amount_from_parts(number: str, unit: str) -> Decimal | None:
    raw_number = number.replace("\u00a0", " ").replace(" ", "")
    separators = [index for index, char in enumerate(raw_number) if char in {",", "."}]
    if len(separators) > 1:
        decimal_index = separators[-1]
        decimal_digits = raw_number[decimal_index + 1 :]
        if len(decimal_digits) in {1, 2}:
            raw_number = (
                raw_number[:decimal_index].replace(",", "").replace(".", "")
                + "."
                + decimal_digits
            )
        else:
            raw_number = raw_number.replace(",", "").replace(".", "")
    elif len(separators) == 1:
        separator_index = separators[0]
        fractional_digits = raw_number[separator_index + 1 :]
        if len(fractional_digits) == 3:
            raw_number = raw_number.replace(",", "").replace(".", "")
        elif raw_number[separator_index] == ",":
            raw_number = raw_number.replace(",", ".")
    try:
        value = Decimal(raw_number)
    except InvalidOperation:
        return None
    normalized_unit = unit.lower().rstrip(".")
    if normalized_unit.startswith("тыс") or normalized_unit.startswith("тысяч"):
        return value * 1_000
    if normalized_unit.startswith("млн") or normalized_unit.startswith("миллион"):
        return value * 1_000_000
    if normalized_unit.startswith("млрд") or normalized_unit.startswith("миллиард"):
        return value * 1_000_000_000
    return value


def parse_rub_amounts(value: str) -> tuple[Decimal, ...]:
    amounts: list[Decimal] = []
    for match in _MONEY_RE.finditer(normalize_whitespace(value)):
        amount = _money_amount_from_parts(match.group("number"), match.group("unit"))
        if amount is not None and amount > 0 and amount not in amounts:
            amounts.append(amount)
    return tuple(amounts)


def _funding_payload(funding: FundingInput) -> dict[str, str | None]:
    return funding.model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True)
class FundingObservation:
    funding: FundingInput
    evidence: tuple[str, ...] = ()
    breakdown: tuple[dict[str, object], ...] = ()
    warning: str | None = None
    error: str | None = None


def _funding_text(value: str | tuple[str, str]) -> tuple[str, str]:
    if isinstance(value, tuple):
        heading, text = value
        return normalize_whitespace(heading), normalize_whitespace(text)
    return "", normalize_whitespace(value)


def _breakdown_entry(
    funding: FundingInput,
    *,
    evidence: str,
    label: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "value": _funding_payload(funding),
        "evidence": evidence,
    }
    if label:
        entry["label"] = label
    return entry


def extract_total_grant_fund(
    texts: Iterable[str | tuple[str, str]],
) -> FundingObservation:
    matches: list[tuple[Decimal, str, bool, str | None]] = []
    for raw_value in texts:
        heading, text = _funding_text(raw_value)
        normalized_heading = normalize_heading(heading)
        heading_mentions_fund = any(
            marker in normalized_heading
            for marker in ("грантовый фонд", "общий фонд", "фонд поддержки", "бюджет конкурса")
        )
        for sentence in _funding_sentences(text):
            sentence_mentions_fund = bool(
                re.search(r"(?:общий\s+)?грантовый\s+фонд", sentence, re.IGNORECASE)
            )
            if not heading_mentions_fund and not sentence_mentions_fund:
                continue
            for amount in parse_rub_amounts(sentence):
                matches.append((amount, sentence, sentence_mentions_fund, heading or None))

    values = {amount for amount, _evidence, _explicit, _label in matches}
    if not values:
        return FundingObservation(FundingInput(value_kind=FundingValueKind.NOT_STATED))
    if len(values) > 1:
        explicitly_named_values = {
            amount for amount, _evidence, explicit, _label in matches if explicit
        }
        breakdown = tuple(
            _breakdown_entry(
                FundingInput(
                    value_kind=FundingValueKind.EXACT,
                    currency_code="RUB",
                    exact_amount=amount,
                ),
                evidence=evidence,
                label=label,
            )
            for amount, evidence, _explicit, label in matches
        )
        if len(explicitly_named_values) > 1:
            return FundingObservation(
                FundingInput(value_kind=FundingValueKind.UNKNOWN),
                evidence=tuple(evidence for _amount, evidence, _explicit, _label in matches),
                breakdown=breakdown,
                error="total_grant_fund_conflict",
            )
        return FundingObservation(
            FundingInput(value_kind=FundingValueKind.UNKNOWN),
            evidence=tuple(evidence for _amount, evidence, _explicit, _label in matches),
            breakdown=breakdown,
            warning="total_grant_fund_breakdown_required",
        )
    amount = values.pop()
    return FundingObservation(
        FundingInput(
            value_kind=FundingValueKind.EXACT,
            currency_code="RUB",
            exact_amount=amount,
        ),
        evidence=tuple(evidence for _amount, evidence, _explicit, _label in matches),
    )


def _funding_sentences(value: str) -> tuple[str, ...]:
    normalized = normalize_whitespace(value)
    if not normalized:
        return ()
    parts = re.split(r"(?<=[.!?;])\s+|\s+[—–-]\s+(?=[А-ЯЁ])", normalized)
    return tuple(part for part in parts if part)


def _has_funding_context(value: str) -> bool:
    return bool(
        re.search(
            r"(?:грант\w*|поддержк\w*|финансир\w*|субсид\w*)",
            value,
            re.IGNORECASE,
        )
    )


def _funding_from_sentence(
    value: str,
    *,
    inherited_funding_context: bool = False,
) -> FundingInput | None:
    """Recognize a bounded per-program amount, never a bare unrelated number."""

    lower = value.lower()
    amounts = parse_rub_amounts(value)
    if not amounts or not (
        _has_funding_context(lower) or inherited_funding_context
    ):
        return None
    shared_range = _SHARED_CURRENCY_RANGE_RE.search(value)
    if shared_range is not None:
        minimum = _money_amount_from_parts(
            shared_range.group("minimum"), shared_range.group("unit")
        )
        maximum = _money_amount_from_parts(
            shared_range.group("maximum"), shared_range.group("unit")
        )
        if minimum is not None and maximum is not None and minimum <= maximum:
            return FundingInput(
                value_kind=FundingValueKind.RANGE,
                currency_code="RUB",
                min_amount=minimum,
                max_amount=maximum,
            )
    if re.search(r"\bот\s+.+?\s+до\s+.+", lower) and len(amounts) >= 2:
        return FundingInput(
            value_kind=FundingValueKind.RANGE,
            currency_code="RUB",
            min_amount=min(amounts),
            max_amount=max(amounts),
        )
    if re.search(r"(?:максимальн\w*|не\s+более|\bдо\s+\d)", lower):
        return FundingInput(
            value_kind=FundingValueKind.MAXIMUM,
            currency_code="RUB",
            max_amount=max(amounts),
        )
    if re.search(r"(?:минимальн\w*|не\s+менее)", lower):
        return FundingInput(
            value_kind=FundingValueKind.MINIMUM,
            currency_code="RUB",
            min_amount=min(amounts),
        )
    if re.search(
        r"(?:размер\s+(?:гранта|поддержки)|грант|поддержк\w*)"
        r".{0,80}(?:составля\w*|рав(?:е|н)\w*|в\s+размере)",
        lower,
    ):
        return FundingInput(
            value_kind=FundingValueKind.EXACT,
            currency_code="RUB",
            exact_amount=amounts[0],
        )
    return None


def _funding_label(value: str, fallback: str | None) -> str | None:
    nomination = re.search(
        r"\b(?P<word>номинаци\w*)\s+"
        r"(?P<names>«[^»]+»(?:\s*(?:,|и)\s*«[^»]+»)*)",
        value,
        re.IGNORECASE,
    )
    if nomination is not None:
        label = normalize_whitespace(
            f"Номинации: {nomination.group('names')}"
        )
        if label:
            return label[:200]
    prefix, separator, _rest = value.partition(":")
    if separator and 1 <= len(prefix.strip()) <= 200:
        return normalize_whitespace(prefix)
    return fallback


def extract_per_program_funding(
    texts: Iterable[str | tuple[str, str]],
) -> FundingObservation:
    observations: list[tuple[FundingInput, str, str | None]] = []
    for raw_value in texts:
        heading, text = _funding_text(raw_value)
        normalized = normalize_whitespace(text)
        if not normalized:
            continue
        inherited_funding_context = _has_funding_context(normalized)
        for sentence in _funding_sentences(normalized):
            if re.search(r"(?:общий\s+)?грантовый\s+фонд", sentence, re.IGNORECASE):
                continue
            funding = _funding_from_sentence(
                sentence,
                inherited_funding_context=inherited_funding_context,
            )
            if funding is not None:
                observations.append((funding, sentence, _funding_label(sentence, heading or None)))

    if not observations:
        return FundingObservation(FundingInput(value_kind=FundingValueKind.NOT_STATED))

    unique = {
        tuple(sorted(funding.model_dump(mode="json", exclude_none=True).items()))
        for funding, _evidence, _label in observations
    }
    if len(unique) > 1:
        return FundingObservation(
            FundingInput(value_kind=FundingValueKind.UNKNOWN),
            evidence=tuple(evidence for _funding, evidence, _label in observations),
            breakdown=tuple(
                _breakdown_entry(funding, evidence=evidence, label=label)
                for funding, evidence, label in observations
            ),
            warning="per_program_funding_ambiguous",
        )
    funding, _evidence, _label = observations[0]
    return FundingObservation(
        funding,
        evidence=tuple(evidence for _funding, evidence, _label in observations),
    )


def funding_payload(observation: FundingObservation) -> dict[str, object]:
    payload: dict[str, object] = {
        "value": observation.funding.model_dump(mode="json", exclude_none=True),
        "evidence": list(observation.evidence),
    }
    if observation.breakdown:
        payload["breakdown"] = list(observation.breakdown)
    return payload


_THEMES = (
    ("education", "Образование", re.compile(r"\bобразован", re.IGNORECASE)),
    ("science", "Наука", re.compile(r"\bнаук", re.IGNORECASE)),
    ("culture", "Культура", re.compile(r"\bкультур", re.IGNORECASE)),
    ("social-sport", "Социальный спорт", re.compile(r"социальн\w*\s+спорт", re.IGNORECASE)),
    (
        "social-support",
        "Социальная поддержка",
        re.compile(r"социальн\w*\s+поддержк|уязвим\w*\s+социальн\w*\s+групп", re.IGNORECASE),
    ),
    ("philanthropy", "Благотворительность", re.compile(r"благотвор", re.IGNORECASE)),
    ("civil-society", "Гражданское общество", re.compile(r"гражданск", re.IGNORECASE)),
)


def normalize_themes(texts: Iterable[str]) -> list[dict[str, str]]:
    combined = " ".join(normalize_whitespace(text) for text in texts)
    return [
        {"slug": slug, "name": name}
        for slug, name, pattern in _THEMES
        if pattern.search(combined)
    ]


def normalize_geographies(texts: Iterable[str]) -> list[dict[str, str]]:
    combined = " ".join(normalize_whitespace(text) for text in texts)
    if re.search(
        r"(?:все\s+регионы\s+россии|всех\s+регионах\s+россии|по\s+всей\s+россии|"
        r"на\s+всей\s+территории\s+россии|российск\w*\s+федерац)",
        combined,
        re.IGNORECASE,
    ):
        return [{"slug": "russia", "name": "Россия"}]
    if re.search(
        r"российск\w*\s+(?:организац|нко|юридическ\w*\s+лиц|участник)",
        combined,
        re.IGNORECASE,
    ):
        return [{"slug": "russia", "name": "Россия"}]
    return []


def parse_sitemap_lastmod(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).isoformat()
    except ValueError:
        try:
            return date.fromisoformat(normalized).isoformat()
        except ValueError:
            return None

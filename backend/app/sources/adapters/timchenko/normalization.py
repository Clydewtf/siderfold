from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from app.domain.geography import FEDERAL_DISTRICTS
from app.domain.models import FundingValueKind
from app.import_bridge.contract import FundingInput
from app.sources.adapters.potanin.normalization import (
    FundingObservation,
    RUSSIAN_MONTHS,
    TimelineEvent,
    extract_application_dates as _extract_application_dates,
    extract_date_span,
    extract_total_grant_fund,
    funding_payload,
    normalize_whitespace as _potanin_normalize_whitespace,
    parse_rub_amounts,
)
from app.sources.registry import normalize_url


TIMCHENKO_HOST = "fondtimchenko.ru"
TIMCHENKO_CONTESTS_PATH = "/contests"
TIMCHENKO_CATALOG_SECTIONS = ("programs", "ready", "archive")
TIMCHENKO_CATALOG_STATUS = {
    "programs": "open",
    "ready": "closed",
    "archive": "closed",
}

_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "yclid"}
_MONTHS_PATTERN = "|".join(RUSSIAN_MONTHS)
_DATE_TOKEN_PATTERN = (
    r"(?:\d{1,2}[./]\d{1,2}[./]\d{4}|"
    r"\d{1,2}\s+(?:"
    + _MONTHS_PATTERN
    + r")(?:\s+\d{4})?(?:\s*г(?:ода?|\.)?)?)"
)
_DATE_TOKEN_RE = re.compile(_DATE_TOKEN_PATTERN, re.IGNORECASE)
_PERIOD_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN_PATTERN})\s*(?:по|до|[-–—])\s*"
    rf"(?P<end>{_DATE_TOKEN_PATTERN})",
    re.IGNORECASE,
)


def normalize_whitespace(value: str) -> str:
    return _potanin_normalize_whitespace(value)


def normalize_heading(value: str) -> str:
    return re.sub(r"[^\w\s]", "", normalize_whitespace(value).lower()).strip()


def normalize_competition_url(value: str) -> str:
    """Return a strict canonical Timchenko competition-card URL.

    Only the three public catalog namespaces are accepted.  This function is
    deliberately stricter than the source allowlist: the allowlist protects
    transport, while this function protects the record identity.
    """

    normalized = normalize_url(value)
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or parsed.hostname != TIMCHENKO_HOST:
        raise ValueError("competition URL must use the official Fond Timchenko origin")

    raw_path = parsed.path
    decoded_path = unquote(raw_path)
    if (
        "\\" in decoded_path
        or re.search(r"%(?:2e|2f|5c)", raw_path, re.IGNORECASE)
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        raise ValueError("competition URL must not contain path traversal")

    path = re.sub(r"/{2,}", "/", raw_path).rstrip("/")
    parts = path.split("/")
    if len(parts) != 4 or parts[1] != "contests" or parts[2] not in TIMCHENKO_CATALOG_SECTIONS:
        raise ValueError(
            "competition URL must be under /contests/programs/, /contests/ready/, "
            "or /contests/archive/"
        )
    if not parts[3] or parts[3] in {".", ".."}:
        raise ValueError("the contests catalog is not a competition card")

    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_QUERY_KEYS
            and not key.lower().startswith("utm_")
        ],
        doseq=True,
    )
    return urlunsplit(("https", TIMCHENKO_HOST, f"{path}/", query, ""))


def normalize_outbound_url(value: str) -> str | None:
    """Normalize a safe HTTP(S) link without making a request to it."""

    try:
        normalized = normalize_url(value)
    except ValueError:
        return None
    parsed = urlsplit(normalized)
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_QUERY_KEYS
            and not key.lower().startswith("utm_")
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def normalize_title(value: str) -> str:
    """Make a reader-facing title while retaining the source title separately."""

    title = normalize_whitespace(value)
    title = re.sub(r"^конкурс\s+", "", title, flags=re.IGNORECASE)
    quoted_year = re.fullmatch(r"[«\"“](.+?)[»\"”]\s+(20\d{2})", title)
    if quoted_year is not None:
        title = f"{quoted_year.group(1)} {quoted_year.group(2)}"
    return title.strip("«»\"“” ")


def years_in_text(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(dict.fromkeys(int(match) for match in re.findall(r"\b(20\d{2})\b", value)))


def infer_year(*values: str | None) -> int | None:
    years: list[int] = []
    for value in values:
        years.extend(years_in_text(value))
    unique = tuple(dict.fromkeys(years))
    return unique[0] if len(unique) == 1 else None


def date_tokens(value: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _DATE_TOKEN_RE.finditer(normalize_whitespace(value)))


def parse_period(value: str, *, fallback_year: int | None = None) -> tuple[date | None, date | None]:
    """Parse a date range while allowing a year from explicit local context."""

    normalized = normalize_whitespace(value)
    for match in _PERIOD_RE.finditer(normalized):
        start, end = extract_date_span(match.group(0), fallback_year=fallback_year)
        if start is not None or end is not None:
            return start, end
    return extract_date_span(normalized, fallback_year=fallback_year)


def extract_top_application_periods(
    texts: Iterable[str],
    *,
    fallback_year: int | None = None,
) -> tuple[tuple[date | None, date | None, str], ...]:
    """Read only explicit top-block application-period evidence.

    The site has used both a sentence form ("Прием заявок с ... по ...") and
    a short label/value form.  Keeping the matched evidence makes conflicts
    reviewable instead of silently choosing one date.
    """

    periods: list[tuple[date | None, date | None, str]] = []
    marker = re.compile(r"(?:при[её]м|подач[аи])\s+заяв\w*", re.IGNORECASE)
    for raw_text in texts:
        text = normalize_whitespace(raw_text)
        for match in marker.finditer(text):
            window_end = min(len(text), match.end() + 260)
            evidence = text[match.start() : window_end]
            if not re.search(r"\bс\b|\bпо\b|\bдо\b|[-–—]", evidence, re.IGNORECASE):
                continue
            start, end = parse_period(evidence, fallback_year=fallback_year)
            if start is None and end is None and date_tokens(evidence):
                periods.append((None, None, evidence))
                continue
            if start is not None or end is not None:
                candidate = (start, end, evidence)
                if candidate not in periods:
                    periods.append(candidate)
    return tuple(periods)


def timeline_kind(label: str) -> str:
    normalized = normalize_heading(label)
    if any(term in normalized for term in ("эксперт", "отбор", "оценк", "рассмотр")):
        return "evaluation"
    if any(term in normalized for term in ("победител", "результат", "итог")):
        return "results"
    if any(term in normalized for term in ("договор", "контракт")):
        return "contracting"
    if any(term in normalized for term in ("реализац", "поддержанн")):
        return "implementation"
    if any(term in normalized for term in ("старт", "начал", "открыт")) and "заяв" in normalized:
        return "application_open"
    if any(term in normalized for term in ("окончан", "заверш", "закрыт")) and "заяв" in normalized:
        return "application_close"
    if any(term in normalized for term in ("вебинар", "семинар", "консультац")):
        return "other"
    if "заяв" in normalized or "прием" in normalized or "приём" in normalized:
        return "application"
    return "other"


def _timeline_label(value: str, date_text: str) -> str:
    label = value.replace(date_text, " ")
    label = re.sub(r"\b\d{1,2}\b", " ", label)
    label = re.sub(r"^[\s:.;,№-]+|[\s:.;,№-]+$", "", label)
    return normalize_whitespace(label) or "Этап конкурса"


def extract_timchenko_timeline(
    texts: Iterable[str],
    *,
    fallback_year: int | None = None,
) -> tuple[TimelineEvent, ...]:
    """Extract Timchenko's numbered stage blocks and preserve their evidence."""

    events: list[TimelineEvent] = []
    seen: set[tuple[str, date | None, date | None]] = set()
    for raw_text in texts:
        normalized = normalize_whitespace(raw_text)
        if not normalized:
            continue
        matches = list(_PERIOD_RE.finditer(normalized))
        if matches:
            chunks = [(match.group(0), match.start(), match.end()) for match in matches]
        else:
            chunks = [
                (match.group(0), match.start(), match.end())
                for match in _DATE_TOKEN_RE.finditer(normalized)
            ]
        for date_text, _start_index, _end_index in chunks:
            start_on, end_on = parse_period(date_text, fallback_year=fallback_year)
            label = _timeline_label(normalized, date_text)
            date_parse_error = (
                start_on is None
                and end_on is None
                and bool(date_tokens(date_text))
            )
            if start_on is None and end_on is None and not date_parse_error:
                continue
            key = (label.casefold(), start_on, end_on)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                TimelineEvent(
                    label=label[:500],
                    kind=timeline_kind(label),
                    start_on=start_on,
                    end_on=end_on,
                    evidence=normalized[:2_000],
                    date_parse_error=date_parse_error,
                    date_label=normalize_whitespace(date_text)[:500],
                )
            )
    return tuple(events)


def extract_application_dates(events: Iterable[TimelineEvent]):
    return _extract_application_dates(events)


@dataclass(frozen=True)
class TimchenkoFunding:
    record_funding: FundingInput
    total_grant_fund: FundingObservation
    per_program: FundingObservation
    amounts: tuple[dict[str, object], ...]
    warning: str | None = None
    error: str | None = None


def _funding_from_text(value: str, *, heading: str = "") -> FundingInput | None:
    text = normalize_whitespace(value)
    amounts = parse_rub_amounts(text)
    if not amounts:
        return None
    lower = f"{heading} {text}".lower()
    if re.search(r"\bот\s+.+?\s+до\s+", lower) and len(amounts) >= 2:
        return FundingInput(
            value_kind=FundingValueKind.RANGE,
            currency_code="RUB",
            min_amount=min(amounts),
            max_amount=max(amounts),
        )
    if re.search(r"(?:\bдо\b|максимальн\w*|не\s+более)", lower):
        return FundingInput(
            value_kind=FundingValueKind.MAXIMUM,
            currency_code="RUB",
            max_amount=max(amounts),
        )
    if re.search(r"(?:минимальн\w*|не\s+менее|от\s+\d)", lower):
        return FundingInput(
            value_kind=FundingValueKind.MINIMUM,
            currency_code="RUB",
            min_amount=min(amounts),
        )
    if re.search(r"(?:размер|финансирован|пожертвован|грант|поддержк|рубл)", lower):
        return FundingInput(
            value_kind=FundingValueKind.EXACT,
            currency_code="RUB",
            exact_amount=amounts[0],
        )
    return None


def _funding_entry(
    funding: FundingInput,
    *,
    evidence: str,
    label: str,
) -> dict[str, object]:
    return {
        "value": funding.model_dump(mode="json", exclude_none=True),
        "evidence": evidence,
        "label": label,
    }


def extract_timchenko_funding(
    texts: Iterable[str | tuple[str, str]],
) -> TimchenkoFunding:
    per_observations: list[tuple[FundingInput, str, str]] = []
    total_inputs: list[tuple[str, str]] = []
    for raw_value in texts:
        if isinstance(raw_value, tuple):
            heading, text = raw_value
        else:
            heading, text = "", raw_value
        heading = normalize_whitespace(heading)
        text = normalize_whitespace(text)
        if not text:
            continue
        heading_normalized = normalize_heading(heading)
        if any(marker in heading_normalized for marker in ("грантовый фонд", "общий фонд", "бюджет конкурса")):
            total_inputs.append((heading, text))
        for sentence in re.split(r"(?<=[.!?;])\s+|\s+[—–-]\s+(?=[А-ЯЁ])", text):
            funding = _funding_from_text(sentence, heading=heading)
            if funding is None:
                continue
            per_observations.append((funding, normalize_whitespace(sentence), heading or "Размер финансирования проекта"))

    total = extract_total_grant_fund(total_inputs)
    unique_per: list[tuple[str, FundingInput, str, str]] = []
    for funding, evidence, label in per_observations:
        key = repr(funding.model_dump(mode="json", exclude_none=True))
        if not any(key == known[0] for known in unique_per):
            unique_per.append((key, funding, evidence, label))

    warning: str | None = None
    per_breakdown: tuple[dict[str, object], ...] = ()
    if not unique_per:
        per = FundingObservation(FundingInput(value_kind=FundingValueKind.NOT_STATED))
    elif len(unique_per) == 1:
        _key, funding, evidence, label = unique_per[0]
        per = FundingObservation(funding, evidence=(evidence,), breakdown=())
    else:
        warning = "per_program_funding_ambiguous"
        per_breakdown = tuple(
            _funding_entry(funding, evidence=evidence, label=label)
            for _key, funding, evidence, label in unique_per
        )
        per = FundingObservation(
            FundingInput(value_kind=FundingValueKind.UNKNOWN),
            evidence=tuple(evidence for _key, _funding, evidence, _label in unique_per),
            breakdown=per_breakdown,
            warning=warning,
        )

    record_funding = per.funding
    if record_funding.value_kind is FundingValueKind.NOT_STATED and total.funding.value_kind not in {
        FundingValueKind.NOT_STATED,
        FundingValueKind.UNKNOWN,
    }:
        record_funding = total.funding

    amounts: list[dict[str, object]] = []
    total_entries = total.breakdown or (
        {
            "value": total.funding.model_dump(mode="json", exclude_none=True),
            "evidence": " ".join(total.evidence),
            "label": "Фонд конкурса",
        },
    )
    for entry in total_entries:
        if isinstance(entry, dict) and entry.get("value", {}).get("value_kind") != "not_stated":
            amounts.append(
                {
                    "scope": "announced_total",
                    "value": entry.get("value"),
                    "label": entry.get("label") or "Фонд конкурса",
                    "evidence": entry.get("evidence") or None,
                }
            )
    per_entries = per.breakdown or (
        {
            "value": per.funding.model_dump(mode="json", exclude_none=True),
            "evidence": " ".join(per.evidence),
            "label": "На один проект",
        },
    )
    for entry in per_entries:
        if isinstance(entry, dict) and entry.get("value", {}).get("value_kind") != "not_stated":
            amounts.append(
                {
                    "scope": "per_recipient",
                    "value": entry.get("value"),
                    "label": entry.get("label") or "На один проект",
                    "evidence": entry.get("evidence") or None,
                }
            )

    unique_amounts: list[dict[str, object]] = []
    for amount in amounts:
        if amount not in unique_amounts:
            unique_amounts.append(amount)

    return TimchenkoFunding(
        record_funding=record_funding,
        total_grant_fund=total,
        per_program=per,
        amounts=tuple(unique_amounts),
        warning=warning or total.warning,
        error=total.error,
    )


_THEME_RULES = (
    ("education", "Образование", re.compile(r"образован|профессиональн\w* самоопредел", re.I)),
    ("social-support", "Социальная поддержка", re.compile(r"тяжел\w* жизненн|социальн\w* поддержк|помощ\w* детям|помощ\w* взросл", re.I)),
    ("family-support", "Поддержка семей", re.compile(r"помощ\w* семь|семь\w*", re.I)),
    ("senior-support", "Поддержка старшего поколения", re.compile(r"старш\w* возраст|пожил\w*", re.I)),
    ("sports-health", "Спорт и здоровье", re.compile(r"спорт|здоров", re.I)),
    ("volunteering", "Волонтерство", re.compile(r"волонтер|волонтёр", re.I)),
    ("ecology", "Экология", re.compile(r"эколог", re.I)),
    ("urban-environment", "Городская среда и благоустройство", re.compile(r"городск\w* сред|благоустрой", re.I)),
    ("culture-traditions", "Культура и традиции", re.compile(r"культур|традици", re.I)),
    ("accessibility", "Поддержка людей с инвалидностью", re.compile(r"ограниченн\w* возможност|инвалид", re.I)),
)


_SOURCE_CATEGORY_THEMES = {
    "забота": ("timchenko-care", "Забота"),
    "care": ("timchenko-care", "Забота"),
    "развитие": ("timchenko-development", "Развитие"),
    "development": ("timchenko-development", "Развитие"),
    "спецпроекты": ("timchenko-special-projects", "Спецпроекты"),
    "specialprojects": ("timchenko-special-projects", "Спецпроекты"),
    "special_projects": ("timchenko-special-projects", "Спецпроекты"),
}


def theme_from_source_category(value: str | None) -> dict[str, str] | None:
    """Map Fond Timchenko's own catalog category to a visible catalog theme."""

    if value is None:
        return None
    theme = _SOURCE_CATEGORY_THEMES.get(normalize_heading(value))
    return {"slug": theme[0], "name": theme[1]} if theme is not None else None


def normalize_themes(texts: Iterable[str]) -> list[dict[str, str]]:
    combined = " ".join(normalize_whitespace(text) for text in texts)
    return [
        {"slug": slug, "name": name}
        for slug, name, pattern in _THEME_RULES
        if pattern.search(combined)
    ]


_GEOGRAPHY_RULES = FEDERAL_DISTRICTS


def normalize_geographies(texts: Iterable[str]) -> list[dict[str, str]]:
    combined = " ".join(normalize_whitespace(text) for text in texts)
    geographies = [
        {"slug": slug, "name": name}
        for slug, name in _GEOGRAPHY_RULES
        if name.casefold() in combined.casefold()
    ]
    if geographies:
        return geographies
    if re.search(r"росси|российск|федеральн", combined, re.IGNORECASE):
        return [{"slug": "russia", "name": "Россия"}]
    return []


def extract_geography_note(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_whitespace(value)
    if not normalized:
        return None
    if re.search(r"росси|округ|регион|территор|населен|федеральн", normalized, re.I):
        return normalized
    return None

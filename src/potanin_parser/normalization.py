import re
from datetime import date
from decimal import Decimal, InvalidOperation


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

_MONTH_PATTERN = "|".join(RUSSIAN_MONTHS)
_DATE_PATTERN = rf"(\d{{1,2}})\s+({_MONTH_PATTERN})\s+(\d{{4}})(?:\s+года?)?"
_APPLICATION_PERIOD_RE = re.compile(
    rf"\bс\s+{_DATE_PATTERN}\s+по\s+{_DATE_PATTERN}",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"(?<![\w.,])(?<!\d )"
    r"(\d{1,3}(?: \d{3})+|\d+)(?:([.,]\d+))?\s*"
    r"(тыс\.?|млн\.?|млрд\.?|руб(?:ль|ля|лей)?\.?)"
    r"(?!\w)",
    re.IGNORECASE,
)
_MONEY_MULTIPLIERS = {
    "тыс": 1_000,
    "млн": 1_000_000,
    "млрд": 1_000_000_000,
}


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _to_iso_date(day: str, month: str, year: str) -> str | None:
    try:
        return date(int(year), RUSSIAN_MONTHS[month.lower()], int(day)).isoformat()
    except (KeyError, ValueError):
        return None


def extract_application_dates(text: str) -> tuple[str | None, str | None]:
    match = _APPLICATION_PERIOD_RE.search(_normalize_whitespace(text))
    if match is None:
        return None, None

    groups = match.groups()
    return _to_iso_date(*groups[:3]), _to_iso_date(*groups[3:])


def parse_money_values(text: str) -> list[int]:
    normalized = _normalize_whitespace(text)
    values = []
    seen = set()

    for match in _MONEY_RE.finditer(normalized):
        integer_text, fraction_text, unit = match.groups()
        try:
            number_text = integer_text.replace(" ", "")
            if fraction_text:
                number_text += fraction_text.replace(",", ".")
            number = Decimal(number_text)
        except InvalidOperation:
            continue

        normalized_unit = unit.lower().rstrip(".")
        multiplier = _MONEY_MULTIPLIERS.get(normalized_unit, 1)
        rubles = number * multiplier
        if rubles != rubles.to_integral_value():
            continue

        value = int(rubles)
        if value not in seen:
            seen.add(value)
            values.append(value)

    return values

import re
from datetime import date
from urllib.parse import urldefrag, urljoin

from lxml import html as lxml_html

from .models import Competition
from .normalization import RUSSIAN_MONTHS, extract_application_dates, parse_money_values


_HEADING_FIELDS = {
    "цели": "goals",
    "цели конкурса": "goals",
    "задачи": "tasks",
    "задачи конкурса": "tasks",
    "целевая аудитория": "target_audience",
    "номинации": "nominations",
    "направления проектов": "project_directions",
    "порядок проведения конкурса": "procedure",
    "процедура проведения конкурса": "procedure",
    "финансирование": "funding_text",
    "грантовый фонд": "funding_text",
}
_PUBLICATION_DATE_RE = re.compile(
    r"(\d{1,2})\s+(" + "|".join(RUSSIAN_MONTHS) + r")\s+(\d{4})",
    re.IGNORECASE,
)


def _text(node) -> str:
    return " ".join(node.text_content().split())


def _first_text(root, xpaths: list[str]) -> str | None:
    for xpath in xpaths:
        nodes = root.xpath(xpath)
        if nodes:
            value = _text(nodes[0])
            if value:
                return value
    return None


def _absolute_url(base_url: str, href: str) -> str:
    return urldefrag(urljoin(base_url, href))[0]


def _unique_links(nodes, base_url: str) -> list[str]:
    links = []
    seen = set()
    for node in nodes:
        href = node.get("href")
        if not href:
            continue
        link = _absolute_url(base_url, href)
        if link not in seen:
            seen.add(link)
            links.append(link)
    return links


def parse_catalog(html: str, base_url: str) -> list[str]:
    root = lxml_html.fromstring(html)
    anchors = root.xpath(
        "//a[contains(concat(' ', normalize-space(@class), ' '), "
        "' programms__item-link ')]"
    )
    return _unique_links(anchors, base_url)


def _normalize_heading(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _extract_sections(info) -> tuple[str | None, dict[str, str]]:
    summary_parts = []
    sections: dict[str, str] = {}
    heading = None

    for child in info:
        if child.tag.lower() == "h2":
            heading = _text(child)
            sections.setdefault(heading, "")
            continue

        value = _text(child)
        if not value:
            continue
        if heading is None:
            summary_parts.append(value)
        else:
            sections[heading] = " ".join(filter(None, [sections[heading], value]))

    summary = " ".join(summary_parts) or None
    return summary, sections


def _parse_publication_date(text: str | None) -> str | None:
    if not text:
        return None
    match = _PUBLICATION_DATE_RE.search(text)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return date(int(year), RUSSIAN_MONTHS[month.lower()], int(day)).isoformat()
    except ValueError:
        return None


def _support_value(text: str) -> int | None:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        for marker in re.finditer(r"максимальн\w*|не более", sentence, re.IGNORECASE):
            values = parse_money_values(sentence[marker.start() :])
            if values:
                return values[0]
    return None


def _contact_cards(root) -> list[dict[str, str]]:
    containers = root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' contacts ')]"
    )
    if not containers:
        return []
    cards = containers[0].xpath(
        ".//*[contains(concat(' ', normalize-space(@class), ' '), "
        "' contacts__item ') or contains(concat(' ', normalize-space(@class), ' '), "
        "' contact ') or contains(concat(' ', normalize-space(@class), ' '), "
        "' contacts__card ') or self::article]"
    )
    if not cards:
        cards = [containers[0]]

    contacts = []
    for card in cards:
        contact = {"text": _text(card)}
        name = _first_text(
            card,
            [
                ".//h2",
                ".//h3",
                ".//*[contains(concat(' ', normalize-space(@class), ' '), "
                "' contacts__name ')]",
                ".//*[contains(concat(' ', normalize-space(@class), ' '), "
                "' contact__name ')]",
            ],
        )
        email = card.xpath(".//a[starts-with(@href, 'mailto:')]/@href")
        phone = card.xpath(".//a[starts-with(@href, 'tel:')]/@href")
        if name:
            contact["name"] = name
        if email:
            contact["email"] = email[0].removeprefix("mailto:")
        if phone:
            contact["phone"] = phone[0].removeprefix("tel:")
        if contact["text"]:
            contacts.append(contact)
    return contacts


def parse_competition(html: str, source_url: str, collected_at: str) -> Competition:
    root = lxml_html.fromstring(html)
    title = _first_text(root, ["//h1"]) or ""
    status = _first_text(
        root,
        [
            "//*[contains(concat(' ', normalize-space(@class), ' '), "
            "' contest__status ')]",
            "//*[contains(concat(' ', normalize-space(@class), ' '), "
            "' contest-status ')]",
            "//*[contains(concat(' ', normalize-space(@class), ' '), ' status ')]",
            "//*[contains(@class, 'status')]",
        ],
    )
    publication_text = _first_text(
        root,
        [
            "//*[contains(concat(' ', normalize-space(@class), ' '), "
            "' aside__period ')]"
        ],
    )
    info_nodes = root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), "
        "' contest__info ')]"
    )

    summary = None
    sections: dict[str, str] = {}
    full_text = ""
    if info_nodes:
        summary, sections = _extract_sections(info_nodes[0])
        full_text = _text(info_nodes[0])

    fields: dict[str, str] = {}
    for heading, content in sections.items():
        field = _HEADING_FIELDS.get(_normalize_heading(heading))
        if field and content:
            fields[field] = content

    procedure = fields.get("procedure")
    date_text = " ".join(filter(None, [procedure, full_text]))
    application_start_date, application_end_date = extract_application_dates(date_text)
    funding_text = fields.get("funding_text")
    funding_values = parse_money_values(funding_text or "")
    grant_fund_rub = funding_values[0] if funding_values else None
    max_support_rub = _support_value(funding_text or full_text)

    application_nodes = root.xpath(
        "//a[contains(concat(' ', normalize-space(@class), ' '), "
        "' button_orange ')]"
    )
    application_links = _unique_links(application_nodes, source_url)
    result_nodes = [
        node
        for node in root.xpath("//a[@href]")
        if re.search(r"побед|итог", _text(node), re.IGNORECASE)
    ]
    document_nodes = root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' documents ')]"
        "//a[@href]"
    )

    warnings = []
    if not title:
        warnings.append("title not found")
    if not application_start_date or not application_end_date:
        warnings.append("application dates not found")
    if grant_fund_rub is None and max_support_rub is None:
        warnings.append("funding not found")
    if not info_nodes:
        warnings.append("content block not found")

    return Competition(
        source="fondpotanin.ru",
        source_url=source_url,
        collected_at=collected_at,
        title=title,
        status=status,
        publication_date=_parse_publication_date(publication_text),
        application_start_date=application_start_date,
        application_end_date=application_end_date,
        summary=summary,
        goals=fields.get("goals"),
        tasks=fields.get("tasks"),
        target_audience=fields.get("target_audience"),
        nominations=fields.get("nominations"),
        project_directions=fields.get("project_directions"),
        procedure=procedure,
        grant_fund_rub=grant_fund_rub,
        max_support_rub=max_support_rub,
        funding_text=funding_text,
        application_url=application_links[0] if application_links else None,
        result_urls=_unique_links(result_nodes, source_url),
        document_urls=_unique_links(document_nodes, source_url),
        contacts=_contact_cards(root),
        sections=sections,
        full_text=full_text,
        parse_warnings=warnings,
    )

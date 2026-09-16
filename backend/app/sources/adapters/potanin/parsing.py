from __future__ import annotations

import re
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass
from typing import Any, Iterable, Literal
from urllib.parse import urldefrag, urljoin, urlsplit

from lxml import etree, html as lxml_html

from app.domain.presentation import (
    infer_access_mode,
    is_schedule_milestone_title,
    is_social_resource_url,
    is_winner_resource,
    public_program_title,
)
from app.sources.adapters.potanin.normalization import (
    POTANIN_HOST,
    extract_geography_note,
    extract_application_dates,
    extract_per_program_funding,
    extract_total_grant_fund,
    extract_timeline_events,
    funding_payload,
    normalize_competition_url,
    normalize_geographies,
    normalize_heading,
    normalize_outbound_url,
    normalize_themes,
    normalize_whitespace,
    parse_rub_amounts,
    parse_sitemap_lastmod,
    parse_source_date,
)


@dataclass(frozen=True)
class ParserIssue:
    severity: Literal["warning", "error"]
    code: str
    field: str
    message: str


@dataclass(frozen=True)
class SitemapEntry:
    url: str
    last_modified_at: str | None


@dataclass(frozen=True)
class SitemapParseResult:
    entries: tuple[SitemapEntry, ...]
    issues: tuple[ParserIssue, ...] = ()


@dataclass(frozen=True)
class ParsedCompetitionPage:
    record_payload: dict[str, Any]
    issues: tuple[ParserIssue, ...] = ()


def _tag_name(node: Any) -> str:
    tag = getattr(node, "tag", "")
    return tag.lower() if isinstance(tag, str) else ""


def _node_text(node: Any) -> str:
    return normalize_whitespace(" ".join(node.itertext()))


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def parse_competitions_sitemap(content: bytes) -> SitemapParseResult:
    """Parse the official XML list without treating arbitrary URLs as cards."""

    if b"<!DOCTYPE" in content.upper():
        return SitemapParseResult(
            entries=(),
            issues=(
                ParserIssue(
                    severity="error",
                    code="unexpected_sitemap_document_type",
                    field="sitemap",
                    message="The sitemap must not contain a document type declaration.",
                ),
            ),
        )
    try:
        root = element_tree.fromstring(content)
    except element_tree.ParseError as error:
        return SitemapParseResult(
            entries=(),
            issues=(
                ParserIssue(
                    severity="error",
                    code="invalid_sitemap_xml",
                    field="sitemap",
                    message=str(error),
                ),
            ),
        )

    if _local_name(root.tag) != "urlset":
        return SitemapParseResult(
            entries=(),
            issues=(
                ParserIssue(
                    severity="error",
                    code="unexpected_sitemap_root",
                    field="sitemap",
                    message="Expected a URL-set sitemap document.",
                ),
            ),
        )

    entries: list[SitemapEntry] = []
    issues: list[ParserIssue] = []
    seen_urls: set[str] = set()
    for node in root:
        if _local_name(node.tag) != "url":
            continue
        values = {
            _local_name(child.tag): normalize_whitespace(child.text or "")
            for child in node
            if isinstance(child.tag, str)
        }
        source_url = values.get("loc")
        if not source_url:
            issues.append(
                ParserIssue(
                    severity="error",
                    code="sitemap_url_missing",
                    field="loc",
                    message="A sitemap URL entry does not contain a loc value.",
                )
            )
            continue
        try:
            normalized_url = normalize_competition_url(source_url)
        except ValueError as error:
            issues.append(
                ParserIssue(
                    severity="warning",
                    code="sitemap_url_outside_catalog",
                    field="loc",
                    message=str(error),
                )
            )
            continue
        if normalized_url in seen_urls:
            issues.append(
                ParserIssue(
                    severity="error",
                    code="duplicate_sitemap_url",
                    field="loc",
                    message=f"The sitemap repeats the normalized card URL: {normalized_url}",
                )
            )
            continue
        seen_urls.add(normalized_url)
        raw_lastmod = values.get("lastmod")
        last_modified_at = parse_sitemap_lastmod(raw_lastmod)
        if raw_lastmod and last_modified_at is None:
            issues.append(
                ParserIssue(
                    severity="warning",
                    code="invalid_sitemap_lastmod",
                    field="lastmod",
                    message=f"Cannot parse sitemap lastmod for {normalized_url}.",
                )
            )
        entries.append(
            SitemapEntry(
                url=normalized_url,
                last_modified_at=last_modified_at,
            )
        )

    if not entries and not any(issue.severity == "error" for issue in issues):
        issues.append(
            ParserIssue(
                severity="error",
                code="empty_competitions_sitemap",
                field="sitemap",
                message="The sitemap did not contain any allowed competition-card URLs.",
            )
        )
    return SitemapParseResult(entries=tuple(entries), issues=tuple(issues))


def _content_root(root: Any) -> Any:
    candidates = root.xpath("(//main | //article)[1]")
    if candidates:
        return candidates[0]
    candidates = root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' contest__info ') "
        "or @data-competition-content]"
    )
    if candidates:
        return candidates[0]
    return root


def _text_without_heading(container: Any, heading: Any) -> str:
    parts: list[str] = []
    if container.text and container.text.strip():
        parts.append(container.text)
    for child in container:
        if child is heading:
            if child.tail and child.tail.strip():
                parts.append(child.tail)
            continue
        text = _node_text(child)
        if text:
            parts.append(text)
        if child.tail and child.tail.strip():
            parts.append(child.tail)
    return normalize_whitespace(" ".join(parts))


_MAX_BLOCK_TEXT_CHARS = 10_000
_SCHEDULE_YEAR_CONTEXT_RE = re.compile(
    r"\b(?:в\s+течение|в|на)\s+(?P<year>20\d{2})\s+год(?:а|у)?\b",
    re.IGNORECASE,
)
_RESULT_YEAR_HEADING_RE = re.compile(
    r"^20\d{2}\s*(?:год(?:а)?|[/–-]\s*20\d{2})$",
    re.IGNORECASE,
)
_CYCLE_LABEL_RE = re.compile(r"^(?:[ivxlcdm]+|\d+)\s+цикл$", re.IGNORECASE)


def _section_category(title: str) -> str:
    heading = normalize_heading(title)
    if is_schedule_milestone_title(title):
        return "schedule"
    categories = (
        ("results", ("победител", "итог", "результат", "лауреат")),
        (
            "schedule",
            ("когда", "срок", "порядок", "этап", "календар", "график", "прием", "приём"),
        ),
        ("goals", ("цел", "задач", "о конкурс")),
        ("opportunities", ("возможност",)),
        ("criteria", ("критери", "оценк", "допуск")),
        ("application", ("заявк", "как участвовать", "подать")),
        ("eligibility", ("кто может", "требован", "участник", "условия участия")),
        (
            "funding",
            ("грантовый фонд", "финансирован", "фонд поддержки", "поддержк", "размер гранта"),
        ),
        ("documents", ("документ", "положени", "правил", "регламент")),
        ("taxonomy", ("направлен", "тем", "географ", "регион", "территор", "номинац")),
        ("contacts", ("контакт", "организатор")),
        ("supplementary", ("новост", "событи", "истор")),
    )
    for category, terms in categories:
        if any(term in heading for term in terms):
            return category
    return "unclassified"


def _heading_category(heading: Any, title: str) -> str:
    if _has_schedule_ancestor(heading):
        return "schedule"
    category = _section_category(title)
    if category != "unclassified":
        return category
    parent = heading.getparent()
    if parent is None:
        return category
    has_contact_link = bool(
        parent.xpath(".//a[starts-with(@href, 'mailto:') or starts-with(@href, 'tel:')]")
    )
    return "contacts" if has_contact_link else category


def _has_schedule_ancestor(node: Any) -> bool:
    current = node
    while current is not None:
        classes = current.get("class", "") if hasattr(current, "get") else ""
        if "schedule" in classes.casefold().split():
            return True
        if "schedule" in classes.casefold():
            return True
        current = current.getparent() if hasattr(current, "getparent") else None
    return False


_CATALOG_TAIL_HEADINGS = {
    "новости",
    "события",
    "истории",
    "похожие материалы",
}


def _is_catalog_tail_heading(title: str) -> bool:
    return normalize_heading(title) in _CATALOG_TAIL_HEADINGS


def _bounded_text(value: str) -> tuple[str, bool]:
    normalized = normalize_whitespace(value)
    if len(normalized) <= _MAX_BLOCK_TEXT_CHARS:
        return normalized, False
    return normalized[:_MAX_BLOCK_TEXT_CHARS].rstrip(), True


def _link_kind(*, link: str, label: str, section_category: str) -> str:
    text = label.lower()
    path = urlsplit(link).path.lower()
    if is_social_resource_url(link):
        return "reference"
    if (
        re.search(r"подать\s+заяв|заполнить\s+заяв|перейти\s+к\s+заяв", text)
        or re.search(r"личн\w*\s+кабинет", text)
        or urlsplit(link).hostname == "zayavka.fondpotanin.ru"
    ):
        return "application"
    if section_category == "results" or is_winner_resource(
        title=label,
        source_section=None,
        url=link,
    ):
        return "result"
    if (
        re.search(r"\.(?:pdf|docx?|xlsx?|pptx?)(?:$|[?#])", link, re.IGNORECASE)
        or path.startswith("/upload/")
        or re.search(r"положени|правил|регламент|документ|бюджет", text)
        or section_category == "documents"
    ):
        return "document"
    if "подроб" in text or "услов" in text or path.startswith("/competitions/"):
        return "detail"
    return "reference"


def _collection_policy(link: str, kind: str) -> tuple[str, str | None]:
    parsed = urlsplit(link)
    if kind == "application":
        return "reference_only", "application_form_not_collected"
    if parsed.hostname != POTANIN_HOST:
        return "reference_only", "outside_official_origin"
    if parsed.path.startswith("/upload/") and kind in {"document", "result"}:
        return "fetch", None
    if parsed.path.startswith("/press/") and kind == "result":
        return "fetch", None
    if parsed.path.startswith("/press/"):
        return "reference_only", "not_result_material"
    return "reference_only", "outside_bounded_artifact_paths"


def _links_in_node(
    node: Any,
    *,
    source_url: str,
    section_title: str | None,
    section_category: str,
    result_year: str | None = None,
) -> list[dict[str, object]]:
    links: list[dict[str, object]] = []
    anchors = list(node.xpath(".//a[@href]"))
    if _tag_name(node) == "a" and node.get("href"):
        anchors.insert(0, node)
    for anchor in anchors:
        href = anchor.get("href")
        if not href:
            continue
        link = _absolute_safe_url(source_url, href)
        if link is None or link == source_url:
            continue
        label = _node_text(anchor)
        kind = _link_kind(link=link, label=label, section_category=section_category)
        collection, reason = _collection_policy(link, kind)
        link_section_title = section_title
        if section_category == "results" and section_title and result_year:
            link_section_title = f"{section_title} · {result_year}"
        entry: dict[str, object] = {
            "url": link,
            "label": label,
            "kind": kind,
            "section_title": link_section_title,
            "section_category": section_category,
            "collection": collection,
        }
        if reason is not None:
            entry["collection_reason"] = reason
        existing = next((candidate for candidate in links if candidate["url"] == link), None)
        if existing is None:
            links.append(entry)
            continue
        existing_label = existing.get("label")
        if not isinstance(existing_label, str) or not label:
            continue
        combined_label = normalize_whitespace(f"{existing_label} {label}")
        if _CYCLE_LABEL_RE.fullmatch(combined_label):
            existing["label"] = combined_label
    return links


def _document_link_label(anchor: Any) -> str:
    """Use the document-card title instead of its format, date, and file-size text."""

    title_nodes = anchor.xpath(
        ".//*[contains(concat(' ', normalize-space(@class), ' '), "
        "' documents__doc-title ')]"
    )
    for title_node in title_nodes:
        if (title := _node_text(title_node)):
            return title
    return _node_text(anchor)


def _document_section_links(scope: Any, source_url: str) -> list[dict[str, object]]:
    """Extract official materials from explicit document sections only."""

    entries: list[dict[str, object]] = []
    for section in scope.xpath(".//section"):
        classes = f" {section.get('class', '')} "
        headings = section.xpath(".//h2 | .//h3 | .//h4")
        heading = headings[0] if headings else None
        section_title = _node_text(heading) if heading is not None else None
        is_document_section = (
            " documents " in classes
            or (section_title is not None and _section_category(section_title) == "documents")
        )
        if not is_document_section:
            continue
        anchors = section.xpath(
            ".//a[contains(concat(' ', normalize-space(@class), ' '), "
            "' documents__doc ') and @href]"
        )
        if not anchors:
            anchors = section.xpath(".//a[@href]")
        for anchor in anchors:
            label = _document_link_label(anchor)
            for entry in _links_in_node(
                anchor,
                source_url=source_url,
                section_title=section_title,
                section_category="documents",
            ):
                if label:
                    entry["label"] = label
                entries.append(entry)
    return entries


def _is_standalone_content_anchor(anchor: Any) -> bool:
    """Exclude links embedded in ordinary prose from the compact material inventory."""

    parent = anchor.getparent()
    if parent is None:
        return False
    return _tag_name(parent) not in {"p", "li", "span", "strong", "b", "em", "small"}


def _standalone_semantic_links(scope: Any, source_url: str) -> list[dict[str, object]]:
    """Retain direct CTAs and named files without sweeping in page navigation."""

    entries: list[dict[str, object]] = []
    for anchor in scope.xpath(".//a[@href]"):
        if not _is_standalone_content_anchor(anchor):
            continue
        for entry in _links_in_node(
            anchor,
            source_url=source_url,
            section_title=None,
            section_category="standalone",
        ):
            kind = entry.get("kind")
            label = entry.get("label")
            if kind not in {"application", "document", "result"}:
                continue
            if kind == "document" and (
                not isinstance(label, str)
                or re.search(r"(?:документ|положени|правил|регламент|форм\w*\s+заяв)", label, re.I)
                is None
            ):
                continue
            entry["section_category"] = {
                "application": "application",
                "document": "documents",
                "result": "results",
            }[kind]
            entries.append(entry)
    return entries


def _inline_section_heading(node: Any) -> str | None:
    """Read a short bold paragraph used as a section heading on legacy pages."""

    if _tag_name(node) != "p":
        return None
    emphasized = [child for child in node if _tag_name(child) in {"b", "strong"}]
    if len(emphasized) != 1:
        return None
    title = _node_text(node)
    if not title or title != _node_text(emphasized[0]):
        return None
    if len(title) > 160 or _section_category(title) == "unclassified":
        return None
    return title


def _result_year_heading(node: Any) -> str | None:
    """Read a bold year label nested inside a winner-list section."""

    if _tag_name(node) != "p":
        return None
    emphasized = [child for child in node if _tag_name(child) in {"b", "strong"}]
    if len(emphasized) != 1:
        return None
    title = _node_text(node)
    if not title or title != _node_text(emphasized[0]):
        return None
    return title if _RESULT_YEAR_HEADING_RE.fullmatch(title) is not None else None


def _content_heading_nodes(scope: Any) -> list[Any]:
    headings: list[Any] = []
    for node in scope.iter():
        if _tag_name(node) in {"h2", "h3", "h4", "h5", "h6"}:
            headings.append(node)
        elif _inline_section_heading(node) is not None:
            headings.append(node)
    return headings


def _contains_content_heading(node: Any, headings: set[Any]) -> bool:
    return any(descendant in headings for descendant in node.iter())


def _extract_content_blocks(scope: Any, source_url: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    headings = _content_heading_nodes(scope)
    heading_set = set(headings)
    for position, heading in enumerate(headings, 1):
        title = _inline_section_heading(heading) or _node_text(heading)
        if not title:
            continue
        if _is_catalog_tail_heading(title):
            break
        fragments: list[str] = []
        related_nodes: list[Any] = [heading]
        sibling = heading.getnext()
        while sibling is not None:
            if sibling in heading_set or _contains_content_heading(sibling, heading_set):
                break
            related_nodes.append(sibling)
            text = _node_text(sibling)
            if text:
                fragments.append(text)
            sibling = sibling.getnext()
        value = normalize_whitespace(" ".join(fragments))
        if not value:
            parent = heading.getparent()
            if parent is not None:
                nested_headings = parent.xpath(".//h2 | .//h3 | .//h4")
                if len(nested_headings) == 1:
                    related_nodes = [parent]
                    value = _text_without_heading(parent, heading)
        text, text_truncated = _bounded_text(value)
        category = _heading_category(heading, title)
        links: list[dict[str, object]] = []
        items: list[str] = []
        result_year: str | None = None
        for node in related_nodes:
            if category == "results":
                result_year = _result_year_heading(node) or result_year
            for link in _links_in_node(
                node,
                source_url=source_url,
                section_title=title,
                section_category=category,
                result_year=result_year,
            ):
                if link not in links:
                    links.append(link)
            list_nodes = node.xpath(".//li")
            if _tag_name(node) == "li":
                list_nodes.insert(0, node)
            for list_node in list_nodes:
                item = _node_text(list_node)
                if item and item not in items:
                    items.append(item)
        if not text and not links:
            continue
        blocks.append(
            {
                "position": position,
                "heading": title,
                "heading_key": normalize_heading(title),
                "category": category,
                "text": text or None,
                "text_truncated": text_truncated,
                "links": links,
                "items": items,
            }
        )
    return blocks


def _extract_sections(blocks: Iterable[dict[str, object]]) -> dict[str, str]:
    sections: dict[str, str] = {}
    for block in blocks:
        title = block.get("heading")
        text = block.get("text")
        if not isinstance(title, str) or not isinstance(text, str) or not text:
            continue
        sections[title] = normalize_whitespace(" ".join(filter(None, (sections.get(title), text))))
    return sections


def _is_total_fund_section(title: str) -> bool:
    heading = normalize_heading(title)
    return any(
        marker in heading
        for marker in ("грантовый фонд", "общий фонд", "фонд поддержки", "бюджет конкурса")
    )


def _per_program_funding_sections(
    blocks: Iterable[dict[str, object]],
) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    for block in blocks:
        title = block.get("heading")
        text = block.get("text")
        category = block.get("category")
        if not isinstance(title, str) or not isinstance(text, str) or not text:
            continue
        if _is_total_fund_section(title):
            continue
        has_funding_signal = bool(
            re.search(r"(?:грант\w*|поддержк\w*|финансир\w*)", text, re.IGNORECASE)
        )
        if category == "funding" or (has_funding_signal and parse_rub_amounts(text)):
            sections.append((title, text))
    return sections


def _first_summary(scope: Any) -> str | None:
    for paragraph in scope.xpath(".//p"):
        value = _node_text(paragraph)
        if len(value) >= 20:
            return value
    return None


def _summary_from_blocks(blocks: Iterable[dict[str, object]], scope: Any) -> str | None:
    for category in ("goals", "opportunities", "eligibility"):
        for block in blocks:
            if block.get("category") != category:
                continue
            value = block.get("text")
            if isinstance(value, str) and len(value) >= 20:
                return value
    return _first_summary(scope)


def _first_category_text(
    blocks: Iterable[dict[str, object]],
    category: str,
) -> str | None:
    for block in blocks:
        if block.get("category") != category:
            continue
        value = block.get("text")
        if isinstance(value, str) and value:
            return value
    return None


def _source_publication_date(root: Any) -> tuple[str | None, tuple[ParserIssue, ...]]:
    values: list[str] = []
    labels = root.xpath("//*[normalize-space()='Дата публикации']")
    for label in labels:
        sibling = label.getnext()
        if sibling is not None:
            parsed = parse_source_date(_node_text(sibling))
            if parsed is not None:
                values.append(parsed.isoformat())
    unique_values = tuple(dict.fromkeys(values))
    if len(unique_values) <= 1:
        return (unique_values[0] if unique_values else None), ()
    return (
        None,
        (
            ParserIssue(
                severity="error",
                code="source_publication_date_conflict",
                field="source_published_on",
                message="The source exposes conflicting publication dates on one card.",
            ),
        ),
    )


def _access_mode(eligibility_text: str | None) -> str:
    return infer_access_mode((eligibility_text,)).value


def _schedule_items(blocks: Iterable[dict[str, object]]) -> list[str]:
    items: list[str] = []
    for block in blocks:
        if block.get("category") != "schedule":
            continue
        raw_items = block.get("items")
        found_items = False
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, str) and item and item not in items:
                    items.append(item)
                    found_items = True
        if found_items:
            continue
        value = block.get("text")
        if isinstance(value, str) and value and value not in items:
            items.append(value)
    return items


def _schedule_year_context(blocks: Iterable[dict[str, object]]) -> tuple[int | None, str | None]:
    contexts: list[tuple[int, str]] = []
    for block in blocks:
        if block.get("category") != "schedule":
            continue
        values: list[str] = []
        text = block.get("text")
        if isinstance(text, str):
            values.append(text)
        raw_items = block.get("items")
        if isinstance(raw_items, list):
            values.extend(item for item in raw_items if isinstance(item, str))
        for value in values:
            normalized = normalize_whitespace(value)
            if "цикл" not in normalize_heading(normalized):
                continue
            for match in _SCHEDULE_YEAR_CONTEXT_RE.finditer(normalized):
                candidate = (int(match.group("year")), normalized)
                if candidate not in contexts:
                    contexts.append(candidate)
    years = tuple(dict.fromkeys(year for year, _evidence in contexts))
    if len(years) != 1:
        return None, None
    year = years[0]
    evidence = next(evidence for candidate, evidence in contexts if candidate == year)
    return year, evidence


def _contact_entries(scope: Any) -> tuple[list[dict[str, str]], tuple[ParserIssue, ...]]:
    contacts: list[dict[str, str]] = []
    issues: list[ParserIssue] = []
    contact_headings = [
        heading
        for heading in scope.xpath(".//h2 | .//h3")
        if _section_category(_node_text(heading)) == "contacts"
    ]
    for heading in contact_headings:
        container = heading.getparent()
        if container is None:
            continue
        people = container.xpath(".//h3")
        for person in people:
            name = _node_text(person)
            if not name:
                continue
            person_parent = person.getparent()
            person_container = person_parent if person_parent is not None else container
            email_links = person_container.xpath(".//a[starts-with(@href, 'mailto:')]")
            phone_links = person_container.xpath(".//a[starts-with(@href, 'tel:')]")
            role_nodes = person_container.xpath(".//p")
            role = next(
                (
                    value
                    for node in role_nodes
                    if (value := _node_text(node)) and value != name
                ),
                None,
            )
            email = (
                (email_links[0].get("href") or "").removeprefix("mailto:").strip()
                if email_links
                else None
            )
            phone = (
                (phone_links[0].get("href") or "").removeprefix("tel:").strip()
                if phone_links
                else None
            )
            evidence = _node_text(person_container)
            entry = {
                "name": name[:255],
                "evidence": evidence[:2_000],
            }
            if role:
                entry["role"] = role[:255]
            if email:
                entry["email"] = email[:320]
            if phone:
                entry["phone"] = phone[:64]
            if entry not in contacts:
                contacts.append(entry)
        section_text = _node_text(container)
        if not people and re.search(
            r"[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}|(?:\+?\d[\d()\s-]{6,}\d)",
            section_text,
            re.UNICODE,
        ):
            issues.append(
                ParserIssue(
                    severity="warning",
                    code="contacts_require_manual_review",
                    field="contacts",
                    message="A contact section was found but no structured contact card could be read.",
                )
            )
    return contacts, tuple(issues)


def _funding_amounts(
    *,
    total_fund: Any,
    per_program_funding: Any,
) -> list[dict[str, object]]:
    amounts: list[dict[str, object]] = []

    def append_observation(
        observation: Any,
        *,
        scope: str,
        fallback_label: str,
    ) -> None:
        breakdown = getattr(observation, "breakdown", ())
        entries = breakdown or (
            {
                "value": observation.funding.model_dump(mode="json", exclude_none=True),
                "evidence": " ".join(getattr(observation, "evidence", ())),
                "label": fallback_label,
            },
        )
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            if not isinstance(value, dict):
                continue
            if value.get("value_kind") == "not_stated" and not entry.get("evidence"):
                continue
            amount = {
                "scope": scope,
                "value": value,
                "label": entry.get("label") or fallback_label,
                "evidence": entry.get("evidence") or None,
            }
            if amount not in amounts:
                amounts.append(amount)

    append_observation(
        total_fund,
        scope="announced_total",
        fallback_label="Фонд конкурса",
    )
    append_observation(
        per_program_funding,
        scope="per_recipient",
        fallback_label="На одну программу или получателя",
    )
    return amounts


_STATUS_PATTERNS = (
    ("open", re.compile(r"\bоткрыт\w*\s+при[её]м\s+заяв", re.IGNORECASE)),
    ("closed", re.compile(r"\bпри[её]м\s+заяв\w*\s+(?:заверш[её]н|закрыт)", re.IGNORECASE)),
    ("completed", re.compile(r"\bзаверш[её]н\w*\b", re.IGNORECASE)),
    ("upcoming", re.compile(r"\b(?:скоро|планируется)\b", re.IGNORECASE)),
)


def _source_status(scope: Any) -> tuple[str | None, tuple[ParserIssue, ...]]:
    candidates: list[str] = []
    nodes = scope.xpath(
        ".//*[@data-status or contains(translate(@class, 'STATUS', 'status'), 'status')]"
    )
    for node in nodes:
        text = _node_text(node)
        for value, pattern in _STATUS_PATTERNS:
            if pattern.search(text):
                candidates.append(value)
                break
    unique = tuple(dict.fromkeys(candidates))
    if not unique:
        return None, ()
    if len(unique) > 1:
        return (
            None,
            (
                ParserIssue(
                    severity="error",
                    code="source_status_conflict",
                    field="source_status",
                    message="The source exposes conflicting status labels on one card.",
                ),
            ),
        )
    return unique[0], ()


def _absolute_safe_url(base_url: str, href: str) -> str | None:
    candidate = urldefrag(urljoin(base_url, href.strip()))[0]
    return normalize_outbound_url(candidate)


def _collect_links(
    scope: Any,
    blocks: Iterable[dict[str, object]],
    source_url: str,
) -> tuple[dict[str, object], list[str]]:
    links = {
        "application_candidates": [],
        "document_urls": [],
        "result_urls": [],
        "detail_urls": [],
        "inventory": [],
    }
    # Explicit document sections get first choice when the same URL is also
    # mentioned inline elsewhere on the page.
    inventory: list[dict[str, object]] = _document_section_links(scope, source_url)
    inventory.extend(_standalone_semantic_links(scope, source_url))
    for block in blocks:
        block_links = block.get("links")
        if isinstance(block_links, list):
            inventory.extend(
                item for item in block_links if isinstance(item, dict)
            )
    unique_inventory: list[dict[str, object]] = []
    entries_by_url: dict[str, dict[str, object]] = {}
    for entry in inventory:
        url = entry.get("url")
        if not isinstance(url, str):
            continue
        existing = entries_by_url.get(url)
        if existing is None:
            copied = dict(entry)
            entries_by_url[url] = copied
            unique_inventory.append(copied)
            continue
        context = {
            "section_title": entry.get("section_title"),
            "section_category": entry.get("section_category"),
        }
        contexts = existing.setdefault(
            "contexts",
            [
                {
                    "section_title": existing.get("section_title"),
                    "section_category": existing.get("section_category"),
                }
            ],
        )
        if isinstance(contexts, list) and context not in contexts:
            contexts.append(context)

    for entry in unique_inventory:
        link = entry.get("url")
        kind = entry.get("kind")
        if not isinstance(link, str) or not isinstance(kind, str):
            continue
        bucket = {
            "application": "application_candidates",
            "document": "document_urls",
            "result": "result_urls",
            "detail": "detail_urls",
        }.get(kind)
        if bucket is not None and link not in links[bucket]:
            links[bucket].append(link)
    links["inventory"] = unique_inventory

    warnings: list[str] = []
    if len(links["application_candidates"]) > 1:
        warnings.append("application_url_ambiguous")
    return links, warnings


def _relevant_section_texts(sections: dict[str, str], keywords: Iterable[str]) -> list[str]:
    values: list[str] = []
    for title, text in sections.items():
        heading = normalize_heading(title)
        if any(keyword in heading for keyword in keywords):
            values.append(text)
    return values


def _category_texts(
    blocks: Iterable[dict[str, object]],
    categories: Iterable[str],
) -> list[str]:
    allowed = set(categories)
    return [
        text
        for block in blocks
        if block.get("category") in allowed
        and isinstance((text := block.get("text")), str)
        and text
    ]


def _decode_html(content: bytes) -> str:
    """Decode the public page before parsing so UTF-8 without a meta tag stays UTF-8."""

    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("windows-1251", errors="replace")


def parse_competition_page(
    content: bytes,
    *,
    source_url: str,
    sitemap_last_modified_at: str | None,
) -> ParsedCompetitionPage:
    """Extract one review-ready candidate without guessing missing facts."""

    issues: list[ParserIssue] = []
    try:
        root = lxml_html.fromstring(_decode_html(content))
    except (etree.ParserError, ValueError, TypeError) as error:
        record = {
            "record_key": source_url,
            "title": "",
            "record_url": source_url,
            "payload": {},
            "warnings": [],
        }
        issues.append(
            ParserIssue(
                severity="error",
                code="invalid_competition_html",
                field="page",
                message=str(error),
            )
        )
        return ParsedCompetitionPage(record_payload=record, issues=tuple(issues))

    scope = _content_root(root)
    title_nodes = scope.xpath(".//h1") or root.xpath("//h1")
    source_title = _node_text(title_nodes[0]) if title_nodes else ""
    if not source_title:
        issues.append(
            ParserIssue(
                severity="error",
                code="title_missing",
                field="title",
                message="Competition page does not expose an H1 title.",
            )
        )

    main_text = _node_text(scope)
    if len(main_text) < 20:
        issues.append(
            ParserIssue(
                severity="error",
                code="unexpected_page_shape",
                field="page",
                message="Competition page does not contain a usable primary content block.",
            )
        )

    content_blocks = _extract_content_blocks(scope, source_url)
    sections = _extract_sections(content_blocks)
    competition_text = normalize_whitespace(
        " ".join(
            value
            for block in content_blocks
            if isinstance((value := block.get("text")), str)
        )
    ) or main_text
    source_status, status_issues = _source_status(scope)
    issues.extend(status_issues)
    source_published_on, source_date_issues = _source_publication_date(root)
    issues.extend(source_date_issues)
    contacts, contact_issues = _contact_entries(scope)
    issues.extend(contact_issues)

    schedule_texts = _schedule_items(content_blocks)
    if not schedule_texts:
        schedule_texts = _relevant_section_texts(
            sections,
            ("когда", "порядок", "график", "прием", "приём", "заяв"),
        )
    if not schedule_texts:
        schedule_texts.extend(
            _node_text(node)
            for node in scope.xpath(".//*[contains(@class, 'schedule')]")
            if _node_text(node)
        )
    if not schedule_texts:
        schedule_texts.append(competition_text)
    schedule_year, schedule_year_evidence = _schedule_year_context(content_blocks)
    timeline_events = extract_timeline_events(
        schedule_texts,
        fallback_year=schedule_year,
    )
    dates = extract_application_dates(timeline_events)
    if dates.error:
        issues.append(
            ParserIssue(
                severity="error",
                code=dates.error,
                field="application_dates",
                message="The source contains conflicting or invalid application date evidence.",
            )
        )

    total_fund_texts = [
        (title, text)
        for title, text in sections.items()
        if _section_category(title) == "funding"
        or "грантовый фонд" in normalize_heading(title)
    ]
    if not total_fund_texts:
        total_fund_texts = [competition_text]
    total_fund = extract_total_grant_fund(total_fund_texts)
    if total_fund.error:
        issues.append(
            ParserIssue(
                severity="error",
                code=total_fund.error,
                field="total_grant_fund",
                message="The source contains conflicting total grant fund values.",
            )
        )
    per_program_funding = extract_per_program_funding(
        _per_program_funding_sections(content_blocks) or [main_text]
    )

    theme_texts = _category_texts(
        content_blocks,
        ("taxonomy", "goals", "opportunities"),
    )
    geography_texts = _category_texts(
        content_blocks,
        ("taxonomy", "eligibility"),
    )
    links, link_warnings = _collect_links(scope, content_blocks, source_url)
    warnings = list(link_warnings)
    if dates.warning:
        warnings.append(dates.warning)
    if per_program_funding.warning:
        warnings.append(per_program_funding.warning)
    if total_fund.warning:
        warnings.append(total_fund.warning)
    unclassified_blocks = [
        block
        for block in content_blocks
        if block.get("category") == "unclassified"
        and (block.get("text") or block.get("links"))
    ]
    for block in unclassified_blocks[:20]:
        heading = block.get("heading")
        if isinstance(heading, str):
            warnings.append(f"unclassified_content_block: {heading}")

    eligibility_summary = _first_category_text(content_blocks, "eligibility")

    application_payload: dict[str, object] = {
        "start_on": dates.start_on.isoformat() if dates.start_on is not None else None,
        "end_on": dates.end_on.isoformat() if dates.end_on is not None else None,
        "url": (
            links["application_candidates"][0]
            if len(links["application_candidates"]) == 1
            else None
        ),
        "candidate_urls": links["application_candidates"],
        "date_evidence": list(dates.evidence),
    }
    if schedule_year is not None and schedule_year_evidence is not None:
        application_payload["year_context"] = {
            "year": schedule_year,
            "evidence": schedule_year_evidence,
        }

    record = {
        "record_key": source_url,
        "title": public_program_title(source_title, source_url=source_url),
        "record_url": source_url,
        "deadline_on": dates.end_on.isoformat() if dates.end_on is not None else None,
        "funding": per_program_funding.funding.model_dump(mode="json", exclude_none=True),
        "payload": {
            "source_status": source_status or "unknown",
            "source_title": source_title or None,
            "source_published_on": source_published_on,
            "source_last_modified_at": sitemap_last_modified_at,
            "application": application_payload,
            "timeline": [
                {
                    "kind": event.kind,
                    "label": event.label,
                    "start_on": event.start_on.isoformat() if event.start_on else None,
                    "end_on": event.end_on.isoformat() if event.end_on else None,
                    "evidence": event.evidence,
                }
                for event in timeline_events
                if event.start_on is not None or event.end_on is not None
            ],
            "funding": {
                "total_grant_fund": funding_payload(total_fund),
                "per_program": funding_payload(per_program_funding),
                "amounts": _funding_amounts(
                    total_fund=total_fund,
                    per_program_funding=per_program_funding,
                ),
            },
            "taxonomy": {
                "themes": normalize_themes(theme_texts),
                "geographies": normalize_geographies(geography_texts),
            },
            "summary": _summary_from_blocks(content_blocks, scope),
            "eligibility": {
                "summary": eligibility_summary,
                "geography_note": extract_geography_note(eligibility_summary),
                "access_mode": _access_mode(eligibility_summary),
            },
            "contacts": contacts,
            "sections": sections,
            "content_inventory": {
                "blocks": content_blocks,
                "unclassified_block_count": len(unclassified_blocks),
                "raw_capture_contains_full_content": True,
            },
            "links": {
                "document_urls": links["document_urls"],
                "result_urls": links["result_urls"],
                "detail_urls": links["detail_urls"],
                "inventory": links["inventory"],
            },
            "artifacts": links["inventory"],
        },
        "warnings": warnings,
    }
    return ParsedCompetitionPage(record_payload=record, issues=tuple(issues))

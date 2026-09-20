from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal
from urllib.parse import urldefrag, urljoin, urlsplit

from lxml import etree, html as lxml_html

from app.domain.models import ProgramAccessMode
from app.domain.presentation import infer_access_mode, is_winner_resource
from app.sources.adapters.potanin.normalization import TimelineEvent

from .normalization import (
    TIMCHENKO_CATALOG_SECTIONS,
    TIMCHENKO_CATALOG_STATUS,
    TIMCHENKO_HOST,
    extract_application_dates,
    extract_geography_note,
    extract_timchenko_funding,
    extract_timchenko_timeline,
    extract_top_application_periods,
    infer_year,
    normalize_competition_url,
    normalize_geographies,
    normalize_heading,
    normalize_outbound_url,
    normalize_themes,
    normalize_title,
    normalize_whitespace,
    parse_period,
    funding_payload,
    theme_from_source_category,
    timeline_kind,
)


@dataclass(frozen=True)
class ParserIssue:
    severity: Literal["warning", "error"]
    code: str
    field: str
    message: str


@dataclass(frozen=True)
class CatalogEntry:
    url: str
    source_category: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class ParsedCatalogPage:
    entries: tuple[CatalogEntry, ...]
    issues: tuple[ParserIssue, ...] = ()


@dataclass(frozen=True)
class ParsedCompetitionPage:
    record_payload: dict[str, Any]
    issues: tuple[ParserIssue, ...] = ()


_MAX_BLOCK_TEXT_CHARS = 10_000
_MAX_SECTION_COUNT = 100
_CATEGORY_NAMES = ("Забота", "Развитие", "Спецпроекты")
_CATALOG_TAIL_HEADINGS = {"другие конкурсы фонда", "похожие конкурсы"}
_SOCIAL_HOSTS = {
    "vk.com",
    "vkontakte.ru",
    "t.me",
    "telegram.me",
    "ok.ru",
    "rutube.ru",
    "youtube.com",
    "youtu.be",
}
_NON_CONTENT_DETAIL_TOKENS = (
    "cookie",
    "consent",
    "modal",
    "popup",
    "subscribe",
    "subscription",
    "newsletter",
    "navigation",
    "breadcrumbs",
    # The live template uses div.main-header and *-menu wrappers inside the
    # page's <main>, rather than semantic <header>/<nav> elements.
    "main-header",
    "menu",
    "layout__head",
)


def _timchenko_access_mode(*texts: str | None) -> str:
    """Classify Timchenko catalogue entries as open unless access is restricted.

    The Fond Timchenko catalogue contains public contests. A missing explicit
    eligibility statement must therefore not surface as an unspecified access
    mode; the only exception is source text that expressly says participation
    is by invitation.
    """

    inferred = infer_access_mode(texts)
    if inferred is ProgramAccessMode.INVITATION_ONLY:
        return inferred.value
    return ProgramAccessMode.OPEN.value


def _tag_name(node: Any) -> str:
    tag = getattr(node, "tag", "")
    return tag.lower() if isinstance(tag, str) else ""


def _node_text(node: Any) -> str:
    return normalize_whitespace(" ".join(node.itertext()))


def _decode_html(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("windows-1251", errors="replace")


def _content_root(root: Any) -> Any:
    candidates = root.xpath("(//main | //article)[1]")
    if candidates:
        scope = candidates[0]
    else:
        candidates = root.xpath(
            "//*[contains(concat(' ', normalize-space(@class), ' '), ' contest-content ') "
            "or @data-contest-content]"
        )
        scope = candidates[0] if candidates else root

    # The site places subscription success modals and consent/navigation
    # controls inside ``main`` on some pages.  Drop only well-known UI
    # containers before any text, headings, or anchors are inspected.
    ignored = [
        node
        for node in scope.xpath(".//*")
        if _is_non_content_detail_node(node)
    ]
    for node in reversed(ignored):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    return scope


def _is_non_content_detail_node(node: Any) -> bool:
    tag = _tag_name(node)
    if tag in {"nav", "footer", "header", "aside"}:
        return True
    values = " ".join(
        normalize_whitespace(node.get(attribute, "")).casefold()
        for attribute in ("class", "id", "role", "aria-label")
    )
    return any(token in values for token in _NON_CONTENT_DETAIL_TOKENS)


def _section_category(title: str) -> str:
    heading = normalize_heading(title)
    if heading in _CATALOG_TAIL_HEADINGS:
        return "catalog_tail"
    if "кто может" in heading or "участ" in heading or "требован" in heading:
        return "eligibility"
    if "мы поддерживаем" in heading or "направлен" in heading or "тем" in heading:
        return "taxonomy"
    if "о конкурсе" in heading or "цель" in heading or "задач" in heading:
        return "goals"
    if any(term in heading for term in ("этап", "старт", "окончан", "вебинар", "отбор", "объявлен")):
        return "schedule"
    if "порядок" in heading or "прием" in heading or "приём" in heading or "заяв" in heading:
        return "application"
    if "размер финансирован" in heading or "финансирован" in heading or "грант" in heading:
        return "funding"
    if "этап" in heading or "срок" in heading or "календар" in heading:
        return "schedule"
    if "географ" in heading or "территор" in heading or "регион" in heading:
        return "taxonomy"
    if "документ" in heading or "положен" in heading or "правил" in heading:
        return "documents"
    if "контакт" in heading or "организатор" in heading:
        return "contacts"
    if any(term in heading for term in ("победител", "результат", "итог")):
        return "results"
    return "unclassified"


def _bounded_text(value: str) -> tuple[str, bool]:
    normalized = normalize_whitespace(value)
    if len(normalized) <= _MAX_BLOCK_TEXT_CHARS:
        return normalized, False
    return normalized[:_MAX_BLOCK_TEXT_CHARS].rstrip(), True


def _paragraphs_from_nodes(nodes: Iterable[Any]) -> list[str]:
    """Read source paragraphs without collapsing their visual boundaries."""

    paragraphs: list[str] = []
    seen: set[Any] = set()
    for node in nodes:
        paragraph_nodes = [node] if _tag_name(node) == "p" else node.xpath(".//p")
        for paragraph in paragraph_nodes:
            if paragraph in seen:
                continue
            seen.add(paragraph)
            value = _node_text(paragraph)
            if value and value not in paragraphs:
                paragraphs.append(value)
    return paragraphs


def _contains_heading(node: Any, headings: set[Any]) -> bool:
    return any(descendant in headings for descendant in node.iter())


def _heading_nodes(scope: Any) -> list[Any]:
    return list(scope.xpath(".//h2 | .//h3 | .//h4 | .//h5 | .//h6"))


def _is_catalog_tail_heading(value: str) -> bool:
    return normalize_heading(value) in _CATALOG_TAIL_HEADINGS


def _extract_content_blocks(scope: Any, source_url: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    headings = _heading_nodes(scope)
    heading_set = set(headings)
    for position, heading in enumerate(headings[:_MAX_SECTION_COUNT], 1):
        title = _node_text(heading)
        if not title:
            continue
        if _is_catalog_tail_heading(title):
            break
        category = _section_category(title)
        related_nodes: list[Any] = [heading]
        fragments: list[str] = []
        sibling = heading.getnext()
        while sibling is not None:
            if sibling in heading_set or _contains_heading(sibling, heading_set):
                break
            related_nodes.append(sibling)
            text = _node_text(sibling)
            if text:
                fragments.append(text)
            sibling = sibling.getnext()

        value = normalize_whitespace(" ".join(fragments))
        if not value:
            parent = heading.getparent()
            if parent is not None and len(parent.xpath(".//h2 | .//h3 | .//h4 | .//h5 | .//h6")) == 1:
                related_nodes = [parent]
                value = normalize_whitespace(
                    " ".join(
                        part
                        for part in parent.itertext()
                        if normalize_whitespace(part) != normalize_whitespace(title)
                    )
                )
        text, text_truncated = _bounded_text(value)
        paragraphs = _paragraphs_from_nodes(related_nodes)
        items: list[str] = []
        links: list[dict[str, object]] = []
        for node in related_nodes:
            list_nodes = node.xpath(".//li")
            if _tag_name(node) == "li":
                list_nodes.insert(0, node)
            for list_node in list_nodes:
                item = _node_text(list_node)
                if item and item not in items:
                    items.append(item)
            anchors = list(node.xpath(".//a[@href]"))
            if _tag_name(node) == "a" and node.get("href"):
                anchors.insert(0, node)
            for anchor in anchors:
                entry = _link_entry(
                    anchor,
                    source_url=source_url,
                    section_title=title,
                    section_category=category,
                )
                if entry is not None and entry not in links:
                    links.append(entry)
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
                "paragraphs": paragraphs,
                "links": links,
                "items": items,
            }
        )
    return blocks


def _extract_sections(blocks: Iterable[dict[str, object]]) -> dict[str, str]:
    sections: dict[str, str] = {}
    for block in blocks:
        heading = block.get("heading")
        text = block.get("text")
        if not isinstance(heading, str) or not isinstance(text, str) or not text:
            continue
        previous = sections.get(heading)
        sections[heading] = normalize_whitespace(" ".join(part for part in (previous, text) if part))
    return sections


def _safe_http_url(base_url: str, href: str) -> str | None:
    if not href or href.strip().startswith("#"):
        return None
    candidate = urldefrag(urljoin(base_url, href.strip()))[0]
    return normalize_outbound_url(candidate)


def _host(value: str) -> str:
    return (urlsplit(value).hostname or "").casefold().removeprefix("www.")


def _is_social_url(value: str) -> bool:
    host = _host(value)
    return host in _SOCIAL_HOSTS or any(host.endswith(f".{item}") for item in _SOCIAL_HOSTS)


def _is_application_label(label: str) -> bool:
    return bool(
        re.search(
            r"подать\s+заяв|заявк\w*|чат[- ]бот|онлайн[- ]платформ|по\s+ссылке",
            label,
            re.IGNORECASE,
        )
    )


def _is_result_label(label: str) -> bool:
    return is_winner_resource(title=label, source_section=None) or bool(
        re.search(r"победител|результат|итог", label, re.IGNORECASE)
    )


_GENERIC_DOWNLOAD_LABELS = {"скачать", "скачать все", "download", "download all"}


def _document_label(anchor: Any, fallback: str, *, is_bundle: bool) -> str:
    """Find a document-card title when its link only says "Скачать".

    The current Timchenko template has a typo in this element's attribute
    (``lass`` rather than ``class``), so both spellings are intentional.
    """

    normalized = normalize_whitespace(fallback)
    if normalized.casefold() not in _GENERIC_DOWNLOAD_LABELS:
        return normalized
    if is_bundle:
        # The bulk-download control belongs to the whole section; looking up
        # through its ancestors could accidentally borrow the first file's
        # title and misrepresent the archive as one document.
        return "Все документы конкурса"

    for container in (anchor, *list(anchor.iterancestors())[:6]):
        title_nodes = container.xpath(
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' ui-file-download__name ') "
            "or contains(concat(' ', normalize-space(@lass), ' '), ' ui-file-download__name ')]"
        )
        for node in title_nodes:
            value = _node_text(node)
            if value:
                return value[:500]

    return "Документ конкурса"


def _link_entry(
    anchor: Any,
    *,
    source_url: str,
    section_title: str | None,
    section_category: str,
) -> dict[str, object] | None:
    href = anchor.get("href")
    if not isinstance(href, str):
        return None
    url = _safe_http_url(source_url, href)
    if url is None:
        return None
    raw_label = _node_text(anchor)
    host = _host(url)
    parsed = urlsplit(url)
    local = host == TIMCHENKO_HOST
    is_bundle = local and parsed.path.rstrip("/") == "/ajax/downloads.php"
    is_upload = local and parsed.path.startswith("/upload/")
    is_press = local and parsed.path.startswith("/press-center/")
    label = _document_label(anchor, raw_label, is_bundle=is_bundle) if (is_bundle or is_upload) else raw_label
    application = _is_application_label(raw_label) or host == "vk.me"

    # Source-owned download URLs are documents even when their anchor label
    # contains "заявка".  Classifying application links first previously
    # promoted upload instructions to public CTA candidates.
    if local and is_bundle:
        return {
            "url": url,
            "label": label,
            "kind": "document",
            "section_title": section_title,
            "section_category": "documents",
            "collection": "reference_only",
            "collection_reason": "download_bundle_not_collected",
        }
    if local and is_upload:
        result = section_category == "results" or _is_result_label(label)
        return {
            "url": url,
            "label": label,
            "kind": "result" if result else "document",
            "section_title": section_title,
            "section_category": "results" if result else "documents",
            "collection": "fetch",
        }
    if local and is_press and (section_category == "results" or _is_result_label(label)):
        return {
            "url": url,
            "label": label,
            "kind": "result",
            "section_title": section_title,
            "section_category": "results",
            "collection": "fetch",
        }
    if application:
        return {
            "url": url,
            "label": label,
            "kind": "application",
            "section_title": section_title,
            "section_category": "application",
            "collection": "reference_only",
            "collection_reason": "application_form_not_collected",
        }
    return None


def _link_inventory_key(entry: dict[str, object], url: str) -> tuple[str, ...]:
    """Use a scheme-independent identity only for application links.

    The same application is sometimes rendered as both http and https.  They
    are one CTA candidate, while document and result URLs retain their exact
    transport identity for provenance and fetching safety.
    """

    if entry.get("kind") != "application":
        return ("url", url)
    parsed = urlsplit(url)
    return (
        "application",
        parsed.netloc.casefold(),
        parsed.path or "/",
        parsed.query,
    )


def _prefer_secure_application_url(existing: dict[str, object], incoming_url: str) -> None:
    current_url = existing.get("url")
    if not isinstance(current_url, str) or existing.get("kind") != "application":
        return
    if urlsplit(current_url).scheme.casefold() == "http" and urlsplit(incoming_url).scheme.casefold() == "https":
        existing["url"] = incoming_url


def _deduplicate_link_inventory(
    blocks: Iterable[dict[str, object]],
    scope: Any,
    *,
    source_url: str,
) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    by_key: dict[tuple[str, ...], dict[str, object]] = {}

    def add_entry(raw_entry: dict[str, object]) -> None:
        url = raw_entry.get("url")
        if not isinstance(url, str):
            return
        key = _link_inventory_key(raw_entry, url)
        existing = by_key.get(key)
        if existing is None:
            existing = dict(raw_entry)
            by_key[key] = existing
            inventory.append(existing)
            return
        _prefer_secure_application_url(existing, url)
        context = {
            "section_title": raw_entry.get("section_title"),
            "section_category": raw_entry.get("section_category"),
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

    for block in blocks:
        raw_links = block.get("links")
        if not isinstance(raw_links, list):
            continue
        for raw_entry in raw_links:
            if isinstance(raw_entry, dict):
                add_entry(raw_entry)

    # Standalone CTA/document anchors can sit between the intro and the first
    # heading, so inspect them separately.  The classifier rejects navigation,
    # social, mailto, tel, and unrelated external links.
    for anchor in scope.xpath(".//a[@href]"):
        if _is_in_ignored_detail_block(anchor):
            continue
        entry = _link_entry(
            anchor,
            source_url=source_url,
            section_title=None,
            section_category="standalone",
        )
        if entry is not None:
            add_entry(entry)
    return inventory


def _is_in_ignored_detail_block(anchor: Any) -> bool:
    current = anchor.getparent()
    while current is not None:
        if _is_non_content_detail_node(current):
            return True
        classes = normalize_whitespace(current.get("class", "")).casefold()
        element_id = normalize_whitespace(current.get("id", "")).casefold()
        if any(term in classes or term in element_id for term in ("other-contests", "recommend", "similar")):
            return True
        # Only inspect headings directly owned by this local block.  Looking
        # at the full text of ``main``/``article`` would see a later
        # "Другие конкурсы Фонда" section and incorrectly hide an earlier
        # standalone application CTA.
        if _tag_name(current) not in {"main", "article", "body", "html"}:
            direct_headings = current.xpath("./h1 | ./h2 | ./h3 | ./h4 | ./h5 | ./h6")
            if any(_is_catalog_tail_heading(_node_text(heading)) for heading in direct_headings):
                return True
        current = current.getparent()
    return False


def _link_buckets(inventory: Iterable[dict[str, object]]) -> dict[str, list[str] | list[dict[str, object]]]:
    result: dict[str, list[str] | list[dict[str, object]]] = {
        "application_candidates": [],
        "document_urls": [],
        "result_urls": [],
        "detail_urls": [],
        "inventory": [],
    }
    for entry in inventory:
        url = entry.get("url")
        kind = entry.get("kind")
        if not isinstance(url, str) or not isinstance(kind, str):
            continue
        bucket = {
            "application": "application_candidates",
            "document": "document_urls",
            "result": "result_urls",
            "detail": "detail_urls",
        }.get(kind)
        if bucket is not None and url not in result[bucket]:  # type: ignore[operator]
            result[bucket].append(url)  # type: ignore[union-attr]
        result["inventory"].append(entry)  # type: ignore[union-attr]
    return result


def _source_category(root: Any, source_title: str, fallback: str | None) -> str | None:
    if fallback:
        return normalize_whitespace(fallback)
    for node in root.xpath("//*[@data-category or @data-direction or @data-contest-category]"):
        for attribute in ("data-category", "data-direction", "data-contest-category"):
            value = node.get(attribute)
            if isinstance(value, str) and normalize_whitespace(value):
                return normalize_whitespace(value)
    text = _node_text(root)
    for category in _CATEGORY_NAMES:
        if re.search(rf"\b{re.escape(category)}\b", text, re.IGNORECASE):
            return category
    title_match = re.search(r"\b(Забота|Развитие|Спецпроекты)\b", source_title, re.IGNORECASE)
    return title_match.group(1) if title_match else None


def _extract_summary(blocks: Iterable[dict[str, object]], scope: Any) -> str | None:
    for wanted in ("goals", "eligibility", "unclassified"):
        for block in blocks:
            if block.get("category") != wanted:
                continue
            raw_paragraphs = block.get("paragraphs")
            if isinstance(raw_paragraphs, list):
                paragraphs = [item for item in raw_paragraphs if isinstance(item, str) and item]
                value = "\n\n".join(paragraphs)
                if len(value) >= 20:
                    return value
            value = block.get("text")
            if isinstance(value, str) and len(value) >= 20:
                return value
    for paragraph in scope.xpath(".//p"):
        value = _node_text(paragraph)
        if len(value) >= 20:
            return value
    return None


def _structured_stage_timeline(scope: Any, *, fallback_year: int | None) -> tuple[TimelineEvent, ...]:
    """Read Timchenko's dedicated stage widgets before text fallbacks.

    Each widget has a reader-facing date and a title in separate elements.
    Treating the whole widget as text loses the title during date extraction.
    """

    events: list[TimelineEvent] = []
    seen: set[tuple[str, str, object, object]] = set()
    stages = scope.xpath(
        ".//*[contains(concat(' ', normalize-space(@class), ' '), ' competition-stage ')]"
    )
    for stage in stages:
        date_nodes = stage.xpath(
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' event-date-display ')]"
        )
        title_nodes = stage.xpath(".//h3 | .//h4 | .//h5")
        date_label = _node_text(date_nodes[0]) if date_nodes else ""
        label = _node_text(title_nodes[0]) if title_nodes else ""
        if not date_label or not label:
            continue

        kind = timeline_kind(label)
        start_on, end_on = parse_period(date_label, fallback_year=fallback_year)
        # A single date in the shared parser is an end date by default. On
        # this page, the title makes an opening milestone unambiguous.
        if kind == "application_open" and start_on is None and end_on is not None:
            start_on, end_on = end_on, None
        elif kind not in {"application_close", "application"} and start_on is None and end_on is not None:
            start_on, end_on = end_on, None

        key = (label.casefold(), date_label.casefold(), start_on, end_on)
        if key in seen:
            continue
        seen.add(key)
        events.append(
            TimelineEvent(
                label=label[:500],
                kind=kind,
                start_on=start_on,
                end_on=end_on,
                evidence=f"{date_label} — {label}"[:2_000],
                date_label=date_label[:500],
            )
        )
    return tuple(events)


def _first_category_text(blocks: Iterable[dict[str, object]], category: str) -> str | None:
    for block in blocks:
        if block.get("category") != category:
            continue
        text = block.get("text")
        if isinstance(text, str) and text:
            return text
    return None


def _schedule_texts(blocks: Iterable[dict[str, object]]) -> list[str]:
    values: list[str] = []
    for block in blocks:
        if block.get("category") != "schedule":
            continue
        raw_items = block.get("items")
        if isinstance(raw_items, list) and raw_items:
            values.extend(item for item in raw_items if isinstance(item, str) and item)
            continue
        text = block.get("text")
        if isinstance(text, str) and text:
            values.append(text)
    return list(dict.fromkeys(values))


def _top_block_text(scope: Any, first_heading: Any | None) -> str:
    if first_heading is None:
        return _node_text(scope)
    fragments: list[str] = []
    for node in scope.iter():
        if node is first_heading:
            break
        if node.text and normalize_whitespace(node.text):
            fragments.append(node.text)
        if node.tail and normalize_whitespace(node.tail):
            fragments.append(node.tail)
    return normalize_whitespace(" ".join(fragments))


def _contact_entries(scope: Any, blocks: Iterable[dict[str, object]]) -> tuple[list[dict[str, str]], tuple[ParserIssue, ...]]:
    contacts: list[dict[str, str]] = []
    issues: list[ParserIssue] = []
    contact_headings = [
        heading
        for heading in scope.xpath(".//h2 | .//h3 | .//h4")
        if _section_category(_node_text(heading)) == "contacts"
    ]
    email_re = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}", re.UNICODE)
    phone_re = re.compile(r"(?:\+?\d[\d()\s-]{6,}\d)")
    for heading in contact_headings:
        parent = heading.getparent()
        if parent is None:
            continue
        people = parent.xpath(".//h3 | .//h4")
        for person in people:
            name = _node_text(person)
            if not name or _section_category(name) == "contacts":
                continue
            person_parent = person.getparent()
            container = person_parent if person_parent is not None else parent
            evidence = _node_text(container)
            emails = email_re.findall(evidence)
            phones = phone_re.findall(evidence)
            role = None
            role_nodes = container.xpath(".//p | .//div")
            for role_node in role_nodes:
                candidate = _node_text(role_node)
                if not candidate or candidate == name or email_re.search(candidate) or phone_re.search(candidate):
                    continue
                if len(candidate) <= 255:
                    role = candidate
                    break
            entry: dict[str, str] = {"name": name[:255], "evidence": evidence[:2_000]}
            if role:
                entry["role"] = role
            if emails:
                entry["email"] = emails[0][:320]
            if phones:
                entry["phone"] = normalize_whitespace(phones[0])[:64]
            if entry not in contacts:
                contacts.append(entry)
        section_text = _node_text(parent)
        if not people and (email_re.search(section_text) or phone_re.search(section_text)):
            issues.append(
                ParserIssue(
                    severity="warning",
                    code="contacts_require_manual_review",
                    field="contacts",
                    message="A contact section was found but no structured contact card could be read.",
                )
            )
    return contacts, tuple(issues)


def _merge_top_and_timeline_dates(
    *,
    top_periods: tuple[tuple[Any, Any, str], ...],
    timeline: tuple[TimelineEvent, ...],
    issues: list[ParserIssue],
) -> tuple[Any, Any, tuple[str, ...]]:
    top_ranges = tuple(dict.fromkeys((start, end) for start, end, _evidence in top_periods))
    timeline_dates = extract_application_dates(timeline)

    # The compact block above the content is called "Приём заявок" by the
    # template, but on a number of real cards its period covers the wider
    # campaign (including selection/results), not the actual form window.
    # A named start/end stage is more precise source evidence, so retain both
    # pieces of evidence for review and use those stages for canonical dates.
    if len(top_ranges) > 1:
        issues.append(
            ParserIssue(
                severity="warning",
                code="application_period_conflict",
                field="application_dates",
                message=(
                    "The top application block contains multiple date periods; "
                    "explicit application stages are used when available."
                ),
            )
        )
        if not timeline_dates.error:
            return (
                timeline_dates.start_on,
                timeline_dates.end_on,
                timeline_dates.evidence,
            )
        return None, None, tuple(evidence for _start, _end, evidence in top_periods)

    if top_ranges:
        start_on, end_on = top_ranges[0]
        if timeline_dates.error:
            issues.append(
                ParserIssue(
                    severity="warning",
                    code=timeline_dates.error,
                    field="application_dates",
                    message=(
                        "The dated timeline has multiple or invalid application windows; "
                        "the top application period is retained for review."
                    ),
                )
            )
            return start_on, end_on, tuple(evidence for _start, _end, evidence in top_periods)
        if (
            timeline_dates.start_on is not None
            and start_on is not None
            and timeline_dates.start_on != start_on
        ) or (
            timeline_dates.end_on is not None
            and end_on is not None
            and timeline_dates.end_on != end_on
        ):
            issues.append(
                ParserIssue(
                    severity="warning",
                    code="application_period_conflict",
                    field="application_dates",
                    message=(
                        "The top campaign period conflicts with explicit application stages; "
                        "the stage dates take precedence."
                    ),
                )
            )
            return (
                timeline_dates.start_on or start_on,
                timeline_dates.end_on or end_on,
                tuple(
                    dict.fromkeys(
                        (*timeline_dates.evidence, *(evidence for _start, _end, evidence in top_periods))
                    )
                ),
            )
        return start_on, end_on, tuple(evidence for _start, _end, evidence in top_periods)

    if timeline_dates.error:
        issues.append(
            ParserIssue(
                severity="warning",
                code=timeline_dates.error,
                field="application_dates",
                message=(
                    "The source contains multiple or invalid application windows; "
                    "no canonical application period was chosen."
                ),
            )
        )
    return timeline_dates.start_on, timeline_dates.end_on, timeline_dates.evidence


def _catalog_category(card: Any) -> str | None:
    for attribute in ("data-category", "data-direction", "data-contest-category"):
        value = card.get(attribute)
        if isinstance(value, str) and normalize_whitespace(value):
            return normalize_whitespace(value)
    text = _node_text(card)
    for category in _CATEGORY_NAMES:
        if re.search(rf"\b{re.escape(category)}\b", text, re.IGNORECASE):
            return category
    return None


def _has_pagination(container: Any) -> bool:
    if container.xpath(
        ".//*[contains(concat(' ', normalize-space(@class), ' '), ' pagination ') "
        "or contains(concat(' ', normalize-space(@class), ' '), ' pager ') "
        "or contains(translate(@aria-label, 'PAGINATION', 'pagination'), 'pagination') "
        "or @data-pagination or @data-load-more]"
    ):
        return True
    for anchor in container.xpath(".//a[@href]"):
        href = anchor.get("href") or ""
        label = _node_text(anchor)
        if re.search(r"(?:[?&](?:page|p)=|/page/)", href, re.IGNORECASE):
            return True
        if re.search(r"следующ|загрузить\s+ещ|показать\s+ещ", label, re.IGNORECASE):
            return True
    return False


def _is_excluded_catalog_card(anchor: Any, container: Any) -> bool:
    """Exclude nested recommendation blocks even when a template nests them."""

    current = anchor.getparent()
    while current is not None and current is not container:
        classes = normalize_whitespace(current.get("class", "")).casefold()
        element_id = normalize_whitespace(current.get("id", "")).casefold()
        if any(term in classes or term in element_id for term in ("other", "recommend", "similar", "footer", "menu")):
            return True
        # Keep this local to the recommendation block.  Inspecting all text
        # on a shared card-list wrapper would hide valid cards merely because
        # a later sibling contains the "Другие конкурсы Фонда" heading.
        direct_headings = current.xpath("./h1 | ./h2 | ./h3 | ./h4 | ./h5 | ./h6")
        if any(_is_catalog_tail_heading(_node_text(heading)) for heading in direct_headings):
            return True
        current = current.getparent()
    return False


def parse_catalog_page(
    content: bytes,
    *,
    source_url: str,
    catalog_section: str,
) -> ParsedCatalogPage:
    issues: list[ParserIssue] = []
    if catalog_section not in TIMCHENKO_CATALOG_SECTIONS:
        raise ValueError(f"unknown Timchenko catalog section: {catalog_section}")
    try:
        root = lxml_html.fromstring(_decode_html(content))
    except (etree.ParserError, ValueError, TypeError) as error:
        return ParsedCatalogPage(
            entries=(),
            issues=(
                ParserIssue(
                    severity="error",
                    code="invalid_catalog_html",
                    field="catalog",
                    message=str(error),
                ),
            ),
        )

    containers = (
        [root]
        if root.get("id") == catalog_section
        else root.xpath(f"//*[@id='{catalog_section}']")
    )
    if not containers:
        return ParsedCatalogPage(
            entries=(),
            issues=(
                ParserIssue(
                    severity="error",
                    code="catalog_shape_changed",
                    field="catalog",
                    message=f"Expected the #{catalog_section} catalog container.",
                ),
            ),
        )
    container = containers[0]
    if _has_pagination(container):
        issues.append(
            ParserIssue(
                severity="error",
                code="catalog_pagination_detected",
                field="catalog",
                message="Catalog pagination was detected; completeness cannot be claimed safely.",
            )
        )

    anchors = container.xpath(
        ".//a[contains(concat(' ', normalize-space(@class), ' '), ' preview-card ') "
        "and contains(concat(' ', normalize-space(@class), ' '), ' competition-preview ')][@href]"
    )
    if not anchors:
        issues.append(
            ParserIssue(
                severity="error",
                code="catalog_shape_changed",
                field="cards",
                message="The catalog container did not contain competition preview cards.",
            )
        )

    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for anchor in anchors:
        if _is_excluded_catalog_card(anchor, container):
            continue
        href = anchor.get("href")
        candidate = normalize_outbound_url(urljoin(source_url, href.strip())) if isinstance(href, str) else None
        if candidate is None:
            issues.append(
                ParserIssue(
                    severity="error",
                    code="invalid_card_url",
                    field="card_url",
                    message="A competition preview card did not contain a usable HTTP(S) URL.",
                )
            )
            continue
        try:
            normalized = normalize_competition_url(candidate)
        except ValueError as error:
            issues.append(
                ParserIssue(
                    severity="error",
                    code="invalid_card_url",
                    field="card_url",
                    message=str(error),
                )
            )
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        entries.append(
            CatalogEntry(
                url=normalized,
                source_category=_catalog_category(anchor),
                label=_node_text(anchor) or None,
            )
        )
    return ParsedCatalogPage(entries=tuple(entries), issues=tuple(issues))


def parse_competition_page(
    content: bytes,
    *,
    source_url: str,
    source_status: str | None = None,
    catalog_section: str | None = None,
    source_category: str | None = None,
    source_last_modified_at: str | None = None,
) -> ParsedCompetitionPage:
    """Parse one Timchenko detail page into the existing import bridge shape."""

    issues: list[ParserIssue] = []
    try:
        normalized_url = normalize_competition_url(source_url)
    except ValueError:
        normalized_url = source_url
    try:
        root = lxml_html.fromstring(_decode_html(content))
    except (etree.ParserError, ValueError, TypeError) as error:
        return ParsedCompetitionPage(
            record_payload={
                "record_key": normalized_url,
                "title": "",
                "record_url": normalized_url,
                "payload": {},
                "warnings": [],
            },
            issues=(
                ParserIssue(
                    severity="error",
                    code="invalid_competition_html",
                    field="page",
                    message=str(error),
                ),
            ),
        )

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

    blocks = _extract_content_blocks(scope, normalized_url)
    sections = _extract_sections(blocks)
    first_heading = _heading_nodes(scope)[0] if _heading_nodes(scope) else None
    top_text = _top_block_text(scope, first_heading)
    competition_text = normalize_whitespace(
        " ".join(
            value
            for block in blocks
            if isinstance((value := block.get("text")), str)
        )
    ) or main_text

    resolved_status = source_status
    if resolved_status is None:
        if re.search(r"при[её]м\s+заяв\w*\s+(?:заверш[её]н|закрыт)", main_text, re.I):
            resolved_status = "closed"
        elif re.search(r"(?:открыт|ид[её]т)\s+при[её]м\s+заяв", main_text, re.I):
            resolved_status = "open"
    resolved_section = catalog_section if catalog_section in TIMCHENKO_CATALOG_SECTIONS else None
    resolved_category = _source_category(root, source_title, source_category)

    schedule_texts = _schedule_texts(blocks)
    year = infer_year(source_title, top_text, " ".join(schedule_texts))
    top_periods = extract_top_application_periods((top_text,), fallback_year=year)
    timeline = _structured_stage_timeline(scope, fallback_year=year)
    if not timeline:
        timeline = extract_timchenko_timeline(schedule_texts, fallback_year=year)
    start_on, end_on, date_evidence = _merge_top_and_timeline_dates(
        top_periods=top_periods,
        timeline=timeline,
        issues=issues,
    )
    if any(start is None and end is None for start, end, _evidence in top_periods):
        issues.append(
            ParserIssue(
                severity="error",
                code="application_period_year_missing",
                field="application_dates",
                message="Application dates are present but their year cannot be inferred safely.",
            )
        )

    funding_inputs: list[str | tuple[str, str]] = []
    if top_text:
        funding_inputs.append(top_text)
    funding_inputs.extend(
        (title, text)
        for title, text in sections.items()
        if _section_category(title) == "funding"
    )
    funding = extract_timchenko_funding(funding_inputs or [competition_text])
    warnings: list[str] = []
    if funding.warning:
        warnings.append(funding.warning)
    if funding.error:
        issues.append(
            ParserIssue(
                severity="error",
                code=funding.error,
                field="funding",
                message="The source contains conflicting funding evidence.",
            )
        )

    inventory = _deduplicate_link_inventory(blocks, scope, source_url=normalized_url)
    buckets = _link_buckets(inventory)
    application_candidates = buckets["application_candidates"]
    document_urls = buckets["document_urls"]
    result_urls = buckets["result_urls"]
    if len(application_candidates) > 1:  # type: ignore[arg-type]
        warnings.append("application_url_ambiguous")

    eligibility_summary = _first_category_text(blocks, "eligibility")
    theme_texts = [
        text
        for block in blocks
        if block.get("category") == "taxonomy"
        and isinstance((text := block.get("text")), str)
        and "географ" not in normalize_heading(str(block.get("heading", "")))
    ]
    geography_texts = [
        text
        for block in blocks
        if block.get("category") == "taxonomy"
        and "географ" in normalize_heading(str(block.get("heading", "")))
        and isinstance((text := block.get("text")), str)
    ]
    geography_text = normalize_whitespace(" ".join(geography_texts)) or None
    themes = normalize_themes(theme_texts)
    source_category_theme = theme_from_source_category(resolved_category)
    if source_category_theme is not None:
        themes = [source_category_theme, *themes]
    contacts, contact_issues = _contact_entries(scope, blocks)
    issues.extend(contact_issues)
    unclassified_blocks = [
        block
        for block in blocks
        if block.get("category") == "unclassified"
        and (block.get("text") or block.get("links"))
    ]
    for block in unclassified_blocks[:20]:
        heading = block.get("heading")
        if isinstance(heading, str):
            warnings.append(f"unclassified_content_block: {heading}")

    application_url = application_candidates[0] if len(application_candidates) == 1 else None  # type: ignore[index]
    timeline_payload = [
        {
            "kind": event.kind,
            "label": event.label,
            "start_on": event.start_on.isoformat() if event.start_on else None,
            "end_on": event.end_on.isoformat() if event.end_on else None,
            "evidence": event.evidence,
            "date_label": event.date_label,
        }
        for event in timeline
        if event.start_on is not None or event.end_on is not None or event.date_label is not None
    ]
    application_payload: dict[str, object] = {
        "start_on": start_on.isoformat() if start_on is not None else None,
        "end_on": end_on.isoformat() if end_on is not None else None,
        "url": application_url,
        "candidate_urls": list(application_candidates),  # type: ignore[arg-type]
        "date_evidence": list(date_evidence),
    }
    if year is not None:
        application_payload["year_context"] = {"year": year, "evidence": source_title or top_text}

    links_payload = {
        "document_urls": list(document_urls),  # type: ignore[arg-type]
        "result_urls": list(result_urls),  # type: ignore[arg-type]
        "detail_urls": list(buckets["detail_urls"]),  # type: ignore[arg-type]
        "inventory": inventory,
    }
    payload = {
        "source_status": resolved_status or "unknown",
        "source_title": source_title or None,
        "catalog_section": resolved_section,
        "source_category": resolved_category,
        "source_last_modified_at": source_last_modified_at,
        "application": application_payload,
        "timeline": timeline_payload,
        "funding": {
            "total_grant_fund": funding_payload(funding.total_grant_fund),
            "per_program": funding_payload(funding.per_program),
            "amounts": list(funding.amounts),
        },
        "taxonomy": {
            "themes": themes,
            "geographies": normalize_geographies(geography_texts),
        },
        "summary": _extract_summary(blocks, scope),
        "eligibility": {
            "summary": eligibility_summary,
            "geography_note": extract_geography_note(geography_text),
            "access_mode": _timchenko_access_mode(
                source_title,
                eligibility_summary,
                competition_text,
            ),
        },
        "contacts": contacts,
        "sections": sections,
        "content_inventory": {
            "blocks": blocks,
            "unclassified_block_count": len(unclassified_blocks),
            "raw_capture_contains_full_content": True,
        },
        "links": links_payload,
        "artifacts": inventory,
    }
    record = {
        "record_key": normalized_url,
        "title": normalize_title(source_title),
        "record_url": normalized_url,
        "deadline_on": end_on.isoformat() if end_on is not None else None,
        "funding": funding.record_funding.model_dump(mode="json", exclude_none=True),
        "payload": payload,
        "warnings": list(dict.fromkeys(warnings)),
    }
    return ParsedCompetitionPage(record_payload=record, issues=tuple(issues))

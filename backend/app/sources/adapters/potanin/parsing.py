from __future__ import annotations

import re
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass
from typing import Any, Iterable, Literal
from urllib.parse import urldefrag, urljoin, urlsplit

from lxml import etree, html as lxml_html

from app.sources.adapters.potanin.normalization import (
    POTANIN_HOST,
    extract_application_dates,
    extract_per_program_funding,
    extract_total_grant_fund,
    funding_payload,
    normalize_competition_url,
    normalize_geographies,
    normalize_heading,
    normalize_outbound_url,
    normalize_themes,
    normalize_whitespace,
    parse_rub_amounts,
    parse_sitemap_lastmod,
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
    candidates = root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' contest__info ') "
        "or @data-competition-content]"
    )
    if candidates:
        return candidates[0]
    candidates = root.xpath("(//main | //article)[1]")
    return candidates[0] if candidates else root


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


def _section_category(title: str) -> str:
    heading = normalize_heading(title)
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
        ("funding", ("грантовый фонд", "финансирован", "поддержк", "размер гранта")),
        ("documents", ("документ", "положени", "правил", "регламент")),
        ("taxonomy", ("направлен", "тем", "географ", "регион", "территор", "номинац")),
        ("contacts", ("контакт", "организатор")),
        ("supplementary", ("новост", "событи", "истор")),
    )
    for category, terms in categories:
        if any(term in heading for term in terms):
            return category
    return "unclassified"


def _bounded_text(value: str) -> tuple[str, bool]:
    normalized = normalize_whitespace(value)
    if len(normalized) <= _MAX_BLOCK_TEXT_CHARS:
        return normalized, False
    return normalized[:_MAX_BLOCK_TEXT_CHARS].rstrip(), True


def _link_kind(*, link: str, label: str, section_category: str) -> str:
    text = label.lower()
    path = urlsplit(link).path.lower()
    if (
        re.search(r"подать\s+заяв|заполнить\s+заяв|перейти\s+к\s+заяв", text)
        or re.search(r"личн\w*\s+кабинет", text)
        or urlsplit(link).hostname == "zayavka.fondpotanin.ru"
    ):
        return "application"
    if section_category == "results" or re.search(
        r"победител|итог|результат|лауреат", text
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
        entry: dict[str, object] = {
            "url": link,
            "label": label,
            "kind": kind,
            "section_title": section_title,
            "section_category": section_category,
            "collection": collection,
        }
        if reason is not None:
            entry["collection_reason"] = reason
        if entry not in links:
            links.append(entry)
    return links


def _extract_content_blocks(scope: Any, source_url: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    headings = scope.xpath(".//h2 | .//h3 | .//h4")
    for position, heading in enumerate(headings, 1):
        title = _node_text(heading)
        if not title:
            continue
        fragments: list[str] = []
        related_nodes: list[Any] = [heading]
        sibling = heading.getnext()
        while sibling is not None:
            if _tag_name(sibling) in {"h2", "h3", "h4"}:
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
        category = _section_category(title)
        links: list[dict[str, object]] = []
        for node in related_nodes:
            for link in _links_in_node(
                node,
                source_url=source_url,
                section_title=title,
                section_category=category,
            ):
                if link not in links:
                    links.append(link)
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
    return "грантовый фонд" in heading or "общий фонд" in heading


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
    inventory: list[dict[str, object]] = []
    for block in blocks:
        block_links = block.get("links")
        if isinstance(block_links, list):
            inventory.extend(
                item for item in block_links if isinstance(item, dict)
            )
    inventory.extend(
        _links_in_node(
            scope,
            source_url=source_url,
            section_title=None,
            section_category="page",
        )
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
    title = _node_text(title_nodes[0]) if title_nodes else ""
    if not title:
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
    source_status, status_issues = _source_status(scope)
    issues.extend(status_issues)

    schedule_texts = _relevant_section_texts(
        sections,
        ("когда", "порядок", "график", "прием", "приём", "заяв"),
    )
    schedule_texts.extend(
        _node_text(node)
        for node in scope.xpath(".//*[contains(@class, 'schedule')]")
        if _node_text(node)
    )
    if not schedule_texts:
        schedule_texts.append(main_text)
    dates = extract_application_dates(schedule_texts)
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
        total_fund_texts = [main_text]
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

    taxonomy_texts = _relevant_section_texts(
        sections,
        ("направлен", "тем", "географ", "регион", "территор"),
    )
    if not taxonomy_texts:
        taxonomy_texts = [main_text]
    links, link_warnings = _collect_links(scope, content_blocks, source_url)
    warnings = list(link_warnings)
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

    record = {
        "record_key": source_url,
        "title": title,
        "record_url": source_url,
        "deadline_on": dates.end_on.isoformat() if dates.end_on is not None else None,
        "funding": per_program_funding.funding.model_dump(mode="json", exclude_none=True),
        "payload": {
            "source_status": source_status or "unknown",
            "source_last_modified_at": sitemap_last_modified_at,
            "application": {
                "start_on": dates.start_on.isoformat() if dates.start_on is not None else None,
                "end_on": dates.end_on.isoformat() if dates.end_on is not None else None,
                "url": (
                    links["application_candidates"][0]
                    if len(links["application_candidates"]) == 1
                    else None
                ),
                "candidate_urls": links["application_candidates"],
                "date_evidence": list(dates.evidence),
            },
            "funding": {
                "total_grant_fund": funding_payload(total_fund),
                "per_program": funding_payload(per_program_funding),
            },
            "taxonomy": {
                "themes": normalize_themes(taxonomy_texts),
                "geographies": normalize_geographies(taxonomy_texts),
            },
            "summary": _first_summary(scope),
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

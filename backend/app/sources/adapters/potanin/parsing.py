from __future__ import annotations

import re
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass
from typing import Any, Iterable, Literal
from urllib.parse import urldefrag, urljoin, urlsplit

from lxml import etree, html as lxml_html

from app.sources.adapters.potanin.normalization import (
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


def _extract_sections(scope: Any) -> dict[str, str]:
    sections: dict[str, str] = {}
    for heading in scope.xpath(".//h2 | .//h3"):
        title = _node_text(heading)
        if not title:
            continue
        fragments: list[str] = []
        sibling = heading.getnext()
        while sibling is not None:
            if _tag_name(sibling) in {"h2", "h3"}:
                break
            text = _node_text(sibling)
            if text:
                fragments.append(text)
            sibling = sibling.getnext()
        value = normalize_whitespace(" ".join(fragments))
        if not value:
            parent = heading.getparent()
            if parent is not None:
                nested_headings = parent.xpath(".//h2 | .//h3")
                if len(nested_headings) == 1:
                    value = _text_without_heading(parent, heading)
        if value:
            sections[title] = normalize_whitespace(
                " ".join(filter(None, (sections.get(title), value)))
            )
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


def _collect_links(scope: Any, source_url: str) -> tuple[dict[str, list[str]], list[str]]:
    links = {
        "application_candidates": [],
        "document_urls": [],
        "result_urls": [],
        "detail_urls": [],
    }
    for anchor in scope.xpath(".//a[@href]"):
        link = _absolute_safe_url(source_url, anchor.get("href"))
        if link is None or link == source_url:
            continue
        text = _node_text(anchor)
        class_name = (anchor.get("class") or "").lower()
        text_lower = text.lower()
        host = urlsplit(link).hostname
        if (
            re.search(r"подать\s+заяв|заполнить\s+заяв|перейти\s+к\s+заяв", text_lower)
            or re.search(r"личн\w*\s+кабинет", text_lower)
            or host == "zayavka.fondpotanin.ru"
        ):
            bucket = "application_candidates"
        elif re.search(r"\.(?:pdf|docx?|xlsx?|pptx?)(?:$|[?#])", link, re.IGNORECASE) or re.search(
            r"положени|правил|регламент|документ|бюджет", text_lower
        ):
            bucket = "document_urls"
        elif re.search(r"победител|итог", text_lower):
            bucket = "result_urls"
        elif ("button" in class_name or "подроб" in text_lower or "услов" in text_lower):
            bucket = "detail_urls"
        else:
            continue
        if link not in links[bucket]:
            links[bucket].append(link)

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

    sections = _extract_sections(scope)
    source_status, status_issues = _source_status(scope)
    issues.extend(status_issues)

    schedule_texts = _relevant_section_texts(
        sections,
        ("когда", "порядок", "прием", "приём", "заяв"),
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
        f"{title} {text}"
        for title, text in sections.items()
        if "грантовый фонд" in normalize_heading(title)
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
        list(sections.values()) or [main_text]
    )

    taxonomy_texts = _relevant_section_texts(
        sections,
        ("направлен", "тем", "географ", "регион", "территор"),
    )
    if not taxonomy_texts:
        taxonomy_texts = [main_text]
    links, link_warnings = _collect_links(scope, source_url)
    warnings = list(link_warnings)
    if per_program_funding.warning:
        warnings.append(per_program_funding.warning)

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
            "links": {
                "document_urls": links["document_urls"],
                "result_urls": links["result_urls"],
                "detail_urls": links["detail_urls"],
            },
        },
        "warnings": warnings,
    }
    return ParsedCompetitionPage(record_payload=record, issues=tuple(issues))

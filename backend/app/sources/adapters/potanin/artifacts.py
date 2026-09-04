from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
import logging
import re
from typing import Any, Literal
from urllib.parse import urldefrag, urljoin

from lxml import etree, html as lxml_html
from pypdf import PdfReader

from app.sources.adapters.potanin.normalization import (
    normalize_outbound_url,
    normalize_whitespace,
    parse_rub_amounts,
)


MAX_EXCERPT_CHARS = 4_000
MAX_PDF_PAGES = 300
MAX_HEADINGS = 80
MAX_LIST_ENTRIES = 100
MAX_LINKS = 200


@dataclass(frozen=True)
class ArtifactInspectionIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ArtifactInspection:
    payload: dict[str, Any]
    issues: tuple[ArtifactInspectionIssue, ...] = ()


_RESULT_TERMS = re.compile(r"победител|итог|лауреат|результат", re.IGNORECASE)
_RESULT_TOTAL_TERMS = re.compile(r"\b(?:итого|всего\s+выделено)\b", re.IGNORECASE)


@contextmanager
def _quiet_pypdf_repair_messages():
    """Keep recoverable PDF repair diagnostics out of the JSON CLI report."""

    logger = logging.getLogger("pypdf._reader")
    previous_level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous_level)


def _excerpt(value: str) -> tuple[str | None, bool]:
    normalized = normalize_whitespace(value)
    if not normalized:
        return None, False
    if len(normalized) <= MAX_EXCERPT_CHARS:
        return normalized, False
    return normalized[:MAX_EXCERPT_CHARS].rstrip(), True


def _result_fragments(value: str) -> list[str]:
    fragments: list[str] = []
    for fragment in re.split(r"(?<=[.!?])\s+|\n+", value):
        normalized = normalize_whitespace(fragment)
        if normalized and _RESULT_TERMS.search(normalized):
            fragments.append(normalized[:500])
        if len(fragments) >= 30:
            break
    return fragments


def _result_funding_observations(value: str) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for fragment in re.split(r"\n+|(?<=[.!?])\s+", value):
        normalized = normalize_whitespace(fragment)
        if not normalized or not _RESULT_TOTAL_TERMS.search(normalized):
            continue
        for amount in parse_rub_amounts(normalized):
            observation = {
                "scope": "awarded_total",
                "value": {
                    "value_kind": "exact",
                    "currency_code": "RUB",
                    "exact_amount": str(amount),
                },
                "label": "Итоговая сумма по результатам",
                "evidence": normalized[:500],
            }
            if observation not in observations:
                observations.append(observation)
    return observations


def _safe_link(base_url: str, href: str) -> str | None:
    return normalize_outbound_url(urldefrag(urljoin(base_url, href.strip()))[0])


def _inspect_html(content: bytes, *, source_url: str) -> ArtifactInspection:
    try:
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded = content.decode("windows-1251", errors="replace")
        root = lxml_html.fromstring(decoded)
    except (etree.ParserError, ValueError, TypeError) as error:
        return ArtifactInspection(
            payload={"kind": "html", "status": "unreadable"},
            issues=(
                ArtifactInspectionIssue(
                    code="artifact_html_parse_failed",
                    message=f"Could not parse linked HTML: {error}",
                ),
            ),
        )

    title_nodes = root.xpath("//h1 | //title")
    title = (
        normalize_whitespace(" ".join(title_nodes[0].itertext()))
        if title_nodes
        else None
    )
    headings = [
        normalize_whitespace(" ".join(node.itertext()))
        for node in root.xpath("//h1 | //h2 | //h3 | //h4")
    ]
    headings = [heading for heading in headings if heading][:MAX_HEADINGS]
    scope_nodes = root.xpath("(//main | //article | //body)[1]")
    scope = scope_nodes[0] if scope_nodes else root
    text = normalize_whitespace(" ".join(scope.itertext()))
    text_excerpt, text_truncated = _excerpt(text)

    list_entries = [
        normalize_whitespace(" ".join(node.itertext()))
        for node in scope.xpath(".//li | .//tr")
    ]
    list_entries = [entry for entry in list_entries if entry][:MAX_LIST_ENTRIES]

    links: list[dict[str, str]] = []
    for anchor in scope.xpath(".//a[@href]"):
        href = anchor.get("href")
        if not href:
            continue
        url = _safe_link(source_url, href)
        if url is None:
            continue
        label = normalize_whitespace(" ".join(anchor.itertext()))
        candidate = {"url": url, "label": label}
        if candidate not in links:
            links.append(candidate)
        if len(links) >= MAX_LINKS:
            break

    return ArtifactInspection(
        payload={
            "kind": "html",
            "status": "inspected",
            "title": title,
            "headings": headings,
            "text_excerpt": text_excerpt,
            "text_truncated": text_truncated,
            "result_evidence": _result_fragments(text),
            "funding_observations": _result_funding_observations(text),
            "list_entries": list_entries,
            "outbound_links": links,
        }
    )


def _inspect_pdf(content: bytes) -> ArtifactInspection:
    try:
        with _quiet_pypdf_repair_messages():
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted:
                return ArtifactInspection(
                    payload={"kind": "pdf", "status": "encrypted"},
                    issues=(
                        ArtifactInspectionIssue(
                            code="artifact_pdf_encrypted",
                            message="The linked PDF is encrypted and was stored for manual review.",
                        ),
                    ),
                )
            page_count = len(reader.pages)
            text_parts: list[str] = []
            text_truncated = page_count > MAX_PDF_PAGES
            for page in reader.pages[:MAX_PDF_PAGES]:
                try:
                    page_text = page.extract_text() or ""
                except Exception:
                    page_text = ""
                if page_text:
                    text_parts.append(page_text)
                if sum(len(part) for part in text_parts) > MAX_EXCERPT_CHARS:
                    text_truncated = True
                    break
    except Exception as error:
        return ArtifactInspection(
            payload={"kind": "pdf", "status": "unreadable"},
            issues=(
                ArtifactInspectionIssue(
                    code="artifact_pdf_parse_failed",
                    message=f"Could not inspect the stored PDF: {error}",
                ),
            ),
        )

    text = "\n".join(text_parts)
    text_excerpt, excerpt_truncated = _excerpt(text)
    text_truncated = text_truncated or excerpt_truncated
    metadata = reader.metadata
    title = metadata.title if metadata is not None else None
    payload = {
        "kind": "pdf",
        "status": "inspected" if text_excerpt else "stored_without_text",
        "page_count": page_count,
        "title": normalize_whitespace(title) if title else None,
        "text_excerpt": text_excerpt,
        "text_truncated": text_truncated,
        "result_evidence": _result_fragments(text),
        "funding_observations": _result_funding_observations(text),
    }
    if text_excerpt is not None:
        return ArtifactInspection(payload=payload)
    return ArtifactInspection(payload=payload)


def inspect_linked_artifact(
    content: bytes,
    *,
    content_format: str,
    source_url: str,
) -> ArtifactInspection:
    """Return bounded, review-oriented metadata while raw bytes remain external."""

    normalized_format = content_format.lower()
    if "pdf" in normalized_format or content.startswith(b"%PDF"):
        return _inspect_pdf(content)
    if "html" in normalized_format or "xml" in normalized_format:
        return _inspect_html(content, source_url=source_url)
    return ArtifactInspection(
        payload={
            "kind": "binary",
            "status": "stored_without_parser",
            "content_format": content_format,
        },
        issues=(
            ArtifactInspectionIssue(
                code="artifact_format_not_inspected",
                message=(
                    f"The linked {content_format!r} resource was stored but has no safe "
                    "text inspector yet."
                ),
            ),
        ),
    )

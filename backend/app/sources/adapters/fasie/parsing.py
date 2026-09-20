from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

from lxml import etree, html as lxml_html

from .normalization import (
    ApplicationWindow,
    FASIE_HOST,
    FASIE_SOURCE_PUBLISHER,
    extract_application_windows,
    extract_grant_funding,
    feed_page_url,
    identity_key,
    normalize_reference_url,
    normalize_title,
    normalize_upload_url,
    normalize_whitespace,
    parse_publication_datetime,
    press_detail_url,
    stable_hash,
)


PublicationKind = Literal["launch", "extension", "amendment", "result", "opportunity", "ignore"]
OriginKind = Literal["first_party", "third_party"]


@dataclass(frozen=True)
class ParserIssue:
    severity: Literal["warning", "error"]
    code: str
    field: str
    message: str


@dataclass(frozen=True)
class FeedPublication:
    url: str
    title: str
    published_at: datetime | None


@dataclass(frozen=True)
class ParsedFeedPage:
    entries: tuple[FeedPublication, ...]
    next_url: str | None
    issues: tuple[ParserIssue, ...] = ()


@dataclass(frozen=True)
class ParsedHomePage:
    competition_urls: tuple[str, ...]
    issues: tuple[ParserIssue, ...] = ()


@dataclass(frozen=True)
class ParsedPublication:
    url: str
    source_title: str
    title: str
    published_at: datetime | None
    # Feed pages are newest-first.  Retaining the first-seen position gives
    # grouping a deterministic chronology when a source exposes dates but no
    # publication time.
    feed_position: int | None
    classification: PublicationKind
    identity_name: str | None
    queue: str | None
    stage: str | None
    year: int | None
    identity: str | None
    origin_kind: OriginKind
    organizer: str | None
    opportunity_type: str
    application_windows: tuple[ApplicationWindow, ...]
    funding: Any | None
    funding_evidence: str | None
    summary: str | None
    eligibility: str | None
    contacts: tuple[dict[str, str], ...]
    themes: tuple[dict[str, str], ...]
    geographies: tuple[dict[str, str], ...]
    sections: dict[str, str]
    application_urls: tuple[str, ...]
    origin_urls: tuple[str, ...]
    reference_urls: tuple[str, ...]
    document_urls: tuple[dict[str, str], ...]
    evidence: tuple[str, ...]
    issues: tuple[ParserIssue, ...] = ()


def _node_text(node: Any) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _decode_html(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("windows-1251", errors="replace")


def _parse_root(content: bytes) -> Any:
    return lxml_html.fromstring(_decode_html(content))


def _first_date_text(node: Any) -> str | None:
    values = node.xpath(
        ".//*[contains(concat(' ', normalize-space(@class), ' '), ' plane_date ')]//b//text()"
    )
    if values:
        return " ".join(str(value) for value in values)
    text = _node_text(node)
    match = re.search(
        r"\b\d{1,2}[./]\d{1,2}[./]\d{4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\b",
        text,
    )
    return match.group(0) if match else None


def _card_title(anchor: Any) -> str:
    heading = anchor.xpath(".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6")
    return _node_text(heading[0]) if heading else _node_text(anchor)


def parse_home_page(content: bytes, *, source_url: str) -> ParsedHomePage:
    issues: list[ParserIssue] = []
    try:
        root = _parse_root(content)
    except (etree.ParserError, ValueError, TypeError) as error:
        return ParsedHomePage(
            (),
            (ParserIssue("error", "invalid_home_html", "home", str(error)),),
        )
    candidates: list[str] = []
    slides = root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' banner_slider ')]"
        "//*[starts-with(normalize-space(@class), 'n_')]"
    )
    if not slides:
        slides = root.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' banner_slider ')]")
    for slide in slides:
        slide_text = _node_text(slide).casefold()
        if "конкурс" not in slide_text or "подать заявку" not in slide_text:
            continue
        for anchor in slide.xpath(".//a[@href]"):
            try:
                url = press_detail_url(anchor.get("href", ""), base_url=source_url)
            except ValueError:
                continue
            if url not in candidates:
                candidates.append(url)
    if not candidates:
        issues.append(
            ParserIssue(
                "warning",
                "home_competition_block_missing",
                "home",
                "The home page did not expose a valid press competition link in the application banner.",
            )
        )
    return ParsedHomePage(tuple(candidates), tuple(issues))


def _next_pager(root: Any, *, source_url: str, issues: list[ParserIssue]) -> str | None:
    next_urls: list[str] = []
    for anchor in root.xpath(".//a[@href]"):
        href = anchor.get("href")
        if not isinstance(href, str) or "/press/news/" not in href:
            continue
        try:
            candidate = feed_page_url(urljoin(source_url, href))
        except ValueError as error:
            issues.append(
                ParserIssue(
                    "error",
                    "malformed_feed_pager",
                    "pagination",
                    str(error),
                )
            )
            continue
        if candidate not in next_urls:
            next_urls.append(candidate)
    if len(next_urls) > 1:
        issues.append(
            ParserIssue(
                "error",
                "ambiguous_feed_pager",
                "pagination",
                "The FASIE feed exposed more than one valid next page.",
            )
        )
        return None
    return next_urls[0] if next_urls else None


def parse_feed_page(content: bytes, *, source_url: str) -> ParsedFeedPage:
    issues: list[ParserIssue] = []
    try:
        root = _parse_root(content)
    except (etree.ParserError, ValueError, TypeError) as error:
        return ParsedFeedPage(
            (),
            None,
            (ParserIssue("error", "invalid_feed_html", "feed", str(error)),),
        )
    lists = root.xpath(
        "//ul[contains(concat(' ', normalize-space(@class), ' '), ' js-result ')]"
    )
    if not lists:
        issues.append(
            ParserIssue(
                "error",
                "feed_shape_changed",
                "feed",
                "FASIE feed does not contain the expected ul.js-result publication list.",
            )
        )
        return ParsedFeedPage((), None, tuple(issues))
    entries: list[FeedPublication] = []
    for anchor in lists[0].xpath("./a[@href] | .//a[@href]"):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        try:
            url = press_detail_url(href, base_url=source_url)
        except ValueError:
            continue
        title = _card_title(anchor)
        date_text = _first_date_text(anchor)
        published_at = parse_publication_datetime(date_text or "")
        if published_at is None:
            issues.append(
                ParserIssue(
                    "warning",
                    "publication_date_missing",
                    "published_at",
                    f"Could not parse a publication date for {url}.",
                )
            )
        entry = FeedPublication(url=url, title=title, published_at=published_at)
        if entry not in entries:
            entries.append(entry)
    next_url = _next_pager(root, source_url=source_url, issues=issues)
    if not entries:
        issues.append(
            ParserIssue(
                "warning",
                "feed_publications_missing",
                "entries",
                "The feed page contained no valid /press/fund/ publication cards.",
            )
        )
    return ParsedFeedPage(tuple(entries), next_url, tuple(issues))


def _quoted_name(text: str) -> str | None:
    pattern = re.compile(
        r"(?:конкурс\w*|преми\w*|рейтинг\w*|акселератор\w*|программ\w*)\s*"
        r"[«\"“](.+?)[»\"”]",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return normalize_title(match.group(1)) if match else None


def _fallback_name(text: str) -> str | None:
    match = re.search(
        r"(?:конкурс\w*|рейтинг\w*|акселератор\w*|программ\w*)\s+"
        r"([А-ЯЁA-Z][^.!?;:]{2,100})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = re.split(r"\s+(?:в рамках|по программе|для|на участие)\b", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
    return normalize_title(value)


def _identity_parts(title: str, text: str, published_at: datetime | None) -> tuple[str | None, str | None, str | None, int | None, str | None]:
    context = f"{title} {text[:4_000]}"
    name = _quoted_name(title) or _fallback_name(title)
    if name is None:
        name = _quoted_name(text[:4_000]) or _fallback_name(text[:4_000])
    queue_match = re.search(r"\bочеред(?:ь|и)\s*(?:№\s*)?(\d+)\b", context, re.IGNORECASE)
    stage_match = re.search(r"\b(?:этап|стадия)\s*(?:№\s*)?(\d+)\b", context, re.IGNORECASE)
    years = [int(value) for value in re.findall(r"\b(20\d{2})\b", f"{title} {text[:4_000]}")]
    year = years[0] if years else (published_at.year if published_at else None)
    queue = queue_match.group(1) if queue_match else None
    stage = stage_match.group(1) if stage_match else None
    identity = identity_key(name, queue, stage, year) if name and year else None
    return name, queue, stage, year, identity


def _classify_publication(title: str, text: str) -> PublicationKind:
    lower_title = title.casefold()
    lower = f"{lower_title} {text}".casefold()
    if re.search(r"подведен\w*\s+итог|итог\w*\s+по\s+конкурс|результат\w*\s+конкурс|список\s+победител\w*\s+конкурс", lower_title):
        return "result"
    if re.search(r"продлен\w*|продлени\w*\s+при[её]м|продолжен\w*\s+при[её]м", lower_title):
        return "extension"
    if re.search(r"изменен\w*|изменени\w*|дополнен\w*|уточнен\w*", lower_title) and re.search(r"конкурс|положен|услов|лот", lower):
        return "amendment"
    if re.search(r"запуск\s+конкурс|начал\w*\s+отбор|открыт\w*\s+при[её]м|объявля\w*\s+о\s+начал", lower_title):
        return "launch"
    if re.search(r"вебинар|конференц|форум|грантополучател\w*\s+фонда|создан\w*\s+при\s+поддержк", lower_title):
        return "ignore"
    has_application = bool(
        re.search(r"при[её]м\s+заяв|подать\s+заяв|заявк\w*\s+можно|открыт\w*\s+при[её]м|набор\w*\s+в\s+акселератор", lower)
    )
    has_opportunity_subject = bool(
        re.search(r"конкурс|преми|рейтинг|акселератор|программ\w*", lower)
    )
    return "opportunity" if has_application and has_opportunity_subject else "ignore"


def _section_category(title: str) -> str:
    normalized = title.casefold()
    if re.search(r"участ|заявител|требован|критери", normalized):
        return "eligibility"
    if re.search(r"контакт|обраща|телефон|email|почт", normalized):
        return "contacts"
    if re.search(r"финанс|грант|поддержк", normalized):
        return "funding"
    if re.search(r"тем|направлен|лот|номинац", normalized):
        return "taxonomy"
    if re.search(r"географ|регион|территор", normalized):
        return "geography"
    if re.search(r"документ|положен|правил", normalized):
        return "documents"
    if re.search(r"срок|этап|при[её]м|подач|результат", normalized):
        return "schedule"
    return "unclassified"


def _extract_sections(body: Any) -> dict[str, str]:
    sections: dict[str, str] = {}
    headings = body.xpath(".//h2 | .//h3 | .//h4")
    for heading in headings:
        title = _node_text(heading)
        if not title:
            continue
        chunks: list[str] = []
        sibling = heading.getnext()
        while sibling is not None and not sibling.xpath("self::h2 | self::h3 | self::h4"):
            value = _node_text(sibling)
            if value:
                chunks.append(value)
            sibling = sibling.getnext()
        text = " ".join(chunks).strip()
        if text:
            sections[title] = text[:10_000]
    return sections


def _contact_entries(text: str) -> tuple[dict[str, str], ...]:
    emails = list(dict.fromkeys(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}", text)))
    phones = list(dict.fromkeys(re.findall(r"(?:\+7|8)\s*\(?\d{3}\)?[\s\-\d().]{7,}", text)))
    if not emails and not phones:
        return ()
    entry: dict[str, str] = {"source": FASIE_SOURCE_PUBLISHER}
    if emails:
        entry["email"] = emails[0][:320]
    if phones:
        entry["phone"] = " ".join(phones[0].split())[:64]
    return (entry,)


def _taxonomy(text: str) -> tuple[tuple[dict[str, str], ...], tuple[dict[str, str], ...]]:
    themes: list[dict[str, str]] = []
    geographies: list[dict[str, str]] = []
    theme_lines = re.findall(r"(?:^|[.!?])\s*(?:\d+[.)]\s*)?([^.!?]{3,120})", text)
    for line in theme_lines:
        value = " ".join(line.split())
        lower = value.casefold()
        if any(term in lower for term in ("медицин", "ии", "искусственн", "станко", "космич", "агро", "цифров")):
            slug = re.sub(r"[^a-z0-9]+", "-", lower.replace("ё", "е"), flags=re.UNICODE).strip("-")[:80]
            item = {"slug": slug or f"theme-{stable_hash(value)[:12]}", "name": value[:300]}
            if item not in themes:
                themes.append(item)
    geo_terms = {
        "росси": "russia",
        "москв": "moscow",
        "регион": "regions",
        "субъект": "regions",
    }
    for needle, slug in geo_terms.items():
        if needle in text.casefold():
            item = {"slug": slug, "name": "Россия" if slug == "russia" else "Региональный охват"}
            if item not in geographies:
                geographies.append(item)
    return tuple(themes[:30]), tuple(geographies[:10])


def _application_link(label: str, context: str, url: str) -> bool:
    lower = f"{label} {context}".casefold()
    label_lower = label.casefold()
    host = urlsplit(url).hostname or ""
    if host == "online.fasie.ru":
        return True
    if host == FASIE_HOST:
        return bool(re.search(r"подать\s+заяв|регистрац\w*|портал\s+подач", label_lower))
    return bool(re.search(r"подать\s+заяв|заявк\w*|регистрац\w*|портал\s+подач", lower))


def _origin_link(label: str, context: str, url: str, source_url: str) -> bool:
    if url == source_url or urlsplit(url).hostname == "online.fasie.ru":
        return False
    lower = f"{label} {context}".casefold()
    parsed = urlsplit(url)
    if parsed.hostname == FASIE_HOST and parsed.path.startswith(("/programs/", "/competitions/")):
        return True
    return bool(re.search(r"официальн\w*\s+сайт|сайт\s+(?:конкурс|преми|программ)|организатор|первичн", lower))


def _extract_links(body: Any, *, source_url: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[dict[str, str], ...]]:
    application_urls: list[str] = []
    origin_urls: list[str] = []
    reference_urls: list[str] = []
    documents: list[dict[str, str]] = []
    for anchor in body.xpath(".//a[@href]"):
        href = anchor.get("href")
        if not isinstance(href, str) or href.casefold().startswith(("mailto:", "tel:", "javascript:")):
            continue
        label = _node_text(anchor)
        parent = anchor.getparent()
        context = _node_text(parent) if parent is not None else label
        url = normalize_reference_url(href, base_url=source_url)
        if url is None:
            continue
        if urlsplit(url).hostname == FASIE_HOST and urlsplit(url).path.startswith("/upload/"):
            try:
                document_url = normalize_upload_url(url)
            except ValueError:
                continue
            item = {"url": document_url, "label": label[:500], "kind": "document"}
            if item not in documents:
                documents.append(item)
            continue
        if _application_link(label, context, url):
            if url not in application_urls:
                application_urls.append(url)
            if url not in reference_urls:
                reference_urls.append(url)
        elif _origin_link(label, context, url, source_url):
            if url not in origin_urls:
                origin_urls.append(url)
        elif url not in reference_urls:
            reference_urls.append(url)
    return tuple(application_urls), tuple(origin_urls), tuple(reference_urls), tuple(documents)


def _organizer_and_origin(text: str, title: str) -> tuple[str | None, OriginKind]:
    lower = text.casefold()
    if re.search(r"фонд\s+содействия\s+инновациям\s+(?:объявля\w*|провод\w*|открыва\w*)", lower):
        return FASIE_SOURCE_PUBLISHER, "first_party"
    explicit = re.search(r"организатор(?:ом)?\s*(?:является|выступает|:)?\s*([^.;]{3,160})", text, re.IGNORECASE)
    if explicit:
        return normalize_whitespace(explicit.group(1)).strip(" ,–—"), "third_party"
    subject = re.search(r"^\s*([А-ЯЁA-Z][^.!?]{2,120}?)\s+(?:объявля\w*|приглаша\w*|открыва\w*)", text)
    if subject and "фонд содействия инновациям" not in subject.group(1).casefold():
        return normalize_whitespace(subject.group(1)).strip(" ,–—"), "third_party"
    if re.search(r"альянс|университет|кластер|банк|ассоциац|преми", f"{title} {text}".casefold()):
        return None, "third_party"
    return None, "first_party"


def _opportunity_type(title: str, text: str, funding: Any | None) -> str:
    lower = f"{title} {text}".casefold()
    if "рейтинг" in lower:
        return "rating"
    if "акселератор" in lower:
        return "accelerator"
    if funding is not None or "грант" in lower:
        return "grant"
    if "конкурс" in lower or "преми" in lower:
        return "contest"
    return "other"


def parse_publication_page(
    content: bytes,
    *,
    source_url: str,
    feed_published_at: datetime | None = None,
    feed_position: int | None = None,
) -> ParsedPublication:
    issues: list[ParserIssue] = []
    try:
        root = _parse_root(content)
    except (etree.ParserError, ValueError, TypeError) as error:
        return ParsedPublication(
            url=source_url,
            source_title="",
            title="",
            published_at=feed_published_at,
            feed_position=feed_position,
            classification="ignore",
            identity_name=None,
            queue=None,
            stage=None,
            year=None,
            identity=None,
            origin_kind="first_party",
            organizer=None,
            opportunity_type="other",
            application_windows=(),
            funding=None,
            funding_evidence=None,
            summary=None,
            eligibility=None,
            contacts=(),
            themes=(),
            geographies=(),
            sections={},
            application_urls=(),
            origin_urls=(),
            reference_urls=(),
            document_urls=(),
            evidence=(),
            issues=(ParserIssue("error", "invalid_publication_html", "page", str(error)),),
        )
    containers = root.xpath(
        "//*[contains(concat(' ', normalize-space(@class), ' '), ' plane_text ')]"
    )
    if not containers:
        return ParsedPublication(
            url=source_url,
            source_title="",
            title="",
            published_at=feed_published_at,
            feed_position=feed_position,
            classification="ignore",
            identity_name=None,
            queue=None,
            stage=None,
            year=None,
            identity=None,
            origin_kind="first_party",
            organizer=None,
            opportunity_type="other",
            application_windows=(),
            funding=None,
            funding_evidence=None,
            summary=None,
            eligibility=None,
            contacts=(),
            themes=(),
            geographies=(),
            sections={},
            application_urls=(),
            origin_urls=(),
            reference_urls=(),
            document_urls=(),
            evidence=(),
            issues=(
                ParserIssue(
                    "error",
                    "publication_shape_changed",
                    "plane_text",
                    "FASIE publication does not contain .plane_text.",
                ),
            ),
        )
    container = containers[0]
    title_nodes = container.xpath(".//h1")
    source_title = _node_text(title_nodes[0]) if title_nodes else ""
    if not source_title:
        issues.append(ParserIssue("error", "title_missing", "title", "FASIE publication has no h1."))
    date_text = _first_date_text(root)
    published_at = parse_publication_datetime(date_text or "") or feed_published_at
    if published_at is None:
        issues.append(ParserIssue("warning", "publication_date_missing", "published_at", "Publication date is unavailable."))
    body_nodes = container.xpath(".//*[@itemprop='text']")
    body = body_nodes[0] if body_nodes else container
    text = _node_text(body)
    title = normalize_title(source_title)
    classification = _classify_publication(source_title, text)
    identity_name, queue, stage, year, identity = _identity_parts(source_title, text, published_at)
    if classification == "opportunity":
        # A generic opportunity page is intentionally standalone unless it is
        # later promoted to a typed launch/extension/amendment publication.
        identity = None
    application_windows = extract_application_windows(text, fallback_year=year)
    funding_result = extract_grant_funding(text)
    if funding_result.warning:
        issues.append(ParserIssue("warning", funding_result.warning, "funding", "Funding evidence is ambiguous."))
    summary_nodes = container.xpath(".//meta[@itemprop='description']/@content")
    summary = normalize_whitespace(summary_nodes[0]) if summary_nodes else None
    if not summary:
        paragraphs = body.xpath(".//p")
        summary = _node_text(paragraphs[0])[:2_000] if paragraphs and _node_text(paragraphs[0]) else None
    sections = _extract_sections(body)
    eligibility = next((value for heading, value in sections.items() if _section_category(heading) == "eligibility"), None)
    contacts = _contact_entries(text)
    themes, geographies = _taxonomy(text)
    application_urls, origin_urls, reference_urls, documents = _extract_links(body, source_url=source_url)
    organizer, origin_kind = _organizer_and_origin(text, source_title)
    external_application = any(
        (urlsplit(url).hostname or "") not in {FASIE_HOST, "online.fasie.ru"}
        for url in application_urls
    )
    if external_application and organizer is None:
        origin_kind = "third_party"
    if classification == "launch" and (origin_kind == "third_party" or external_application):
        classification = "opportunity"
        identity = None
    if classification in {"launch", "extension", "amendment", "result"} and identity is None:
        issues.append(
            ParserIssue(
                "warning",
                "publication_identity_missing",
                "identity",
                "The publication type is known but its competition name/year identity is incomplete.",
            )
        )
    opportunity_type = _opportunity_type(source_title, text, funding_result.funding)
    evidence = tuple(dict.fromkeys(item for item in (source_title, summary, *[window.evidence for window in application_windows], funding_result.evidence) if item))
    return ParsedPublication(
        url=source_url,
        source_title=source_title,
        title=title or source_title,
        published_at=published_at,
        feed_position=feed_position,
        classification=classification,
        identity_name=identity_name,
        queue=queue,
        stage=stage,
        year=year,
        identity=identity,
        origin_kind=origin_kind,
        organizer=organizer,
        opportunity_type=opportunity_type,
        application_windows=application_windows,
        funding=funding_result.funding,
        funding_evidence=funding_result.evidence,
        summary=summary,
        eligibility=eligibility,
        contacts=contacts,
        themes=themes,
        geographies=geographies,
        sections=sections,
        application_urls=application_urls,
        origin_urls=origin_urls,
        reference_urls=reference_urls,
        document_urls=documents,
        evidence=evidence,
        issues=tuple(issues),
    )

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from html import escape
from hashlib import sha256
import re
from time import monotonic, sleep
from typing import Any, Sequence
from urllib.parse import urlsplit

from app.import_bridge.contract import ParsedRow, ValidationIssue, add_duplicate_key_issues, parse_record
from app.sources.adapters.potanin.http import (
    HttpResponse,
    ResponseFetcher,
    SourceFetchError,
    UrllibResponseFetcher,
    fetch_result_from_response,
)
from app.sources.contract import (
    AdapterContext,
    AdapterIssue,
    AdapterReport,
    AdapterRunTimeoutError,
    AdapterRunSummary,
    AdapterStage,
    DiscoveredResource,
    DiscoveryResult,
    ExtractedRecord,
    ExtractResult,
    FetchResult,
    SourceAdapter,
    ValidationResult,
    adapter_report,
)
from app.sources.registry import UrlAllowlistError

from .artifacts import inspect_fasie_artifact
from .normalization import (
    FASIE_HOST,
    FASIE_SOURCE_PUBLISHER,
    FASIE_TZ,
    competitions_archive_url,
    feed_page_url,
    normalize_fasie_url,
    normalize_identity_name,
    normalize_online_fasie_api_url,
    normalize_online_fasie_url,
    normalize_upload_url,
    program_page_url,
    programs_index_url,
    press_detail_url,
    stable_hash,
)
from .parsing import (
    ArchivePublication,
    OnlineCompetition,
    ParsedPublication,
    ProgramCatalogEntry,
    ParserIssue,
    parse_competitions_archive_page,
    parse_feed_page,
    parse_home_page,
    parse_online_competitions_api,
    parse_program_page,
    parse_programs_index_page,
    parse_publication_page,
)


FASIE_ADAPTER_NAME = "fasie-competitions"
FASIE_ADAPTER_VERSION = "1.4.0"
_FASIE_USER_AGENT = "siderfold-fasie-adapter/1.0 (+https://fasie.ru/)"
_PARSER_ISSUES_KEY = "_parser_issues"

_KIND_HOME = "fasie-home"
_KIND_FEED = "fasie-feed"
_KIND_ONLINE = "fasie-online"
_KIND_PROGRAMS_INDEX = "fasie-programs-index"
_KIND_PROGRAM_PAGE = "fasie-program-page"
_KIND_COMPETITIONS_ARCHIVE = "fasie-competitions-archive"
_KIND_PUBLICATION = "fasie-publication"
_KIND_RECORD = "fasie-record"
_KIND_ARTIFACT = "fasie-artifact"


@dataclass(frozen=True)
class _GroupedRecord:
    key: str
    record_url: str
    canonical_publication_url: str
    payload: dict[str, Any]
    publications: tuple[ParsedPublication, ...] = ()


def _url_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:20]


def _home_resource(url: str) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=f"{FASIE_ADAPTER_NAME}:home",
        url=url,
        metadata={"kind": _KIND_HOME, "extract_record": False},
    )


def _feed_resource(url: str) -> DiscoveredResource:
    page = urlsplit(url).query or "first"
    return DiscoveredResource(
        external_key=f"{FASIE_ADAPTER_NAME}:feed:{_url_hash(page)}",
        url=url,
        metadata={"kind": _KIND_FEED, "extract_record": False},
    )


def _online_resource(api_url: str, *, public_url: str) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=f"{FASIE_ADAPTER_NAME}:online",
        url=api_url,
        metadata={
            "kind": _KIND_ONLINE,
            "extract_record": False,
            "public_url": public_url,
        },
    )


def _programs_index_resource(url: str) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=f"{FASIE_ADAPTER_NAME}:programs-index",
        url=url,
        metadata={"kind": _KIND_PROGRAMS_INDEX, "extract_record": False},
    )


def _program_page_resource(url: str) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=f"{FASIE_ADAPTER_NAME}:program:{_url_hash(url)}",
        url=url,
        metadata={"kind": _KIND_PROGRAM_PAGE, "extract_record": False},
    )


def _competitions_archive_resource(url: str) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=f"{FASIE_ADAPTER_NAME}:competitions-archive",
        url=url,
        metadata={"kind": _KIND_COMPETITIONS_ARCHIVE, "extract_record": False},
    )


def _publication_resource(url: str, *, published_at: datetime | None, title: str) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=f"{FASIE_ADAPTER_NAME}:publication:{_url_hash(url)}",
        url=url,
        metadata={
            "kind": _KIND_PUBLICATION,
            "extract_record": False,
            "published_at": published_at.isoformat() if published_at else None,
            "title_hint": title,
        },
    )


def _artifact_resource(url: str, parent_record_keys: Sequence[str]) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=f"{FASIE_ADAPTER_NAME}:artifact:{_url_hash(url)}",
        url=url,
        metadata={
            "kind": _KIND_ARTIFACT,
            "extract_record": False,
            "parent_record_keys": list(parent_record_keys),
        },
    )


def _record_resource(group: _GroupedRecord, *, source_publication_url: str) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=group.key,
        url=group.record_url,
        metadata={
            "kind": _KIND_RECORD,
            "extract_record": True,
            "record_key": group.key,
            "source_publication_url": source_publication_url,
            "record_payload": deepcopy(group.payload),
        },
    )


def _archive_publication_stub(entry: ArchivePublication) -> bytes:
    """Build enough structured HTML to normalize a bounded archive row.

    The competitions archive is itself the authoritative public evidence for
    a result title and date.  Fetching every result detail page (and each
    legacy attachment it links) causes FASIE to rate-limit a manual run.  We
    retain an archive-only record with its detail URL as provenance; a detail
    page already selected through the active feed supersedes this stub.
    """

    title = escape(entry.title)
    return (
        "<div class='plane_text'>"
        f"<h1>{title}</h1>"
        f"<div itemprop='text'><p>{title}</p></div>"
        "</div>"
    ).encode()


def _parser_issue_to_adapter(issue: ParserIssue, resource_key: str) -> AdapterIssue:
    return AdapterIssue(
        stage=AdapterStage.DISCOVER,
        severity=issue.severity,
        code=issue.code,
        message=issue.message,
        resource_key=resource_key,
        field=issue.field,
    )


def _publication_sort_key(publication: ParsedPublication) -> tuple[datetime, int, str]:
    # FASIE's feed is newest-first.  A page date alone is not enough to order
    # an announcement, extension, and result that all share that date, so use
    # the first-seen feed position before falling back to the stable URL.
    feed_position = -publication.feed_position if publication.feed_position is not None else 0
    return (
        publication.published_at or datetime.min.replace(tzinfo=FASIE_TZ),
        feed_position,
        publication.url,
    )


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _not_stated_funding() -> dict[str, Any]:
    return {"value": {"value_kind": "not_stated"}}


def _funding_payload(funding: Any | None, evidence: str | None) -> dict[str, Any]:
    if funding is None:
        return {"total_grant_fund": _not_stated_funding(), "per_program": _not_stated_funding(), "amounts": []}
    value = funding.model_dump(mode="json", exclude_none=True)
    entry = {"value": value, "evidence": evidence}
    return {"total_grant_fund": _not_stated_funding(), "per_program": entry, "amounts": [entry]}


def _unique_dicts(values: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for value in values:
        if value not in result:
            result.append(dict(value))
    return result


def _serialize_publication(publication: ParsedPublication) -> dict[str, Any]:
    return {
        "url": publication.url,
        "published_at": _iso(publication.published_at),
        "type": publication.classification,
        "title": publication.source_title,
        "identity": publication.identity,
        "full_page_content": publication.full_page_content,
        "related_publication_urls": list(publication.related_publication_urls),
        "evidence": list(publication.evidence[:8]),
    }


def _application_values(publications: Sequence[ParsedPublication]) -> tuple[date | None, date | None, datetime | None, datetime | None, list[str], list[str]]:
    relevant = [publication for publication in publications if publication.classification != "result"]
    windows = [window for publication in relevant for window in publication.application_windows]
    starts = [window for window in windows if window.start_on is not None]
    start = min((window.start_on for window in starts), default=None)
    start_at = min((window.start_at for window in starts if window.start_at is not None), default=None)
    # A later extension/amendment with an explicit deadline is authoritative;
    # do not keep the older launch deadline merely because it is later.
    latest_deadline = next(
        (
            window
            for publication in reversed(relevant)
            for window in reversed(publication.application_windows)
            if window.end_on is not None
        ),
        None,
    )
    end = latest_deadline.end_on if latest_deadline is not None else None
    end_at = latest_deadline.end_at if latest_deadline is not None else None
    evidence = [window.evidence for window in windows]
    return (
        start,
        end,
        start_at,
        end_at,
        list(dict.fromkeys(evidence)),
        [publication.url for publication in relevant if publication.application_windows],
    )


def _display_title(publications: Sequence[ParsedPublication]) -> str:
    active = [publication for publication in publications if publication.classification != "result"]
    identified = [
        publication
        for publication in active
        if publication.identity is not None and publication.identity_name
    ]
    source = (
        sorted(identified or active or list(publications), key=_publication_sort_key)[-1]
        if active or publications
        else None
    )
    if source is None:
        return "Актуальная возможность Фонда содействия инновациям"
    # A single publication must retain its cleaned H1.  An identity inferred
    # from page text is useful for linking an explicit launch/extension group,
    # but it is not a reader-facing replacement for a standalone card title.
    grouped = len(active) > 1
    title = (
        source.identity_name
        if grouped and source.identity and source.identity_name
        else source.title
    )
    if source.identity and source.queue and not re_search_queue(title):
        title = f"{title} (ОЧЕРЕДЬ {source.queue})"
    if source.identity and source.stage and not re_search_stage(title):
        title = f"{title} (ЭТАП {source.stage})"
    return title.strip()


def re_search_queue(value: str) -> bool:
    return "очеред" in value.casefold()


def re_search_stage(value: str) -> bool:
    return bool(value and "этап" in value.casefold())


def _source_status(
    publications: Sequence[ParsedPublication],
    *,
    as_of: datetime,
    start_on: date | None,
    end_at: datetime | None,
) -> str:
    """Derive an informational lifecycle state without hiding old records."""

    if any(publication.classification == "result" for publication in publications):
        return "completed"
    today = as_of.date()
    if start_on is not None and start_on > today:
        return "upcoming"
    if end_at is not None:
        if end_at < as_of:
            return "closed"
        return "open"
    if any(publication.classification in {"launch", "extension"} for publication in publications):
        return "open"
    if any(publication.classification == "milestone" for publication in publications):
        return "closed"
    return "unknown"


def _canonical_publication(publications: Sequence[ParsedPublication]) -> ParsedPublication:
    linked_targets = {
        url
        for publication in publications
        for url in publication.related_publication_urls
    }
    linked = [publication for publication in publications if publication.url in linked_targets]
    identified = [
        publication
        for publication in publications
        if publication.identity is not None and publication.classification != "result"
    ]
    return sorted(linked or identified or list(publications), key=_publication_sort_key)[-1]


def _timeline_kind(classification: str) -> str:
    return {
        "launch": "application_open",
        "extension": "application",
        "amendment": "other",
        "milestone": "evaluation",
        "result": "results",
        "opportunity": "application",
    }.get(classification, "other")


def _build_grouped_record(
    publications: Sequence[ParsedPublication],
    *,
    as_of: datetime,
    cutoff: date,
    identity_override: str | None = None,
) -> tuple[_GroupedRecord | None, tuple[ParserIssue, ...]]:
    ordered = sorted(publications, key=_publication_sort_key)
    issues: list[ParserIssue] = []
    if not ordered:
        return None, ()
    del cutoff
    last = ordered[-1]
    non_results = [publication for publication in ordered if publication.classification != "result"]
    start_on, end_on, start_at, end_at, date_evidence, _date_sources = _application_values(ordered)
    source_status = _source_status(
        ordered,
        as_of=as_of,
        start_on=start_on,
        end_at=end_at,
    )
    if end_at is None and source_status in {"open", "upcoming"}:
        issues.append(
            ParserIssue(
                "warning",
                "deadline_missing",
                "deadline_on",
                "The opportunity is explicitly current but no application deadline was found.",
            )
        )
    identity = identity_override or next(
        (publication.identity for publication in ordered if publication.identity),
        None,
    )
    canonical = _canonical_publication(ordered)
    if identity is None:
        key = f"fasie:publication:{stable_hash(last.url)}"
        record_url = canonical.url
    else:
        key = f"fasie:competition:{stable_hash(identity)}"
        record_url = canonical.url
    latest_funding = next((publication for publication in reversed(non_results) if publication.funding is not None), None)
    application_urls = list(dict.fromkeys(url for publication in ordered for url in publication.application_urls))
    origin_urls = list(dict.fromkeys(url for publication in ordered for url in publication.origin_urls))
    reference_urls = list(dict.fromkeys(url for publication in ordered for url in publication.reference_urls))
    documents: list[dict[str, str]] = []
    for publication in ordered:
        for document in publication.document_urls:
            if document not in documents:
                documents.append(dict(document))
    if identity is None and not origin_urls:
        external_application_urls = [
            url
            for url in application_urls
            if (urlsplit(url).hostname or "").casefold() not in {FASIE_HOST, "online.fasie.ru"}
        ]
        if len(external_application_urls) == 1:
            # A sole third-party application page is the best available
            # primary identity for a standalone FASIE publication.  It is
            # retained as a reference too; this additional provenance value
            # only enables exact, manual-review-only cross-source matching.
            origin_urls.append(external_application_urls[0])
        else:
            issues.append(
                ParserIssue(
                    "warning",
                    "origin_url_missing_possible_duplicate",
                    "origin_urls",
                    "The standalone external opportunity has no explicit primary origin URL.",
                )
            )
    contacts = _unique_dicts([contact for publication in ordered for contact in publication.contacts])
    themes = _unique_dicts([theme for publication in ordered for theme in publication.themes])
    geographies = _unique_dicts([geo for publication in ordered for geo in publication.geographies])
    sections: dict[str, str] = {}
    for publication in ordered:
        sections.update(publication.sections)
    source_title = _display_title(ordered)
    summary = next((publication.summary for publication in reversed(non_results) if publication.summary), None)
    eligibility = next((publication.eligibility for publication in reversed(non_results) if publication.eligibility), None)
    organizer = next((publication.organizer for publication in reversed(ordered) if publication.organizer), None)
    origin_kind = "third_party" if any(publication.origin_kind == "third_party" for publication in ordered) else "first_party"
    opportunity_type = next((publication.opportunity_type for publication in reversed(non_results) if publication.opportunity_type), "other")
    application = {
        "start_on": _iso(start_on),
        "end_on": _iso(end_on),
        "start_at": _iso(start_at),
        "end_at": _iso(end_at),
        "url": application_urls[0] if application_urls else None,
        "candidate_urls": application_urls,
        "date_evidence": date_evidence,
    }
    timeline = [
        {
            "kind": _timeline_kind(publication.classification),
            "label": publication.source_title,
            "start_on": publication.published_at.date().isoformat() if publication.published_at else None,
            "end_on": None,
            "evidence": list(publication.evidence[:3]),
        }
        for publication in ordered
    ]
    payload = {
        "source_publisher": FASIE_SOURCE_PUBLISHER,
        "organizer": organizer,
        "origin_kind": origin_kind,
        "origin_urls": origin_urls,
        "opportunity_type": opportunity_type,
        "source_status": source_status,
        "source_lifecycle_state": "archived" if source_status == "completed" else source_status,
        "source_publications": [_serialize_publication(publication) for publication in ordered],
        "application": application,
        "timeline": timeline,
        "funding": _funding_payload(latest_funding.funding if latest_funding else None, latest_funding.funding_evidence if latest_funding else None),
        "taxonomy": {"themes": themes, "geographies": geographies},
        "eligibility": {"summary": eligibility, "evidence": eligibility},
        "contacts": contacts,
        "summary": summary,
        "sections": sections,
        "links": {
            "application_candidates": application_urls,
            "origin_urls": origin_urls,
            "reference_urls": reference_urls,
            "document_urls": [item["url"] for item in documents],
            "result_urls": [publication.url for publication in ordered if publication.classification == "result"],
            "source_publication_urls": [publication.url for publication in ordered],
        },
        "content_inventory": {
            "raw_capture_contains_full_content": all(
                publication.full_page_content for publication in ordered
            ),
            "blocks": [
                {"url": publication.url, "heading": publication.source_title, "text": " ".join(publication.evidence[:8])}
                for publication in ordered
            ],
        },
        "artifacts": [
            {**item, "collection": "fetch"}
            for item in documents[:12]
        ],
        "artifact_summary": {"discovered": min(len(documents), 12), "captured": 0, "deferred": max(0, len(documents) - 12)},
    }
    warnings = [issue.code for issue in issues]
    if latest_funding is None and opportunity_type in {"rating", "accelerator", "contest", "other"}:
        warnings.append("funding_not_applicable_or_not_stated")
    record = {
        "record_key": key,
        "title": source_title,
        "record_url": record_url,
        "deadline_on": end_on.isoformat() if end_on else None,
        "funding": latest_funding.funding.model_dump(mode="json", exclude_none=True) if latest_funding else None,
        "payload": payload,
        "warnings": list(dict.fromkeys(warnings)),
    }
    return _GroupedRecord(
        key,
        record_url,
        canonical.url,
        record,
        tuple(ordered),
    ), tuple(issues)


def _group_publications(
    publications: Sequence[ParsedPublication],
    *,
    as_of: datetime,
    cutoff: date,
) -> tuple[tuple[_GroupedRecord, ...], tuple[ParserIssue, ...]]:
    """Group deterministic identities and explicit press-to-press links.

    An FASIE announcement can infer one name from its prose while explicitly
    linking to the canonical card under another name.  Treat that link as a
    graph edge, not as a one-way identity overwrite.  Otherwise an older
    sibling still under the inferred identity can produce a second group with
    the same final record key.
    """

    groups: dict[str, list[ParsedPublication]] = {}
    standalone: list[ParsedPublication] = []
    issues: list[ParserIssue] = []
    by_url = {publication.url: publication for publication in publications}
    parent = {
        publication.identity: publication.identity
        for publication in publications
        if publication.identity is not None
    }

    def find(identity: str) -> str:
        root = parent[identity]
        while root != parent[root]:
            root = parent[root]
        while identity != root:
            next_identity = parent[identity]
            parent[identity] = root
            identity = next_identity
        return root

    def merge(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        # A lexicographic root makes record keys stable if card ordering in
        # the source feed changes between runs.
        parent[max(left_root, right_root)] = min(left_root, right_root)

    related_identities_by_url: dict[str, set[str]] = {}
    for publication in publications:
        related_identities = {
            target.identity
            for url in publication.related_publication_urls
            if (target := by_url.get(url)) is not None and target.identity is not None
        }
        related_identities_by_url[publication.url] = related_identities
        if len(related_identities) > 1:
            issues.append(
                ParserIssue(
                    "warning",
                    "related_publication_ambiguous",
                    "identity",
                    "A publication links to more than one identifiable FASIE competition.",
                )
            )
            continue
        if publication.identity is None or not related_identities:
            continue
        related_identity = next(iter(related_identities))
        if publication.identity != related_identity:
            issues.append(
                ParserIssue(
                    "warning",
                    "related_publication_identity_override",
                    "identity",
                    "An explicit FASIE press link merged conflicting inferred identities.",
                )
            )
            merge(publication.identity, related_identity)

    component_targets: dict[str, set[str]] = {}
    for publication in publications:
        if publication.classification == "ignore":
            continue
        related_identities = related_identities_by_url[publication.url]
        if publication.identity is not None:
            component = find(publication.identity)
            groups.setdefault(component, []).append(publication)
            if len(related_identities) == 1:
                component_targets.setdefault(component, set()).update(related_identities)
            continue
        if len(related_identities) == 1:
            related_identity = next(iter(related_identities))
            component = find(related_identity)
            groups.setdefault(component, []).append(publication)
            component_targets.setdefault(component, set()).add(related_identity)
            continue
        if (
            publication.classification == "opportunity"
            and publication.origin_kind == "first_party"
            and (
                publication.funding is not None
                or any((urlsplit(url).hostname or "").casefold() == "online.fasie.ru" for url in publication.application_urls)
            )
        ):
            standalone.append(publication)
            continue
        if publication.classification == "opportunity":
            # Partner rankings, forum invitations and benefits for existing
            # winners are FASIE news, not FASIE grant-program candidates.
            continue
        else:
            issues.append(
                ParserIssue(
                    "warning",
                    "publication_identity_missing",
                    "identity",
                    f"Skipped {publication.classification} publication without deterministic identity: {publication.url}",
                )
            )
    records: list[_GroupedRecord] = []
    for component, values in groups.items():
        identity_override = min(component_targets.get(component, {component}))
        record, group_issues = _build_grouped_record(
            values,
            as_of=as_of,
            cutoff=cutoff,
            identity_override=identity_override,
        )
        issues.extend(group_issues)
        if record is not None:
            records.append(record)
    for publication in standalone:
        record, group_issues = _build_grouped_record(
            (publication,),
            as_of=as_of,
            cutoff=cutoff,
        )
        issues.extend(group_issues)
        if record is not None:
            records.append(record)
    records.sort(key=lambda item: item.record_url)
    return tuple(records), tuple(issues)


def _competition_match_key(value: str) -> str:
    """Normalize the public portal's short labels to FASIE press naming."""

    normalized = normalize_identity_name(value)
    normalized = re.sub(r"\b20\d{2}\b", " ", normalized)
    normalized = re.sub(r"\bочередь\s+\d+\b", " ", normalized)
    # The public portal calls the medical-device track ``Старт-Мед-1`` while
    # the Fund press and programme table use ``Старт-Медизделия-1``.
    normalized = re.sub(r"\bмед\s+(?=\d|$)", "медизделия ", normalized)
    return " ".join(normalized.split())


def _queue_from_value(value: str) -> str | None:
    match = re.search(r"\bочеред(?:ь|и)\s*(?:№\s*)?(\d+)\b", value, re.IGNORECASE)
    return match.group(1) if match else None


def _online_matches_group(online: OnlineCompetition, group: _GroupedRecord) -> bool:
    online_key = _competition_match_key(online.name)
    online_queue = _queue_from_value(online.name)
    for publication in group.publications:
        candidates = [publication.identity_name, publication.title, publication.source_title]
        if not any(
            isinstance(value, str) and _competition_match_key(value) == online_key
            for value in candidates
        ):
            continue
        if online_queue is not None and publication.queue is not None and online_queue != publication.queue:
            continue
        # ``get-public-common-info`` is the portal data which powers the
        # public "до …" label.  Its deadline can legitimately differ from an
        # older press launch or extension notice; that is an update, not proof
        # that two similarly named competitions are unrelated.
        return True
    return False


def _append_unique_url_item(target: list[dict[str, str]], item: dict[str, str]) -> None:
    if item not in target:
        target.append(item)


def _apply_program_catalog_entry(group: _GroupedRecord, entry: ProgramCatalogEntry) -> None:
    record = group.payload
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return
    catalog_entries = payload.setdefault("program_catalog", [])
    if not isinstance(catalog_entries, list):
        catalog_entries = []
        payload["program_catalog"] = catalog_entries
    catalog_value = {
        "name": entry.name,
        "program_name": entry.program_name,
        "source_url": entry.source_url,
        "detail_url": entry.detail_url,
        "source_status": entry.source_status,
        "deadline_on": entry.deadline_on.isoformat() if entry.deadline_on else None,
        "status_evidence": entry.status_evidence,
    }
    if catalog_value not in catalog_entries:
        catalog_entries.append(catalog_value)
    sections = payload.setdefault("sections", {})
    if isinstance(sections, dict) and entry.conditions:
        heading = f"Условия программы: {entry.program_name or entry.name}"
        sections.setdefault(heading, entry.conditions)
    taxonomy = payload.setdefault("taxonomy", {})
    themes = taxonomy.setdefault("themes", []) if isinstance(taxonomy, dict) else []
    if isinstance(themes, list) and entry.program_name:
        theme = {
            "slug": f"fasie-program-{stable_hash(entry.program_name)[:12]}",
            "name": entry.program_name,
        }
        if theme not in themes:
            themes.append(theme)
    links = payload.setdefault("links", {})
    artifacts = payload.setdefault("artifacts", [])
    document_urls = links.setdefault("document_urls", []) if isinstance(links, dict) else []
    if not isinstance(artifacts, list):
        artifacts = []
        payload["artifacts"] = artifacts
    for document in entry.document_urls:
        if isinstance(document_urls, list) and document["url"] not in document_urls:
            document_urls.append(document["url"])
        artifact = {**document, "collection": "fetch"}
        _append_unique_url_item(artifacts, artifact)
    if record.get("funding") is None and entry.funding is not None:
        record["funding"] = entry.funding.model_dump(mode="json", exclude_none=True)
        payload["funding"] = _funding_payload(entry.funding, entry.funding_evidence)
    application = payload.get("application")
    if isinstance(application, dict) and application.get("end_on") is None and entry.deadline_on is not None:
        application["end_on"] = entry.deadline_on.isoformat()
        application["end_at"] = datetime.combine(
            entry.deadline_on,
            time(23, 59, 59, 999999),
            tzinfo=FASIE_TZ,
        ).isoformat()
        application.setdefault("date_evidence", []).append(entry.status_evidence)
        record["deadline_on"] = entry.deadline_on.isoformat()
    current_status = payload.get("source_status")
    if current_status != "completed":
        if entry.source_status == "open":
            payload["source_status"] = "open"
            payload["source_lifecycle_state"] = "open"
        elif current_status == "unknown" and entry.source_status in {"closed", "upcoming"}:
            payload["source_status"] = entry.source_status
            payload["source_lifecycle_state"] = entry.source_status


def _online_only_group(online: OnlineCompetition) -> _GroupedRecord:
    identity = f"{online.name}|{online.deadline_on or '-'}"
    key = f"fasie:online:{stable_hash(identity)}"
    application = {
        "start_on": None,
        "end_on": online.deadline_on.isoformat() if online.deadline_on else None,
        "start_at": None,
        "end_at": (
            datetime.combine(online.deadline_on, time(23, 59, 59, 999999), tzinfo=FASIE_TZ).isoformat()
            if online.deadline_on
            else None
        ),
        "url": None,
        "candidate_urls": [],
        "date_evidence": [online.evidence],
    }
    payload = {
        "source_publisher": FASIE_SOURCE_PUBLISHER,
        "organizer": FASIE_SOURCE_PUBLISHER,
        "origin_kind": "first_party",
        "origin_urls": [],
        "opportunity_type": "grant",
        "source_status": "open",
        "source_lifecycle_state": "open",
        "source_publications": [
            {
                "url": online.source_url,
                "published_at": None,
                "type": "online_status",
                "title": online.name,
                "identity": None,
                "evidence": [online.evidence],
            }
        ],
        "application": application,
        "timeline": [
            {
                "kind": "application",
                "label": "Статус открытого конкурса на online.fasie.ru",
                "start_on": None,
                "end_on": online.deadline_on.isoformat() if online.deadline_on else None,
                "evidence": [online.evidence],
            }
        ],
        "funding": _funding_payload(None, None),
        "taxonomy": {"themes": [], "geographies": []},
        "eligibility": {"summary": None, "evidence": None},
        "contacts": [],
        "summary": None,
        "sections": {},
        "links": {
            "application_candidates": [],
            "origin_urls": [],
            "reference_urls": [online.source_url],
            "document_urls": [],
            "result_urls": [],
            "source_publication_urls": [online.source_url],
        },
        "content_inventory": {
            "raw_capture_contains_full_content": True,
            "blocks": [{"url": online.source_url, "heading": online.name, "text": online.evidence}],
        },
        "artifacts": [],
        "artifact_summary": {"discovered": 0, "captured": 0, "deferred": 0},
        "online_status": [
            {
                "name": online.name,
                "deadline_on": online.deadline_on.isoformat() if online.deadline_on else None,
                "source_url": online.source_url,
                "evidence": online.evidence,
            }
        ],
    }
    record = {
        "record_key": key,
        "title": online.name,
        "record_url": online.source_url,
        "deadline_on": online.deadline_on.isoformat() if online.deadline_on else None,
        "funding": None,
        "payload": payload,
        "warnings": ["online_competition_without_press_publication"],
    }
    return _GroupedRecord(key, online.source_url, online.source_url, record)


def _enrich_groups(
    groups: Sequence[_GroupedRecord],
    *,
    program_entries: Sequence[ProgramCatalogEntry],
    online_competitions: Sequence[OnlineCompetition],
) -> tuple[_GroupedRecord, ...]:
    enriched = list(groups)
    for group in enriched:
        publication_urls = {
            url
            for publication in group.publications
            for url in (publication.url, *publication.related_publication_urls)
        }
        for entry in program_entries:
            if entry.detail_url is not None and entry.detail_url in publication_urls:
                _apply_program_catalog_entry(group, entry)
        online_matches = [online for online in online_competitions if _online_matches_group(online, group)]
        if not online_matches:
            continue
        payload = group.payload.get("payload")
        if not isinstance(payload, dict):
            continue
        payload["source_status"] = "open"
        payload["source_lifecycle_state"] = "open"
        statuses = payload.setdefault("online_status", [])
        if not isinstance(statuses, list):
            statuses = []
            payload["online_status"] = statuses
        application = payload.get("application")
        for online in online_matches:
            value = {
                "name": online.name,
                "deadline_on": online.deadline_on.isoformat() if online.deadline_on else None,
                "source_url": online.source_url,
                "evidence": online.evidence,
            }
            if value not in statuses:
                statuses.append(value)
            if isinstance(application, dict) and online.deadline_on is not None:
                online_deadline = online.deadline_on.isoformat()
                previous_deadline = application.get("end_on")
                if previous_deadline != online_deadline:
                    application["end_on"] = online_deadline
                    application["end_at"] = datetime.combine(
                        online.deadline_on,
                        time(23, 59, 59, 999999),
                        tzinfo=FASIE_TZ,
                    ).isoformat()
                    application.setdefault("date_evidence", []).append(online.evidence)
                    group.payload["deadline_on"] = online_deadline
                    if isinstance(previous_deadline, str):
                        warnings = list(group.payload.get("warnings", []))
                        warnings.append("online_deadline_overrides_press_deadline")
                        group.payload["warnings"] = list(dict.fromkeys(warnings))
    unmatched = [
        online
        for online in online_competitions
        if not any(_online_matches_group(online, group) for group in enriched)
    ]
    enriched.extend(_online_only_group(online) for online in unmatched)
    enriched.sort(key=lambda item: item.record_url)
    return tuple(enriched)


class FasieCompetitionsAdapter:
    """Bounded parser for current FASIE opportunities published in the fund press feed."""

    name = FASIE_ADAPTER_NAME
    version = FASIE_ADAPTER_VERSION

    def __init__(self, *, fetcher: ResponseFetcher | None = None) -> None:
        self._fetcher = fetcher
        self._last_request_at: float | None = None

    def _pace_request(self, context: AdapterContext) -> None:
        """Keep live FASIE runs polite without slowing fixture-based tests."""

        config = context.source.fasie
        if self._fetcher is not None or config is None or self._last_request_at is None:
            return
        delay = config.min_request_interval_seconds - (monotonic() - self._last_request_at)
        if delay <= 0:
            return
        if delay >= context.require_time_remaining():
            raise AdapterRunTimeoutError(
                "FASIE request pacing would exceed the configured run-time budget."
            )
        sleep(delay)

    def _get(self, resource: DiscoveredResource, context: AdapterContext) -> FetchResult:
        requested_url = context.require_allowed_url(resource.url)
        def validate_redirect(url: str) -> str:
            allowed_url = context.require_allowed_url(url)
            kind = resource.metadata.get("kind")
            if kind == _KIND_HOME:
                return normalize_fasie_url(allowed_url, allow_query=False)
            if kind == _KIND_FEED:
                return feed_page_url(allowed_url)
            if kind == _KIND_ONLINE:
                return normalize_online_fasie_api_url(allowed_url)
            if kind == _KIND_PROGRAMS_INDEX:
                return programs_index_url(allowed_url)
            if kind == _KIND_PROGRAM_PAGE:
                return program_page_url(allowed_url)
            if kind == _KIND_COMPETITIONS_ARCHIVE:
                return competitions_archive_url(allowed_url)
            if kind == _KIND_PUBLICATION:
                return press_detail_url(allowed_url)
            if kind == _KIND_ARTIFACT:
                return normalize_upload_url(allowed_url)
            return allowed_url

        fetcher = self._fetcher or UrllibResponseFetcher(
            redirect_validator=validate_redirect,
            user_agent=_FASIE_USER_AGENT,
        )
        response: HttpResponse = fetcher.get(
            requested_url,
            timeout_seconds=context.request_timeout_seconds(),
            max_response_bytes=context.limits.max_response_bytes,
        )
        return fetch_result_from_response(resource, response, context)

    def _post_json(
        self,
        resource: DiscoveredResource,
        context: AdapterContext,
        *,
        payload: dict[str, object],
    ) -> FetchResult:
        requested_url = context.require_allowed_url(resource.url)

        def validate_redirect(url: str) -> str:
            allowed_url = context.require_allowed_url(url)
            if resource.metadata.get("kind") == _KIND_ONLINE:
                return normalize_online_fasie_api_url(allowed_url)
            return allowed_url

        fetcher = self._fetcher or UrllibResponseFetcher(
            redirect_validator=validate_redirect,
            user_agent=_FASIE_USER_AGENT,
        )
        post_json = getattr(fetcher, "post_json", None)
        if not callable(post_json):
            raise TypeError("FASIE online inventory requires a fetcher with post_json support")
        response: HttpResponse = post_json(
            requested_url,
            payload=payload,
            timeout_seconds=context.request_timeout_seconds(),
            max_response_bytes=context.limits.max_response_bytes,
        )
        return fetch_result_from_response(resource, response, context)

    def fetch(self, resource: DiscoveredResource, context: AdapterContext) -> FetchResult:
        kind = resource.metadata.get("kind")
        if kind == _KIND_HOME:
            normalize_fasie_url(resource.url, allow_query=False)
        elif kind == _KIND_FEED:
            feed_page_url(resource.url)
        elif kind == _KIND_ONLINE:
            normalize_online_fasie_api_url(resource.url)
        elif kind == _KIND_PROGRAMS_INDEX:
            programs_index_url(resource.url)
        elif kind == _KIND_PROGRAM_PAGE:
            program_page_url(resource.url)
        elif kind == _KIND_COMPETITIONS_ARCHIVE:
            competitions_archive_url(resource.url)
        elif kind == _KIND_PUBLICATION:
            press_detail_url(resource.url)
        elif kind == _KIND_ARTIFACT:
            normalize_upload_url(resource.url)
        else:
            raise ValueError("resource is not a supported FASIE discovery, publication, or artifact URL")
        if kind == _KIND_ONLINE:
            fetched = self._post_json(
                resource,
                context,
                payload={"newsShowOnStartPage": True, "newsShowOnInnerPages": False},
            )
        else:
            fetched = self._get(resource, context)
        if kind == _KIND_HOME:
            final_url = normalize_fasie_url(fetched.final_url, allow_query=False)
        elif kind == _KIND_FEED:
            final_url = feed_page_url(fetched.final_url)
        elif kind == _KIND_ONLINE:
            final_url = normalize_online_fasie_api_url(fetched.final_url)
        elif kind == _KIND_PROGRAMS_INDEX:
            final_url = programs_index_url(fetched.final_url)
        elif kind == _KIND_PROGRAM_PAGE:
            final_url = program_page_url(fetched.final_url)
        elif kind == _KIND_COMPETITIONS_ARCHIVE:
            final_url = competitions_archive_url(fetched.final_url)
        elif kind == _KIND_PUBLICATION:
            final_url = press_detail_url(fetched.final_url)
        else:
            final_url = normalize_upload_url(fetched.final_url)
        return replace(fetched, final_url=final_url)

    def _capture(
        self,
        resource: DiscoveredResource,
        context: AdapterContext,
        *,
        captures: list[FetchResult],
        issues: list[AdapterIssue],
        request_count: int,
        response_bytes: int,
        error_code: str,
        artifact: bool = False,
    ) -> tuple[FetchResult | None, int, int, bool]:
        if request_count >= context.limits.max_requests:
            issues.append(
                AdapterIssue(
                    stage=AdapterStage.DISCOVER,
                    severity="warning" if artifact else "error",
                    code="artifact_request_limit_reached" if artifact else "request_limit_reached",
                    message="The request limit was reached before this resource could be fetched.",
                    resource_key=resource.external_key,
                )
            )
            return None, request_count, response_bytes, False
        try:
            context.require_time_remaining()
            self._pace_request(context)
            request_count += 1
            try:
                fetched = self.fetch(resource, context)
            finally:
                # Pace both successful requests and rejected attempts.  A
                # temporary source-side refusal must not make the next call
                # immediate if a future caller elects to continue the run.
                if self._fetcher is None:
                    self._last_request_at = monotonic()
        except AdapterRunTimeoutError as error:
            issues.append(
                AdapterIssue(
                    stage=AdapterStage.DISCOVER,
                    severity="warning" if artifact else "error",
                    code="run_time_limit_reached",
                    message=str(error),
                    resource_key=resource.external_key,
                )
            )
            return None, request_count, response_bytes, False
        except UrlAllowlistError as error:
            issues.append(
                AdapterIssue(
                    stage=AdapterStage.DISCOVER,
                    severity="warning" if artifact else "error",
                    code="url_not_allowed",
                    message=str(error),
                    resource_key=resource.external_key,
                )
            )
            return None, request_count, response_bytes, False
        except SourceFetchError as error:
            restricted = bool(re.search(r"\bHTTP (?:403|429)\b", str(error)))
            issues.append(
                AdapterIssue(
                    stage=AdapterStage.DISCOVER,
                    severity="warning" if artifact else "error",
                    code="source_access_restricted" if restricted else error_code,
                    message=(
                        "FASIE temporarily rejected access (HTTP 403/429); no further requests were made."
                        if restricted
                        else str(error)
                    ),
                    resource_key=resource.external_key,
                )
            )
            return None, request_count, response_bytes, restricted
        except Exception as error:
            issues.append(
                AdapterIssue(
                    stage=AdapterStage.DISCOVER,
                    severity="warning" if artifact else "error",
                    code=error_code,
                    message=str(error),
                    resource_key=resource.external_key,
                )
            )
            return None, request_count, response_bytes, False
        if response_bytes + len(fetched.content) > context.limits.max_total_bytes:
            issues.append(
                AdapterIssue(
                    stage=AdapterStage.DISCOVER,
                    severity="warning" if artifact else "error",
                    code="artifact_response_limit_reached" if artifact else "response_limit_reached",
                    message=(
                        "The linked artifact exceeded the total response-size budget and was left as a reference."
                        if artifact
                        else "The total response-size limit was reached before this resource could be retained."
                    ),
                    resource_key=resource.external_key,
                )
            )
            return None, request_count, response_bytes, True
        captures.append(fetched)
        return fetched, request_count, response_bytes + len(fetched.content), False

    def discover(self, context: AdapterContext) -> DiscoveryResult:
        config = context.source.fasie
        if config is None:
            raise ValueError("fasie-competitions requires fasie configuration")
        self._last_request_at = None
        captures: list[FetchResult] = []
        issues: list[AdapterIssue] = []
        request_count = 0
        response_bytes = 0
        home_url = normalize_fasie_url(config.home_url, allow_query=False)
        online_url = normalize_online_fasie_url(config.online_competitions_url)
        online_api_url = normalize_online_fasie_api_url(config.online_competitions_api_url)
        programs_url = programs_index_url(config.programs_url)
        archive_url = competitions_archive_url(config.competitions_archive_url)
        as_of = context.started_at.astimezone(FASIE_TZ)
        cutoff = as_of.date() - timedelta(days=config.lookback_days)
        # FASIE renders DATE_FROM/DATE_TILL back into the form but currently
        # does not apply them to the result set.  Use the real chronological
        # feed and enforce the cutoff locally, rather than trusting a silently
        # ignored server-side filter.
        feed_url = feed_page_url(config.press_feed_url)
        home_resource = _home_resource(home_url)
        home_capture, request_count, response_bytes, total_limit_reached = self._capture(
            home_resource,
            context,
            captures=captures,
            issues=issues,
            request_count=request_count,
            response_bytes=response_bytes,
            error_code="home_fetch_failed",
        )
        home_urls: list[str] = []
        if home_capture is not None and "html" in home_capture.content_format.casefold():
            home_parsed = parse_home_page(home_capture.content, source_url=home_capture.final_url)
            issues.extend(_parser_issue_to_adapter(issue, home_resource.external_key) for issue in home_parsed.issues)
            home_urls.extend(home_parsed.competition_urls)

        online_competitions: list[OnlineCompetition] = []
        online_capture: FetchResult | None = None
        online_capture_index: int | None = None
        online_resource = _online_resource(online_api_url, public_url=online_url)
        if not total_limit_reached:
            online_capture, request_count, response_bytes, capture_total_limit = self._capture(
                online_resource,
                context,
                captures=captures,
                issues=issues,
                request_count=request_count,
                response_bytes=response_bytes,
                error_code="online_competitions_fetch_failed",
            )
            total_limit_reached = total_limit_reached or capture_total_limit
            if online_capture is not None:
                online_capture_index = len(captures) - 1
                if "json" not in online_capture.content_format.casefold():
                    issues.append(
                        AdapterIssue(
                            stage=AdapterStage.DISCOVER,
                            severity="error",
                            code="unexpected_online_competitions_content_type",
                            message="FASIE online competition inventory API must return JSON.",
                            resource_key=online_resource.external_key,
                        )
                    )
                else:
                    parsed_online = parse_online_competitions_api(
                        online_capture.content,
                        source_url=online_url,
                    )
                    online_competitions.extend(parsed_online.entries)
                    issues.extend(
                        _parser_issue_to_adapter(issue, online_resource.external_key)
                        for issue in parsed_online.issues
                    )

        program_entries: list[ProgramCatalogEntry] = []
        programs_index_resource = _programs_index_resource(programs_url)
        if not total_limit_reached:
            programs_capture, request_count, response_bytes, capture_total_limit = self._capture(
                programs_index_resource,
                context,
                captures=captures,
                issues=issues,
                request_count=request_count,
                response_bytes=response_bytes,
                error_code="programs_index_fetch_failed",
            )
            total_limit_reached = total_limit_reached or capture_total_limit
            if programs_capture is not None:
                if "html" not in programs_capture.content_format.casefold():
                    issues.append(
                        AdapterIssue(
                            stage=AdapterStage.DISCOVER,
                            severity="error",
                            code="unexpected_programs_index_content_type",
                            message="FASIE programs index must be HTML.",
                            resource_key=programs_index_resource.external_key,
                        )
                    )
                else:
                    parsed_index = parse_programs_index_page(
                        programs_capture.content,
                        source_url=programs_capture.final_url,
                    )
                    issues.extend(
                        _parser_issue_to_adapter(issue, programs_index_resource.external_key)
                        for issue in parsed_index.issues
                    )
                    program_urls = list(parsed_index.program_urls)
                    if len(program_urls) > config.max_program_pages:
                        issues.append(
                            AdapterIssue(
                                stage=AdapterStage.DISCOVER,
                                severity="warning",
                                code="program_page_limit_reached",
                                message=(
                                    "FASIE programs index exposed more pages than the configured "
                                    f"limit ({config.max_program_pages})."
                                ),
                                resource_key=programs_index_resource.external_key,
                            )
                        )
                        program_urls = program_urls[: config.max_program_pages]
                    for program_url in program_urls:
                        if total_limit_reached:
                            break
                        resource = _program_page_resource(program_url)
                        fetched, request_count, response_bytes, capture_total_limit = self._capture(
                            resource,
                            context,
                            captures=captures,
                            issues=issues,
                            request_count=request_count,
                            response_bytes=response_bytes,
                            error_code="program_page_fetch_failed",
                        )
                        if capture_total_limit:
                            total_limit_reached = True
                            break
                        if fetched is None:
                            continue
                        if "html" not in fetched.content_format.casefold():
                            issues.append(
                                AdapterIssue(
                                    stage=AdapterStage.DISCOVER,
                                    severity="error",
                                    code="unexpected_program_page_content_type",
                                    message="FASIE program page must be HTML.",
                                    resource_key=resource.external_key,
                                )
                            )
                            continue
                        parsed_program = parse_program_page(fetched.content, source_url=fetched.final_url)
                        program_entries.extend(parsed_program.entries)
                        issues.extend(
                            _parser_issue_to_adapter(issue, resource.external_key)
                            for issue in parsed_program.issues
                        )

        archive_entries: list[ArchivePublication] = []
        archive_capture: FetchResult | None = None
        archive_capture_index: int | None = None
        archive_resource = _competitions_archive_resource(archive_url)
        if not total_limit_reached:
            archive_capture, request_count, response_bytes, capture_total_limit = self._capture(
                archive_resource,
                context,
                captures=captures,
                issues=issues,
                request_count=request_count,
                response_bytes=response_bytes,
                error_code="competitions_archive_fetch_failed",
            )
            total_limit_reached = total_limit_reached or capture_total_limit
            if archive_capture is not None:
                archive_capture_index = len(captures) - 1
                if "html" not in archive_capture.content_format.casefold():
                    issues.append(
                        AdapterIssue(
                            stage=AdapterStage.DISCOVER,
                            severity="error",
                            code="unexpected_competitions_archive_content_type",
                            message="FASIE competitions archive must be HTML.",
                            resource_key=archive_resource.external_key,
                        )
                    )
                else:
                    parsed_archive = parse_competitions_archive_page(
                        archive_capture.content,
                        source_url=archive_capture.final_url,
                    )
                    archive_entries.extend(parsed_archive.entries)
                    issues.extend(
                        _parser_issue_to_adapter(issue, archive_resource.external_key)
                        for issue in parsed_archive.issues
                    )
                    if len(archive_entries) > config.max_archive_entries:
                        issues.append(
                            AdapterIssue(
                                stage=AdapterStage.DISCOVER,
                                severity="warning",
                                code="archive_entry_limit_reached",
                                message=(
                                    "FASIE competitions archive exposed more entries than the configured "
                                    f"limit ({config.max_archive_entries})."
                                ),
                                resource_key=archive_resource.external_key,
                            )
                        )
                        archive_entries = archive_entries[: config.max_archive_entries]

        feed_entries: dict[str, Any] = {}
        seen_pages: set[str] = set()
        current_url: str | None = feed_url
        pages = 0
        while current_url is not None and pages < config.max_feed_pages and not total_limit_reached:
            if current_url in seen_pages:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="feed_pager_loop",
                        message="The FASIE feed pagination looped.",
                        resource_key=_feed_resource(current_url).external_key,
                    )
                )
                break
            seen_pages.add(current_url)
            pages += 1
            resource = _feed_resource(current_url)
            fetched, request_count, response_bytes, capture_total_limit = self._capture(
                resource,
                context,
                captures=captures,
                issues=issues,
                request_count=request_count,
                response_bytes=response_bytes,
                error_code="feed_fetch_failed",
            )
            if capture_total_limit:
                total_limit_reached = True
                break
            if fetched is None:
                break
            if "html" not in fetched.content_format.casefold():
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="unexpected_feed_content_type",
                        message="FASIE feed page must be HTML.",
                        resource_key=resource.external_key,
                    )
                )
                break
            parsed = parse_feed_page(fetched.content, source_url=fetched.final_url)
            issues.extend(_parser_issue_to_adapter(issue, resource.external_key) for issue in parsed.issues)
            in_window_entries = [
                entry
                for entry in parsed.entries
                if entry.published_at is None or entry.published_at.date() >= cutoff
            ]
            for entry in in_window_entries:
                if entry.is_likely_lifecycle_event:
                    feed_entries.setdefault(entry.url, entry)
            if parsed.entries and any(entry.published_at is None for entry in parsed.entries):
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="feed_cutoff_date_unavailable",
                        message="A feed page contained a publication without a valid date; cutoff completeness is limited.",
                        resource_key=resource.external_key,
                    )
                )
            # The public feed is newest-first.  Once a complete page is older
            # than the configured retention boundary, later pages cannot add
            # a current lifecycle event.  A missing/unparseable date disables
            # this early exit so the configured page cap remains the safe
            # fallback instead of silently losing a card.
            if parsed.entries and all(
                entry.published_at is not None and entry.published_at.date() < cutoff
                for entry in parsed.entries
            ):
                break
            if not parsed.next_url:
                break
            current_url = parsed.next_url
        else:
            if current_url is not None and not total_limit_reached:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="feed_page_limit_reached",
                        message=f"FASIE feed page limit ({config.max_feed_pages}) was reached.",
                        resource_key=_feed_resource(current_url).external_key,
                    )
                )

        candidate_urls = list(home_urls)
        candidate_hints: dict[str, tuple[datetime | None, str]] = {}
        for entry in program_entries:
            if entry.detail_url is not None and entry.detail_url not in candidate_urls:
                candidate_urls.append(entry.detail_url)
        for entry in feed_entries.values():
            candidate_hints[entry.url] = (entry.published_at, entry.title)
            if entry.url not in candidate_urls:
                candidate_urls.append(entry.url)
        feed_positions = {
            url: position
            for position, url in enumerate(feed_entries, 1)
        }
        publications: list[ParsedPublication] = []
        publication_captures: dict[str, tuple[int, FetchResult]] = {}
        # An open contest can appear in the public portal before FASIE has
        # published a linked press notice.  Its card still has authoritative
        # raw evidence: map the user-facing portal URL to the JSON capture.
        if online_capture is not None and online_capture_index is not None:
            publication_captures[online_url] = (online_capture_index, online_capture)
        for index, url in enumerate(candidate_urls, 1):
            if total_limit_reached:
                break
            hint = candidate_hints.get(url)
            entry = feed_entries.get(url)
            published_at = entry.published_at if entry is not None else (hint[0] if hint is not None else None)
            title_hint = entry.title if entry is not None else (hint[1] if hint is not None else "")
            resource = _publication_resource(url, published_at=published_at, title=title_hint)
            fetched, request_count, response_bytes, capture_total_limit = self._capture(
                resource,
                context,
                captures=captures,
                issues=issues,
                request_count=request_count,
                response_bytes=response_bytes,
                error_code="publication_fetch_failed",
            )
            if capture_total_limit:
                total_limit_reached = True
                break
            if fetched is None:
                continue
            publication_captures[url] = (len(captures) - 1, fetched)
            publication_captures[fetched.final_url] = (len(captures) - 1, fetched)
            if "html" not in fetched.content_format.casefold():
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="unexpected_publication_content_type",
                        message="FASIE publication must be HTML.",
                        resource_key=resource.external_key,
                    )
                )
                continue
            parsed = parse_publication_page(
                fetched.content,
                source_url=fetched.final_url,
                feed_published_at=published_at,
                feed_position=feed_positions.get(url),
            )
            publications.append(parsed)
            issues.extend(_parser_issue_to_adapter(issue, resource.external_key) for issue in parsed.issues)
            context.report_progress(f"публикации FASIE: {index}/{len(candidate_urls)}")

        # Archive rows are official result evidence in their own right.  Use a
        # bounded synthetic parse when the detail page was not already needed
        # by the current feed or programme table.  This preserves closed and
        # archived competitions without turning one manual run into hundreds
        # of legacy-detail and attachment downloads.
        if archive_capture is not None and archive_capture_index is not None:
            for entry in archive_entries:
                if entry.url in publication_captures:
                    continue
                parsed = replace(
                    parse_publication_page(
                        _archive_publication_stub(entry),
                        source_url=entry.url,
                        feed_published_at=entry.published_at,
                    ),
                    full_page_content=False,
                )
                publications.append(parsed)
                publication_captures[entry.url] = (archive_capture_index, archive_capture)
                issues.extend(
                    _parser_issue_to_adapter(issue, archive_resource.external_key)
                    for issue in parsed.issues
                )

        groups, group_issues = _group_publications(
            publications,
            as_of=as_of,
            cutoff=cutoff,
        )
        issues.extend(_parser_issue_to_adapter(issue, f"{FASIE_ADAPTER_NAME}:grouping") for issue in group_issues)
        groups = _enrich_groups(
            groups,
            program_entries=program_entries,
            online_competitions=online_competitions,
        )
        if len(groups) > context.limits.max_records:
            issues.append(
                AdapterIssue(
                    stage=AdapterStage.DISCOVER,
                    severity="error",
                    code="record_limit_exceeded",
                    message=f"max_records limit ({context.limits.max_records}) was exceeded.",
                )
            )
            groups = groups[: context.limits.max_records]

        artifact_urls: dict[str, set[str]] = {}
        for group in groups:
            artifacts = group.payload.get("payload", {}).get("artifacts", [])
            if isinstance(artifacts, list):
                for artifact in artifacts:
                    if isinstance(artifact, dict) and isinstance(artifact.get("url"), str):
                        artifact_urls.setdefault(artifact["url"], set()).add(group.key)
        artifact_results: dict[str, FetchResult | None] = {}
        artifact_canonical: dict[str, FetchResult] = {}
        content_hashes: dict[str, FetchResult] = {}
        artifact_failures: dict[str, str] = {}
        artifact_deferred: set[str] = set()
        artifact_deferred_reasons: dict[str, str] = {}
        artifact_fetched = 0
        artifact_attempts = 0
        artifact_budget_reported = False
        artifact_captures: list[FetchResult] = []
        for artifact_url, parent_keys in artifact_urls.items():
            if total_limit_reached:
                artifact_deferred.add(artifact_url)
                artifact_deferred_reasons[artifact_url] = "total_bytes_limit"
                continue
            if artifact_attempts >= config.max_artifact_requests:
                artifact_deferred.add(artifact_url)
                artifact_deferred_reasons[artifact_url] = "artifact_fetch_budget"
                if not artifact_budget_reported:
                    issues.append(
                        AdapterIssue(
                            stage=AdapterStage.DISCOVER,
                            severity="warning",
                            code="artifact_fetch_budget_reached",
                            message=(
                                "The configured FASIE artifact-fetch budget "
                                f"({config.max_artifact_requests}) was reached; remaining files were deferred."
                            ),
                            resource_key=f"{FASIE_ADAPTER_NAME}:artifacts",
                        )
                    )
                    artifact_budget_reported = True
                continue
            resource = _artifact_resource(artifact_url, sorted(parent_keys))
            artifact_attempts += 1
            fetched, request_count, response_bytes, capture_total_limit = self._capture(
                resource,
                context,
                captures=artifact_captures,
                issues=issues,
                request_count=request_count,
                response_bytes=response_bytes,
                error_code="artifact_fetch_failed",
                artifact=True,
            )
            if capture_total_limit:
                total_limit_reached = True
                artifact_deferred.add(artifact_url)
                artifact_deferred_reasons[artifact_url] = "total_bytes_limit"
                continue
            if fetched is None:
                if request_count >= context.limits.max_requests:
                    artifact_deferred.add(artifact_url)
                    artifact_deferred_reasons[artifact_url] = "request_limit"
                else:
                    artifact_failures[artifact_url] = "artifact_fetch_failed"
                continue
            artifact_fetched += 1
            artifact_results[artifact_url] = fetched
            content_hash = sha256(fetched.content).hexdigest()
            canonical = content_hashes.get(content_hash)
            if canonical is None:
                content_hashes[content_hash] = fetched
                artifact_canonical[artifact_url] = fetched
            else:
                artifact_canonical[artifact_url] = canonical
                fetched_aliases = canonical.resource.metadata.setdefault("alias_urls", [])
                if isinstance(fetched_aliases, list) and artifact_url not in fetched_aliases:
                    fetched_aliases.append(artifact_url)
        for group in groups:
            payload = group.payload.get("payload")
            if not isinstance(payload, dict):
                continue
            record_warnings = list(group.payload.get("warnings", []))
            artifact_entries = payload.get("artifacts", [])
            captured = 0
            deferred = 0
            if isinstance(artifact_entries, list):
                for entry in artifact_entries:
                    if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
                        continue
                    url = entry["url"]
                    fetched = artifact_results.get(url)
                    if fetched is None:
                        entry["collection_status"] = "deferred" if url in artifact_deferred else "failed"
                        entry["collection_reason"] = (
                            artifact_deferred_reasons.get(url, "request_limit")
                            if url in artifact_deferred
                            else artifact_failures.get(url, "artifact_not_captured")
                        )
                        if entry["collection_status"] == "deferred":
                            deferred += 1
                        record_warnings.append(f"{entry['collection_reason']}: {url}")
                        continue
                    canonical = artifact_canonical[url]
                    inspection = inspect_fasie_artifact(canonical.content, content_format=canonical.content_format, source_url=canonical.final_url)
                    entry.update(
                        {
                            "collection_status": "captured",
                            "capture": {
                                "resource_key": canonical.resource.external_key,
                                "source_url": url,
                                "raw_capture_source_url": canonical.final_url,
                                "content_sha256": sha256(canonical.content).hexdigest(),
                                "content_format": canonical.content_format,
                                "received_at": canonical.received_at.isoformat(),
                                "external_content_uri": canonical.external_content_uri,
                            },
                            "inspection": inspection.payload,
                        }
                    )
                    record_warnings.extend(f"{issue.code}: {issue.message}" for issue in inspection.issues)
                    captured += 1
            payload["artifact_summary"] = {"discovered": len(artifact_entries) if isinstance(artifact_entries, list) else 0, "captured": captured, "deferred": deferred}
            group.payload["warnings"] = list(dict.fromkeys(record_warnings))

        groups_by_capture: dict[int, list[_GroupedRecord]] = {}
        for group in groups:
            capture_info = publication_captures.get(group.canonical_publication_url)
            if capture_info is None:
                capture_info = next(
                    (
                        (index, capture)
                        for index, capture in enumerate(captures)
                        if capture.final_url == group.canonical_publication_url
                    ),
                    None,
                )
            if capture_info is None:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="record_capture_missing",
                        message="A FASIE record could not be linked to its raw source capture.",
                        resource_key=group.key,
                    )
                )
                continue
            capture_index, _capture = capture_info
            groups_by_capture.setdefault(capture_index, []).append(group)
        record_resources: list[DiscoveredResource] = []
        discovery_index = 1
        for capture_index, capture_groups in groups_by_capture.items():
            capture = captures[capture_index]
            metadata = dict(capture.resource.metadata)
            metadata.update(
                {
                    "kind": _KIND_RECORD,
                    "extract_record": True,
                    "discovery_index": discovery_index,
                    "record_payloads": [deepcopy(group.payload) for group in capture_groups],
                    "source_publication_urls": [group.canonical_publication_url for group in capture_groups],
                }
            )
            record_capture_resource = DiscoveredResource(
                external_key=capture.resource.external_key,
                url=capture.resource.url,
                metadata=metadata,
            )
            captures[capture_index] = replace(capture, resource=record_capture_resource)
            record_resources.extend(
                _record_resource(group, source_publication_url=capture.final_url)
                for group in capture_groups
            )
            discovery_index += len(capture_groups)
        canonical_artifact_ids = {id(item) for item in artifact_canonical.values()}
        captures.extend(
            item
            for item in artifact_captures
            if id(item) in canonical_artifact_ids
        )
        context.report_progress(f"FASIE: найдено конкурсов и программ всех статусов {len(record_resources)}")
        return DiscoveryResult(
            captures=tuple(captures),
            record_resources=tuple(record_resources),
            issues=tuple(issues),
            request_count=request_count,
            response_bytes=response_bytes,
            artifact_discovered=len(artifact_urls),
            artifact_fetched=artifact_fetched,
            artifact_deferred=len(artifact_deferred),
            coverage_scope=(
                "FASIE public open-competition inventory, programme status tables, "
                "locally date-bounded Fund press lifecycle feed, and the bounded competitions archive"
            ),
            quality_limitations=(
                "The Fund press feed is locally bounded by lookback_days and max_feed_pages; malformed or undated pagination is reported.",
                "The archive is bounded by max_archive_entries and programme discovery by max_program_pages.",
                "Lifecycle events are grouped only by deterministic identity or an explicit FASIE press-to-press link.",
                "Third-party rankings, events and benefits for existing winners are excluded from the FASIE grant queue.",
                "Application forms and external pages are references only; only the anonymous FASIE status API is read.",
                "Attachments are fetched only from FASIE /upload/ after a grouped record is formed, with a deterministic artifact-fetch budget.",
                "Raw responses remain outside PostgreSQL; staged payloads contain capture metadata and bounded inspection excerpts.",
            ),
        )

    def extract(self, fetched: FetchResult, context: AdapterContext) -> ExtractResult:
        del context
        if fetched.resource.metadata.get("kind") != _KIND_RECORD:
            return ExtractResult()
        raw_payloads = fetched.resource.metadata.get("record_payloads")
        if not isinstance(raw_payloads, list):
            legacy_payload = fetched.resource.metadata.get("record_payload")
            raw_payloads = [legacy_payload] if isinstance(legacy_payload, dict) else []
        payloads = [payload for payload in raw_payloads if isinstance(payload, dict)]
        if not payloads:
            return ExtractResult(
                issues=(
                    AdapterIssue(
                        stage=AdapterStage.EXTRACT,
                        severity="error",
                        code="record_payload_missing",
                        message="FASIE grouped record capture has no payload.",
                        resource_key=fetched.resource.external_key,
                    ),
                )
            )
        row_number = fetched.resource.metadata.get("discovery_index", 1)
        if not isinstance(row_number, int) or row_number < 1:
            row_number = 1
        return ExtractResult(
            records=tuple(
                ExtractedRecord(
                    row_number=row_number + index,
                    raw_payload=deepcopy(raw_payload),
                    capture_key=fetched.resource.external_key,
                )
                for index, raw_payload in enumerate(payloads)
            )
        )

    def validate(self, records: Sequence[ExtractedRecord], context: AdapterContext) -> ValidationResult:
        del context
        rows: list[ParsedRow] = []
        for extracted in records:
            payload = dict(extracted.raw_payload)
            parser_issues = payload.pop(_PARSER_ISSUES_KEY, [])
            row = parse_record(payload, row_number=extracted.row_number, capture_key=extracted.capture_key)
            validation_issues = list(row.issues)
            warnings = list(row.record.warnings) if row.record is not None else []
            if isinstance(parser_issues, list):
                for issue in parser_issues:
                    if not isinstance(issue, dict):
                        continue
                    code = issue.get("code")
                    message = issue.get("message")
                    if isinstance(code, str) and isinstance(message, str):
                        warnings.append(f"{code}: {message}")
            if row.record is not None and warnings != row.record.warnings:
                row = replace(row, record=row.record.model_copy(update={"warnings": list(dict.fromkeys(warnings))}))
            if validation_issues != list(row.issues):
                row = replace(row, issues=tuple(validation_issues))
            rows.append(row)
        return ValidationResult(rows=add_duplicate_key_issues(rows))

    def report(self, summary: AdapterRunSummary) -> AdapterReport:
        return adapter_report(self, summary)


def fasie_adapter() -> SourceAdapter:
    return FasieCompetitionsAdapter()

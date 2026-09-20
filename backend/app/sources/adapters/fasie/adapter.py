from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from typing import Any, Sequence
from urllib.parse import urlsplit

from app.import_bridge.contract import ParsedRow, ValidationIssue, add_duplicate_key_issues, parse_record
from app.sources.adapters.potanin.http import (
    HttpResponse,
    ResponseFetcher,
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
    feed_page_url,
    normalize_fasie_url,
    normalize_upload_url,
    press_detail_url,
    stable_hash,
)
from .parsing import (
    ParsedPublication,
    ParserIssue,
    parse_feed_page,
    parse_home_page,
    parse_publication_page,
)


FASIE_ADAPTER_NAME = "fasie-competitions"
FASIE_ADAPTER_VERSION = "1.1.0"
_FASIE_USER_AGENT = "siderfold-fasie-adapter/1.0 (+https://fasie.ru/)"
_PARSER_ISSUES_KEY = "_parser_issues"

_KIND_HOME = "fasie-home"
_KIND_FEED = "fasie-feed"
_KIND_PUBLICATION = "fasie-publication"
_KIND_RECORD = "fasie-record"
_KIND_ARTIFACT = "fasie-artifact"


@dataclass(frozen=True)
class _GroupedRecord:
    key: str
    record_url: str
    canonical_publication_url: str
    payload: dict[str, Any]


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
    source = sorted(active or list(publications), key=_publication_sort_key)[-1] if active or publications else None
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


def _build_grouped_record(
    publications: Sequence[ParsedPublication],
    *,
    as_of: datetime,
    cutoff: date,
) -> tuple[_GroupedRecord | None, tuple[ParserIssue, ...]]:
    ordered = sorted(publications, key=_publication_sort_key)
    issues: list[ParserIssue] = []
    if not ordered:
        return None, ()
    last = ordered[-1]
    non_results = [publication for publication in ordered if publication.classification != "result"]
    if last.classification == "result":
        return None, ()
    if last.classification == "amendment" and not any(
        publication.classification in {"launch", "extension", "opportunity"} for publication in ordered
    ):
        issues.append(
            ParserIssue(
                "warning",
                "orphan_amendment_skipped",
                "identity",
                "An amendment without an identified active opportunity was skipped.",
            )
        )
        return None, tuple(issues)
    start_on, end_on, start_at, end_at, date_evidence, _date_sources = _application_values(ordered)
    if end_at is not None and end_at < as_of:
        return None, ()
    if end_at is None:
        issues.append(
            ParserIssue(
                "warning",
                "deadline_missing",
                "deadline_on",
                "The opportunity is explicitly current but no application deadline was found.",
            )
        )
    if not any(publication.classification in {"launch", "extension", "amendment", "opportunity"} for publication in ordered):
        return None, ()
    identity = next((publication.identity for publication in ordered if publication.identity), None)
    if identity is None:
        key = f"fasie:publication:{stable_hash(last.url)}"
        record_url = last.url
    else:
        key = f"fasie:competition:{stable_hash(identity)}"
        active_urls = [publication.url for publication in non_results if publication.published_at is not None or publication.url]
        record_url = active_urls[-1] if active_urls else ordered[-1].url
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
            "kind": publication.classification,
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
        "source_status": "open",
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
            "raw_capture_contains_full_content": True,
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
    return _GroupedRecord(key, record_url, record_url, record), tuple(issues)


def _group_publications(
    publications: Sequence[ParsedPublication],
    *,
    as_of: datetime,
    cutoff: date,
) -> tuple[tuple[_GroupedRecord, ...], tuple[ParserIssue, ...]]:
    groups: dict[str, list[ParsedPublication]] = {}
    standalone: list[ParsedPublication] = []
    issues: list[ParserIssue] = []
    for publication in publications:
        if publication.classification == "ignore":
            continue
        if publication.identity is not None:
            groups.setdefault(publication.identity, []).append(publication)
        elif publication.classification == "opportunity":
            standalone.append(publication)
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
    for values in (*groups.values(), *(tuple([item]) for item in standalone)):
        record, group_issues = _build_grouped_record(values, as_of=as_of, cutoff=cutoff)
        issues.extend(group_issues)
        if record is not None:
            records.append(record)
    records.sort(key=lambda item: item.record_url)
    return tuple(records), tuple(issues)


class FasieCompetitionsAdapter:
    """Bounded parser for current FASIE opportunities published in the fund press feed."""

    name = FASIE_ADAPTER_NAME
    version = FASIE_ADAPTER_VERSION

    def __init__(self, *, fetcher: ResponseFetcher | None = None) -> None:
        self._fetcher = fetcher

    def _get(self, resource: DiscoveredResource, context: AdapterContext) -> FetchResult:
        requested_url = context.require_allowed_url(resource.url)
        def validate_redirect(url: str) -> str:
            allowed_url = context.require_allowed_url(url)
            kind = resource.metadata.get("kind")
            if kind == _KIND_HOME:
                return normalize_fasie_url(allowed_url, allow_query=False)
            if kind == _KIND_FEED:
                return feed_page_url(allowed_url)
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

    def fetch(self, resource: DiscoveredResource, context: AdapterContext) -> FetchResult:
        kind = resource.metadata.get("kind")
        if kind == _KIND_HOME:
            normalize_fasie_url(resource.url, allow_query=False)
        elif kind == _KIND_FEED:
            feed_page_url(resource.url)
        elif kind == _KIND_PUBLICATION:
            press_detail_url(resource.url)
        elif kind == _KIND_ARTIFACT:
            normalize_upload_url(resource.url)
        else:
            raise ValueError("resource is not a FASIE home, feed, publication, or artifact")
        fetched = self._get(resource, context)
        if kind == _KIND_HOME:
            final_url = normalize_fasie_url(fetched.final_url, allow_query=False)
        elif kind == _KIND_FEED:
            final_url = feed_page_url(fetched.final_url)
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
            request_count += 1
            fetched = self.fetch(resource, context)
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
        captures: list[FetchResult] = []
        issues: list[AdapterIssue] = []
        request_count = 0
        response_bytes = 0
        home_url = normalize_fasie_url(config.home_url, allow_query=False)
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
        cutoff = context.started_at.astimezone(FASIE_TZ).date() - timedelta(days=config.lookback_days)
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
            for entry in parsed.entries:
                feed_entries.setdefault(entry.url, entry)
            dates = [entry.published_at.date() for entry in parsed.entries if entry.published_at is not None]
            if parsed.entries and len(dates) == len(parsed.entries) and all(value < cutoff for value in dates):
                break
            if parsed.entries and len(dates) != len(parsed.entries):
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="feed_cutoff_date_unavailable",
                        message="A feed page contained a publication without a valid date; cutoff completeness is limited.",
                        resource_key=resource.external_key,
                    )
                )
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
        for entry in feed_entries.values():
            if entry.published_at is None or entry.published_at.date() >= cutoff:
                if entry.url not in candidate_urls:
                    candidate_urls.append(entry.url)
        feed_positions = {
            url: position
            for position, url in enumerate(feed_entries, 1)
        }
        publications: list[ParsedPublication] = []
        publication_captures: dict[str, tuple[int, FetchResult]] = {}
        for index, url in enumerate(candidate_urls, 1):
            if total_limit_reached:
                break
            entry = feed_entries.get(url)
            published_at = entry.published_at if entry is not None else None
            resource = _publication_resource(url, published_at=published_at, title=entry.title if entry else "")
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

        groups, group_issues = _group_publications(
            publications,
            as_of=context.started_at.astimezone(FASIE_TZ),
            cutoff=cutoff,
        )
        issues.extend(_parser_issue_to_adapter(issue, f"{FASIE_ADAPTER_NAME}:grouping") for issue in group_issues)
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
        artifact_captures: list[FetchResult] = []
        for artifact_url, parent_keys in artifact_urls.items():
            if total_limit_reached:
                artifact_deferred.add(artifact_url)
                artifact_deferred_reasons[artifact_url] = "total_bytes_limit"
                continue
            resource = _artifact_resource(artifact_url, sorted(parent_keys))
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

        record_resources: list[DiscoveredResource] = []
        for group in groups:
            capture_info = publication_captures.get(group.canonical_publication_url)
            if capture_info is None:
                capture_info = next((value for url, value in publication_captures.items() if url == group.record_url), None)
            if capture_info is None:
                continue
            capture_index, capture = capture_info
            record_resource = _record_resource(group, source_publication_url=capture.final_url)
            captures[capture_index] = replace(capture, resource=record_resource)
            record_resources.append(record_resource)
        canonical_artifact_ids = {id(item) for item in artifact_canonical.values()}
        captures.extend(
            item
            for item in artifact_captures
            if id(item) in canonical_artifact_ids
        )
        context.report_progress(f"FASIE: найдено активных возможностей {len(record_resources)}")
        return DiscoveryResult(
            captures=tuple(captures),
            record_resources=tuple(record_resources),
            issues=tuple(issues),
            request_count=request_count,
            response_bytes=response_bytes,
            artifact_discovered=len(artifact_urls),
            artifact_fetched=artifact_fetched,
            artifact_deferred=len(artifact_deferred),
            coverage_scope="current opportunities published in FASIE's home application banner and fund press feed within the configured lookback window",
            quality_limitations=(
                "The feed is bounded by lookback_days and max_feed_pages; malformed or undated pagination is reported.",
                "Only exact deterministic competition identities are grouped; standalone third-party opportunities remain separate candidates.",
                "Results are retained as source publications and close their group rather than becoming active records.",
                "Application portals and external pages are references only and are never fetched.",
                "Attachments are fetched only from FASIE /upload/ after an active grouped record is formed and inspected with source-owned limits.",
                "Raw responses remain outside PostgreSQL; staged payloads contain capture metadata and bounded inspection excerpts.",
            ),
        )

    def extract(self, fetched: FetchResult, context: AdapterContext) -> ExtractResult:
        del context
        if fetched.resource.metadata.get("kind") != _KIND_RECORD:
            return ExtractResult()
        raw_payload = fetched.resource.metadata.get("record_payload")
        if not isinstance(raw_payload, dict):
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
            records=(
                ExtractedRecord(
                    row_number=row_number,
                    raw_payload=deepcopy(raw_payload),
                    capture_key=fetched.resource.external_key,
                ),
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

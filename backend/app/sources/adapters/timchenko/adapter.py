from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import Any, Sequence
from urllib.parse import urlsplit

from app.import_bridge.contract import ParsedRow, ValidationIssue, add_duplicate_key_issues, parse_record
from app.sources.adapters.potanin.artifacts import inspect_linked_artifact
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

from .normalization import (
    TIMCHENKO_CATALOG_SECTIONS,
    TIMCHENKO_CATALOG_STATUS,
    TIMCHENKO_HOST,
    normalize_competition_url,
    normalize_outbound_url,
)
from .parsing import ParserIssue, parse_catalog_page, parse_competition_page


TIMCHENKO_ADAPTER_NAME = "timchenko-competitions"
TIMCHENKO_ADAPTER_VERSION = "1.1.3"
TIMCHENKO_CATALOG_URLS = {
    section: f"https://{TIMCHENKO_HOST}/contests/{section}/"
    for section in TIMCHENKO_CATALOG_SECTIONS
}

_PARSER_ISSUES_KEY = "_parser_issues"
_RESOURCE_ROLE_DISCOVERY = "discovery"
_RESOURCE_ROLE_RECORD = "record"
_RESOURCE_ROLE_ARTIFACT = "artifact"
_TIMCHENKO_USER_AGENT = "siderfold-timchenko-adapter/1.0 (+https://fondtimchenko.ru/)"


@dataclass
class _PendingArtifact:
    url: str
    kind: str
    depth: int
    parent_record_urls: set[str] = field(default_factory=set)


def _catalog_resource(section: str) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=f"{TIMCHENKO_ADAPTER_NAME}:catalog:{section}",
        url=TIMCHENKO_CATALOG_URLS[section],
        metadata={
            "kind": "competition-catalog",
            "resource_role": _RESOURCE_ROLE_DISCOVERY,
            "extract_record": False,
            "catalog_section": section,
            "source_status": TIMCHENKO_CATALOG_STATUS[section],
        },
    )


def _competition_resource_key(url: str) -> str:
    digest = sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"{TIMCHENKO_ADAPTER_NAME}:competition:{digest}"


def _artifact_resource_key(url: str) -> str:
    digest = sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"{TIMCHENKO_ADAPTER_NAME}:artifact:{digest}"


def _competition_resource(
    *,
    url: str,
    discovery_index: int,
    catalog_section: str,
    source_status: str,
    source_category: str | None,
) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=_competition_resource_key(url),
        url=url,
        metadata={
            "kind": "competition-card",
            "resource_role": _RESOURCE_ROLE_RECORD,
            "extract_record": True,
            "discovery_index": discovery_index,
            "catalog_section": catalog_section,
            "source_status": source_status,
            "source_category": source_category,
        },
    )


def _artifact_resource(pending: _PendingArtifact) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=_artifact_resource_key(pending.url),
        url=pending.url,
        metadata={
            "kind": "linked-artifact",
            "resource_role": _RESOURCE_ROLE_ARTIFACT,
            "extract_record": False,
            "artifact_kind": pending.kind,
            "crawl_depth": pending.depth,
            "parent_record_urls": sorted(pending.parent_record_urls),
        },
    )


def _parser_issue_payload(issues: Sequence[ParserIssue]) -> list[dict[str, str]]:
    return [
        {
            "severity": issue.severity,
            "code": issue.code,
            "field": issue.field,
            "message": issue.message,
        }
        for issue in issues
    ]


def _parse_embedded_issues(value: object) -> tuple[ParserIssue, ...]:
    if not isinstance(value, list):
        return ()
    parsed: list[ParserIssue] = []
    for raw_issue in value:
        if not isinstance(raw_issue, dict):
            continue
        severity = raw_issue.get("severity")
        code = raw_issue.get("code")
        field = raw_issue.get("field")
        message = raw_issue.get("message")
        if (
            severity in {"warning", "error"}
            and isinstance(code, str)
            and isinstance(field, str)
            and isinstance(message, str)
        ):
            parsed.append(
                ParserIssue(
                    severity=severity,
                    code=code,
                    field=field,
                    message=message,
                )
            )
    return tuple(parsed)


def _discovery_issue(issue: ParserIssue, resource_key: str) -> AdapterIssue:
    return AdapterIssue(
        stage=AdapterStage.DISCOVER,
        severity=issue.severity,
        code=issue.code,
        message=issue.message,
        resource_key=resource_key,
        field=issue.field,
    )


def _unexpected_format_record(*, source_url: str, content_format: str) -> dict[str, Any]:
    return {
        "record_key": source_url,
        "title": "Unparseable source card",
        "record_url": source_url,
        "payload": {},
        "warnings": [],
        _PARSER_ISSUES_KEY: _parser_issue_payload(
            (
                ParserIssue(
                    severity="error",
                    code="unexpected_card_content_type",
                    field="content_format",
                    message=(
                        "Competition cards must be served as HTML; "
                        f"received {content_format!r}."
                    ),
                ),
            )
        ),
    }


def _artifact_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    nested = payload.get("payload")
    artifacts = nested.get("artifacts") if isinstance(nested, dict) else None
    return [entry for entry in artifacts if isinstance(entry, dict)] if isinstance(artifacts, list) else []


def _append_result_funding_observations(
    payload: dict[str, Any],
    *,
    artifact: dict[str, Any],
    inspection: dict[str, Any],
) -> None:
    if artifact.get("kind") != "result":
        return
    funding = payload.get("funding")
    observations = inspection.get("funding_observations")
    if not isinstance(funding, dict) or not isinstance(observations, list):
        return
    amounts = funding.setdefault("amounts", [])
    if not isinstance(amounts, list):
        return
    for observation in observations:
        if isinstance(observation, dict) and observation not in amounts:
            amounts.append(observation)


def _nested_document_urls(fetched: FetchResult) -> list[str]:
    if "html" not in fetched.content_format.lower():
        return []
    inspection = inspect_linked_artifact(
        fetched.content,
        content_format=fetched.content_format,
        source_url=fetched.final_url,
    )
    links = inspection.payload.get("outbound_links")
    if not isinstance(links, list):
        return []
    urls: list[str] = []
    for entry in links:
        if not isinstance(entry, dict):
            continue
        value = entry.get("url")
        if not isinstance(value, str):
            continue
        normalized = normalize_outbound_url(value)
        if normalized is None:
            continue
        parsed = urlsplit(normalized)
        if parsed.hostname == TIMCHENKO_HOST and parsed.path.startswith("/upload/"):
            if normalized not in urls:
                urls.append(normalized)
    return urls


class TimchenkoCompetitionsAdapter:
    """Bounded collector for Fond Timchenko's three public contest catalogs."""

    name = TIMCHENKO_ADAPTER_NAME
    version = TIMCHENKO_ADAPTER_VERSION

    def __init__(self, *, fetcher: ResponseFetcher | None = None) -> None:
        self._fetcher = fetcher
        self._artifact_aliases: dict[str, FetchResult] = {}
        self._artifact_parent_urls: dict[str, set[str]] = {}
        self._artifact_deferred_reasons: dict[str, str] = {}

    def _get(self, resource: DiscoveredResource, context: AdapterContext) -> FetchResult:
        requested_url = context.require_allowed_url(resource.url)
        fetcher = self._fetcher or UrllibResponseFetcher(
            redirect_validator=context.require_allowed_url,
            user_agent=_TIMCHENKO_USER_AGENT,
        )
        response: HttpResponse = fetcher.get(
            requested_url,
            timeout_seconds=context.request_timeout_seconds(),
            max_response_bytes=context.limits.max_response_bytes,
        )
        return fetch_result_from_response(resource, response, context)

    def _record_discovery_artifact(
        self,
        *,
        entry: dict[str, Any],
        parent_record_url: str,
        pending: dict[str, _PendingArtifact],
        artifact_urls: set[str],
        deferred_urls: set[str],
    ) -> None:
        url = entry.get("url")
        kind = entry.get("kind")
        collection = entry.get("collection")
        if not isinstance(url, str) or kind not in {"document", "result"}:
            return
        artifact_urls.add(url)
        if collection != "fetch":
            deferred_urls.add(url)
            return
        current = pending.get(url)
        if current is None:
            current = _PendingArtifact(url=url, kind=kind, depth=1)
            pending[url] = current
        current.parent_record_urls.add(parent_record_url)

    def discover(self, context: AdapterContext) -> DiscoveryResult:
        self._artifact_aliases = {}
        self._artifact_parent_urls = {}
        self._artifact_deferred_reasons = {}
        captures: list[FetchResult] = []
        issues: list[AdapterIssue] = []
        cards_by_url: dict[str, DiscoveredResource] = {}
        request_count = 0
        response_bytes = 0
        pending: dict[str, _PendingArtifact] = {}
        artifact_urls: set[str] = set()
        deferred_urls: set[str] = set()
        artifact_fetched = 0

        for section in TIMCHENKO_CATALOG_SECTIONS:
            resource = _catalog_resource(section)
            if request_count >= context.limits.max_requests:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="catalog_request_limit_reached",
                        message="The request limit was reached before all three catalogs were captured.",
                        resource_key=resource.external_key,
                    )
                )
                break
            try:
                context.report_progress(f"каталог {section}: загружается")
                context.require_time_remaining()
                request_count += 1
                fetched = self._get(resource, context)
            except AdapterRunTimeoutError as error:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="run_time_limit_reached",
                        message=str(error),
                        resource_key=resource.external_key,
                    )
                )
                break
            except UrlAllowlistError as error:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="url_not_allowed",
                        message=str(error),
                        resource_key=resource.external_key,
                    )
                )
                continue
            except Exception as error:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="catalog_fetch_failed",
                        message=str(error),
                        resource_key=resource.external_key,
                    )
                )
                continue

            if response_bytes + len(fetched.content) > context.limits.max_total_bytes:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="catalog_response_limit_reached",
                        message="The total response-size limit was reached while capturing catalogs.",
                        resource_key=resource.external_key,
                    )
                )
                break
            response_bytes += len(fetched.content)
            captures.append(fetched)
            if "html" not in fetched.content_format.lower():
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="unexpected_catalog_content_type",
                        message=(
                            "Competition catalogs must be served as HTML; "
                            f"received {fetched.content_format!r}."
                        ),
                        resource_key=resource.external_key,
                    )
                )
                continue

            parsed = parse_catalog_page(
                fetched.content,
                source_url=fetched.final_url,
                catalog_section=section,
            )
            issues.extend(_discovery_issue(issue, resource.external_key) for issue in parsed.issues)
            for entry in parsed.entries:
                if entry.url in cards_by_url:
                    existing = cards_by_url[entry.url]
                    sections = existing.metadata.setdefault("catalog_sections", [existing.metadata.get("catalog_section")])
                    if isinstance(sections, list) and section not in sections:
                        sections.append(section)
                    categories = existing.metadata.setdefault("source_categories", [])
                    if isinstance(categories, list) and entry.source_category and entry.source_category not in categories:
                        categories.append(entry.source_category)
                    issues.append(
                        AdapterIssue(
                            stage=AdapterStage.DISCOVER,
                            severity="warning",
                            code="duplicate_normalized_url",
                            message=f"The normalized card URL appeared in more than one catalog: {entry.url}",
                            resource_key=existing.external_key,
                            field="record_key",
                        )
                    )
                    continue
                index = len(cards_by_url) + 1
                cards_by_url[entry.url] = _competition_resource(
                    url=entry.url,
                    discovery_index=index,
                    catalog_section=section,
                    source_status=TIMCHENKO_CATALOG_STATUS[section],
                    source_category=entry.source_category,
                )

        cards = list(cards_by_url.values())
        context.report_progress(f"каталог: найдено карточек {len(cards)}")
        if len(cards) > context.limits.max_records:
            issues.append(
                AdapterIssue(
                    stage=AdapterStage.DISCOVER,
                    severity="error",
                    code="record_limit_exceeded",
                    message=f"max_records limit ({context.limits.max_records}) was exceeded during discovery.",
                )
            )
            cards = cards[: context.limits.max_records]

        # Capture the detail pages once during discovery.  This lets the
        # bounded artifact crawl use exactly the links present on each card,
        # while the runner later extracts from immutable captures.
        for index, resource in enumerate(cards, 1):
            if request_count >= context.limits.max_requests:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="card_request_limit_reached",
                        message="The request limit was reached before every card was captured.",
                        resource_key=resource.external_key,
                    )
                )
                break
            try:
                context.report_progress(f"каталог: загружается карточка {index}/{len(cards)}")
                context.require_time_remaining()
                request_count += 1
                fetched = self.fetch(resource, context)
            except AdapterRunTimeoutError as error:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="run_time_limit_reached",
                        message=str(error),
                        resource_key=resource.external_key,
                    )
                )
                break
            except UrlAllowlistError as error:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="url_not_allowed",
                        message=str(error),
                        resource_key=resource.external_key,
                    )
                )
                continue
            except Exception as error:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="competition_card_fetch_failed",
                        message=str(error),
                        resource_key=resource.external_key,
                    )
                )
                continue
            if response_bytes + len(fetched.content) > context.limits.max_total_bytes:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="card_response_limit_reached",
                        message="The total response-size limit was reached while capturing cards.",
                        resource_key=resource.external_key,
                    )
                )
                break
            response_bytes += len(fetched.content)
            captures.append(fetched)
            if "html" not in fetched.content_format.lower():
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="unexpected_card_content_type",
                        message=(
                            "Competition cards must be served as HTML; "
                            f"received {fetched.content_format!r}."
                        ),
                        resource_key=resource.external_key,
                    )
                )
                continue
            parsed = parse_competition_page(
                fetched.content,
                source_url=fetched.final_url,
                source_status=resource.metadata.get("source_status"),
                catalog_section=resource.metadata.get("catalog_section"),
                source_category=resource.metadata.get("source_category"),
            )
            for artifact in _artifact_entries(parsed.record_payload):
                self._record_discovery_artifact(
                    entry=artifact,
                    parent_record_url=resource.url,
                    pending=pending,
                    artifact_urls=artifact_urls,
                    deferred_urls=deferred_urls,
                )

        # Detail cards are deliberately captured before this queue is built.
        # Sorting makes the remaining global artifact budget reproducible.
        queued_urls: deque[str] = deque(sorted(pending))
        artifact_position = 0
        while queued_urls:
            url = queued_urls.popleft()
            pending_artifact = pending[url]
            artifact_resource = _artifact_resource(pending_artifact)
            artifact_position += 1
            if request_count >= context.limits.max_requests:
                deferred_urls.add(url)
                deferred_urls.update(queued_urls)
                self._artifact_deferred_reasons[url] = "request_limit"
                self._artifact_deferred_reasons.update(
                    {remaining_url: "request_limit" for remaining_url in queued_urls}
                )
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="artifact_request_limit_reached",
                        message="Remaining linked artifacts were retained as references for a later run.",
                        resource_key=artifact_resource.external_key,
                    )
                )
                break
            try:
                context.report_progress(
                    f"материалы: загружается {artifact_position}/{artifact_position + len(queued_urls)}"
                )
                context.require_time_remaining()
                request_count += 1
                fetched = self.fetch(artifact_resource, context)
            except AdapterRunTimeoutError as error:
                deferred_urls.add(url)
                deferred_urls.update(queued_urls)
                self._artifact_deferred_reasons[url] = "time_limit"
                self._artifact_deferred_reasons.update(
                    {remaining_url: "time_limit" for remaining_url in queued_urls}
                )
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="artifact_time_limit_reached",
                        message=f"{error}; remaining linked artifacts were retained as references.",
                        resource_key=artifact_resource.external_key,
                    )
                )
                break
            except Exception as error:
                deferred_urls.add(url)
                self._artifact_deferred_reasons[url] = "fetch_failed"
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="artifact_fetch_failed",
                        message=str(error),
                        resource_key=artifact_resource.external_key,
                    )
                )
                continue
            if response_bytes + len(fetched.content) > context.limits.max_total_bytes:
                deferred_urls.add(url)
                deferred_urls.update(queued_urls)
                self._artifact_deferred_reasons[url] = "total_bytes_limit"
                self._artifact_deferred_reasons.update(
                    {remaining_url: "total_bytes_limit" for remaining_url in queued_urls}
                )
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="artifact_response_limit_reached",
                        message="The linked artifact exceeded the total response-size budget and was left as a reference.",
                        resource_key=artifact_resource.external_key,
                    )
                )
                break
            response_bytes += len(fetched.content)
            artifact_fetched += 1
            self._artifact_parent_urls[pending_artifact.url] = set(pending_artifact.parent_record_urls)
            content_hash = sha256(fetched.content).hexdigest()
            canonical = next(
                (
                    known
                    for known in self._artifact_aliases.values()
                    if sha256(known.content).hexdigest() == content_hash
                ),
                None,
            )
            if canonical is None:
                canonical = fetched
                captures.append(canonical)
            else:
                alias_urls = canonical.resource.metadata.setdefault("alias_urls", [canonical.final_url])
                if isinstance(alias_urls, list) and pending_artifact.url not in alias_urls:
                    alias_urls.append(pending_artifact.url)
            self._artifact_aliases[pending_artifact.url] = canonical
            self._artifact_aliases[fetched.final_url] = canonical
            if pending_artifact.kind != "result" or pending_artifact.depth >= 2:
                continue
            for nested_url in _nested_document_urls(fetched):
                artifact_urls.add(nested_url)
                nested = pending.get(nested_url)
                if nested is None:
                    nested = _PendingArtifact(
                        url=nested_url,
                        kind="document",
                        depth=pending_artifact.depth + 1,
                    )
                    pending[nested_url] = nested
                    queued_urls.append(nested_url)
                nested.parent_record_urls.update(pending_artifact.parent_record_urls)

        context.report_progress(
            f"сбор завершён: запросов {request_count}; материалов получено {artifact_fetched}"
        )
        return DiscoveryResult(
            resources=(),
            captures=tuple(captures),
            record_resources=tuple(cards),
            issues=tuple(issues),
            request_count=request_count,
            response_bytes=response_bytes,
            artifact_discovered=len(artifact_urls),
            artifact_fetched=artifact_fetched,
            artifact_deferred=len(deferred_urls),
            coverage_scope=(
                "official Fond Timchenko competition cards from the programs, ready, and archive catalogs, "
                "plus bounded official documents and explicitly marked result materials"
            ),
            quality_limitations=(
                "Completeness is measured only against the three server-rendered catalogs captured at run time.",
                "Pagination is a hard error because this adapter does not guess or follow catalog pages.",
                "Application forms, mailto/tel links, social links, and external pages are retained only when they are an application candidate; they are never fetched.",
                "The AJAX download bundle is reference-only; only direct /upload/ files and one nested /upload/ level from an official result page are fetched.",
                "Raw responses remain outside PostgreSQL; candidates contain capture metadata and bounded artifact inspections.",
            ),
        )

    def fetch(self, resource: DiscoveredResource, context: AdapterContext) -> FetchResult:
        resource_kind = resource.metadata.get("kind")
        if resource_kind == "competition-card":
            normalize_competition_url(resource.url)
        elif resource_kind == "linked-artifact":
            parsed = urlsplit(resource.url)
            if parsed.hostname != TIMCHENKO_HOST or not (
                parsed.path.startswith("/upload/") or parsed.path.startswith("/press-center/")
            ):
                raise ValueError("Timchenko artifacts must be under /upload/ or /press-center/")
        else:
            raise ValueError("resource is not a Timchenko card or linked artifact")
        fetched = self._get(resource, context)
        if resource_kind == "competition-card":
            return replace(fetched, final_url=normalize_competition_url(fetched.final_url))
        return fetched

    def extract(self, fetched: FetchResult, context: AdapterContext) -> ExtractResult:
        del context
        if fetched.resource.metadata.get("kind") != "competition-card":
            return ExtractResult()
        source_url = normalize_competition_url(fetched.final_url)
        discovery_index = fetched.resource.metadata.get("discovery_index")
        row_number = discovery_index if isinstance(discovery_index, int) else 1
        if "html" not in fetched.content_format.lower():
            return ExtractResult(
                records=(
                    ExtractedRecord(
                        row_number=row_number,
                        raw_payload=_unexpected_format_record(
                            source_url=source_url,
                            content_format=fetched.content_format,
                        ),
                        capture_key=fetched.resource.external_key,
                    ),
                )
            )
        parsed = parse_competition_page(
            fetched.content,
            source_url=source_url,
            source_status=(
                fetched.resource.metadata.get("source_status")
                if isinstance(fetched.resource.metadata.get("source_status"), str)
                else None
            ),
            catalog_section=(
                fetched.resource.metadata.get("catalog_section")
                if isinstance(fetched.resource.metadata.get("catalog_section"), str)
                else None
            ),
            source_category=(
                fetched.resource.metadata.get("source_category")
                if isinstance(fetched.resource.metadata.get("source_category"), str)
                else None
            ),
        )
        payload = dict(parsed.record_payload)
        payload[_PARSER_ISSUES_KEY] = _parser_issue_payload(parsed.issues)
        return ExtractResult(
            records=(
                ExtractedRecord(
                    row_number=row_number,
                    raw_payload=payload,
                    capture_key=fetched.resource.external_key,
                ),
            )
        )

    def enrich(
        self,
        records: Sequence[ExtractedRecord],
        fetched: Sequence[FetchResult],
        context: AdapterContext,
    ) -> ExtractResult:
        del context
        artifacts_by_url = {
            item.final_url: item
            for item in fetched
            if item.resource.metadata.get("resource_role") == _RESOURCE_ROLE_ARTIFACT
        }
        artifacts_by_url.update(self._artifact_aliases)
        artifacts_by_parent: dict[str, list[tuple[str, FetchResult]]] = {}
        for artifact_url, item in artifacts_by_url.items():
            parent_urls = self._artifact_parent_urls.get(artifact_url)
            if parent_urls is None:
                raw_parent_urls = item.resource.metadata.get("parent_record_urls")
                parent_urls = (
                    {value for value in raw_parent_urls if isinstance(value, str)}
                    if isinstance(raw_parent_urls, list)
                    else set()
                )
            for parent_url in parent_urls:
                artifacts_by_parent.setdefault(parent_url, []).append((artifact_url, item))

        enriched_records: list[ExtractedRecord] = []
        for record in records:
            raw_payload = dict(record.raw_payload)
            payload = raw_payload.get("payload")
            if not isinstance(payload, dict):
                enriched_records.append(record)
                continue
            artifacts = _artifact_entries(raw_payload)
            enriched_artifacts: list[dict[str, Any]] = []
            warnings = list(raw_payload.get("warnings", []))
            captured_count = 0
            reference_count = 0
            deferred_count = 0
            represented_urls: set[str] = set()
            for artifact in artifacts:
                enriched_artifact = dict(artifact)
                url = enriched_artifact.get("url")
                if isinstance(url, str):
                    represented_urls.add(url)
                fetched_artifact = artifacts_by_url.get(url) if isinstance(url, str) else None
                if fetched_artifact is None:
                    if enriched_artifact.get("collection") == "fetch":
                        enriched_artifact["collection_status"] = "deferred"
                        enriched_artifact["collection_reason"] = self._artifact_deferred_reasons.get(
                            url,
                            "not_captured_in_run",
                        )
                        deferred_count += 1
                    else:
                        enriched_artifact["collection_status"] = "reference_only"
                        reference_count += 1
                    enriched_artifacts.append(enriched_artifact)
                    continue
                inspection = inspect_linked_artifact(
                    fetched_artifact.content,
                    content_format=fetched_artifact.content_format,
                    source_url=fetched_artifact.final_url,
                )
                enriched_artifact.update(
                    {
                        "collection_status": "captured",
                        "capture": {
                            "resource_key": fetched_artifact.resource.external_key,
                            "source_url": url,
                            "raw_capture_source_url": fetched_artifact.final_url,
                            "content_sha256": sha256(fetched_artifact.content).hexdigest(),
                            "content_format": fetched_artifact.content_format,
                            "received_at": fetched_artifact.received_at.isoformat(),
                            "external_content_uri": fetched_artifact.external_content_uri,
                        },
                        "inspection": inspection.payload,
                    }
                )
                _append_result_funding_observations(
                    payload,
                    artifact=enriched_artifact,
                    inspection=inspection.payload,
                )
                warnings.extend(f"{issue.code}: {issue.message}" for issue in inspection.issues)
                captured_count += 1
                enriched_artifacts.append(enriched_artifact)

            record_url = raw_payload.get("record_url")
            if isinstance(record_url, str):
                for artifact_url, fetched_artifact in artifacts_by_parent.get(record_url, []):
                    if artifact_url in represented_urls:
                        continue
                    inspection = inspect_linked_artifact(
                        fetched_artifact.content,
                        content_format=fetched_artifact.content_format,
                        source_url=fetched_artifact.final_url,
                    )
                    nested_artifact = {
                        "url": artifact_url,
                        "label": None,
                        "kind": fetched_artifact.resource.metadata.get("artifact_kind"),
                        "collection": "fetch",
                        "collection_status": "captured",
                        "relationship": "nested_linked_artifact",
                        "capture": {
                            "resource_key": fetched_artifact.resource.external_key,
                            "source_url": artifact_url,
                            "raw_capture_source_url": fetched_artifact.final_url,
                            "content_sha256": sha256(fetched_artifact.content).hexdigest(),
                            "content_format": fetched_artifact.content_format,
                            "received_at": fetched_artifact.received_at.isoformat(),
                            "external_content_uri": fetched_artifact.external_content_uri,
                        },
                        "inspection": inspection.payload,
                    }
                    _append_result_funding_observations(
                        payload,
                        artifact=nested_artifact,
                        inspection=inspection.payload,
                    )
                    warnings.extend(f"{issue.code}: {issue.message}" for issue in inspection.issues)
                    enriched_artifacts.append(nested_artifact)
                    represented_urls.add(artifact_url)
                    captured_count += 1

            payload["artifacts"] = enriched_artifacts
            payload["artifact_summary"] = {
                "captured": captured_count,
                "reference_only": reference_count,
                "deferred": deferred_count,
            }
            raw_payload["payload"] = payload
            raw_payload["warnings"] = list(dict.fromkeys(warnings))
            enriched_records.append(replace(record, raw_payload=raw_payload))
        return ExtractResult(records=tuple(enriched_records))

    def validate(
        self,
        records: Sequence[ExtractedRecord],
        context: AdapterContext,
    ) -> ValidationResult:
        del context
        rows: list[ParsedRow] = []
        for extracted in records:
            payload = dict(extracted.raw_payload)
            parser_issues = _parse_embedded_issues(payload.pop(_PARSER_ISSUES_KEY, None))
            row = parse_record(
                payload,
                row_number=extracted.row_number,
                capture_key=extracted.capture_key,
            )
            validation_issues = list(row.issues)
            warnings = list(row.record.warnings) if row.record is not None else []
            for issue in parser_issues:
                if issue.severity == "error":
                    validation_issues.append(
                        ValidationIssue(
                            row_number=extracted.row_number,
                            field=issue.field,
                            code=issue.code,
                            message=issue.message,
                        )
                    )
                else:
                    warnings.append(f"{issue.code}: {issue.message}")
            if row.record is not None and warnings != row.record.warnings:
                row = replace(row, record=row.record.model_copy(update={"warnings": warnings}))
            if validation_issues != list(row.issues):
                row = replace(row, issues=tuple(validation_issues))
            rows.append(row)
        return ValidationResult(rows=add_duplicate_key_issues(rows))

    def report(self, summary: AdapterRunSummary) -> AdapterReport:
        return adapter_report(self, summary)


def timchenko_adapter() -> SourceAdapter:
    return TimchenkoCompetitionsAdapter()

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import Any, Sequence
from urllib.parse import urlsplit

from app.import_bridge.contract import (
    ParsedRow,
    ValidationIssue,
    add_duplicate_key_issues,
    parse_record,
)
from app.sources.adapters.potanin.artifacts import inspect_linked_artifact
from app.sources.adapters.potanin.http import (
    HttpResponse,
    ResponseFetcher,
    UrllibResponseFetcher,
    fetch_result_from_response,
)
from app.sources.adapters.potanin.normalization import (
    POTANIN_HOST,
    normalize_competition_url,
)
from app.sources.adapters.potanin.parsing import (
    ParserIssue,
    parse_competition_page,
    parse_competitions_sitemap,
)
from app.sources.contract import (
    AdapterContext,
    AdapterIssue,
    AdapterReport,
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


POTANIN_ADAPTER_NAME = "potanin-competitions"
POTANIN_ADAPTER_VERSION = "1.1.0"
POTANIN_SITEMAP_URL = "https://fondpotanin.ru/sitemap-iblock-competitions.xml"
_SITEMAP_RESOURCE_KEY = "potanin:sitemap:competitions"
_PARSER_ISSUES_KEY = "_parser_issues"
_RESOURCE_ROLE_DISCOVERY = "discovery"
_RESOURCE_ROLE_RECORD = "record"
_RESOURCE_ROLE_ARTIFACT = "artifact"


@dataclass
class _PendingArtifact:
    url: str
    kind: str
    depth: int
    parent_record_urls: set[str] = field(default_factory=set)


def _sitemap_resource() -> DiscoveredResource:
    return DiscoveredResource(
        external_key=_SITEMAP_RESOURCE_KEY,
        url=POTANIN_SITEMAP_URL,
        metadata={
            "kind": "competitions-sitemap",
            "resource_role": _RESOURCE_ROLE_DISCOVERY,
            "extract_record": False,
        },
    )


def _card_resource_key(url: str) -> str:
    digest = sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"potanin:competition:{digest}"


def _artifact_resource_key(url: str) -> str:
    digest = sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"potanin:artifact:{digest}"


def _card_resource(
    *,
    url: str,
    discovery_index: int,
    sitemap_last_modified_at: str | None,
) -> DiscoveredResource:
    return DiscoveredResource(
        external_key=_card_resource_key(url),
        url=url,
        metadata={
            "kind": "competition-card",
            "resource_role": _RESOURCE_ROLE_RECORD,
            "extract_record": True,
            "discovery_index": discovery_index,
            "sitemap_last_modified_at": sitemap_last_modified_at,
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


def _discovery_issue(issue: ParserIssue) -> AdapterIssue:
    return AdapterIssue(
        stage=AdapterStage.DISCOVER,
        severity=issue.severity,
        code=issue.code,
        message=issue.message,
        resource_key=_SITEMAP_RESOURCE_KEY,
        field=issue.field,
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


def _unexpected_format_record(
    *,
    source_url: str,
    content_format: str,
) -> dict[str, Any]:
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
    container = payload.get("payload")
    artifacts = container.get("artifacts") if isinstance(container, dict) else None
    if not isinstance(artifacts, list):
        return []
    return [entry for entry in artifacts if isinstance(entry, dict)]


def _nested_document_urls(fetched: FetchResult) -> list[str]:
    """Discover one extra document layer from an already-captured result page."""

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
        url = entry.get("url")
        if not isinstance(url, str):
            continue
        parsed = urlsplit(url)
        if parsed.hostname == POTANIN_HOST and parsed.path.startswith("/upload/"):
            if url not in urls:
                urls.append(url)
    return urls


class PotaninCompetitionsAdapter:
    """Bounded collector for public Fond Potanin competition pages and artifacts."""

    name = POTANIN_ADAPTER_NAME
    version = POTANIN_ADAPTER_VERSION

    def __init__(self, *, fetcher: ResponseFetcher | None = None) -> None:
        self._fetcher = fetcher or UrllibResponseFetcher()
        self._artifact_aliases: dict[str, FetchResult] = {}
        self._artifact_parent_urls: dict[str, set[str]] = {}

    def _get(
        self,
        resource: DiscoveredResource,
        context: AdapterContext,
    ) -> FetchResult:
        requested_url = context.require_allowed_url(resource.url)
        response: HttpResponse = self._fetcher.get(
            requested_url,
            timeout_seconds=context.limits.timeout_seconds,
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
        sitemap_resource = _sitemap_resource()
        sitemap_fetch = self._get(sitemap_resource, context)
        sitemap = parse_competitions_sitemap(sitemap_fetch.content)
        captures: list[FetchResult] = [sitemap_fetch]
        issues: list[AdapterIssue] = [_discovery_issue(issue) for issue in sitemap.issues]
        if any(issue.severity == "error" for issue in issues):
            return DiscoveryResult(
                captures=tuple(captures),
                issues=tuple(issues),
                request_count=1,
                response_bytes=len(sitemap_fetch.content),
                coverage_scope="official Fond Potanin competitions sitemap",
            )
        request_count = 1
        response_bytes = len(sitemap_fetch.content)
        cards: list[DiscoveredResource] = []
        pending: dict[str, _PendingArtifact] = {}
        artifact_urls: set[str] = set()
        artifact_fetched = 0
        deferred_urls: set[str] = set()

        for index, entry in enumerate(sitemap.entries, 1):
            resource = _card_resource(
                url=entry.url,
                discovery_index=index,
                sitemap_last_modified_at=entry.last_modified_at,
            )
            cards.append(resource)
            if request_count >= context.limits.max_requests:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="card_request_limit_reached",
                        message=(
                            "The request limit was reached before every sitemap card "
                            "could be captured."
                        ),
                        resource_key=resource.external_key,
                    )
                )
                break
            try:
                fetched = self.fetch(resource, context)
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
            request_count += 1
            response_bytes += len(fetched.content)
            if response_bytes > context.limits.max_total_bytes:
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="error",
                        code="card_response_limit_reached",
                        message=(
                            "The total response-size limit was reached while collecting "
                            "competition cards."
                        ),
                        resource_key=resource.external_key,
                    )
                )
                break
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
                source_url=entry.url,
                sitemap_last_modified_at=entry.last_modified_at,
            )
            for artifact in _artifact_entries(parsed.record_payload):
                self._record_discovery_artifact(
                    entry=artifact,
                    parent_record_url=entry.url,
                    pending=pending,
                    artifact_urls=artifact_urls,
                    deferred_urls=deferred_urls,
                )

        queued_urls: deque[str] = deque(pending)
        while queued_urls:
            url = queued_urls.popleft()
            pending_artifact = pending[url]
            resource = _artifact_resource(pending_artifact)
            if request_count >= context.limits.max_requests:
                deferred_urls.add(url)
                deferred_urls.update(queued_urls)
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="artifact_request_limit_reached",
                        message=(
                            "The request limit was reached; remaining linked artifacts "
                            "were retained as references for a later run."
                        ),
                        resource_key=resource.external_key,
                    )
                )
                break
            try:
                fetched = self.fetch(resource, context)
            except Exception as error:
                deferred_urls.add(url)
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="artifact_fetch_failed",
                        message=str(error),
                        resource_key=resource.external_key,
                    )
                )
                request_count += 1
                continue
            request_count += 1
            artifact_fetched += 1
            response_bytes += len(fetched.content)
            if response_bytes > context.limits.max_total_bytes:
                deferred_urls.add(url)
                issues.append(
                    AdapterIssue(
                        stage=AdapterStage.DISCOVER,
                        severity="warning",
                        code="artifact_response_limit_reached",
                        message=(
                            "The linked artifact exceeded the run's total response-size "
                            "budget and was left as a reference."
                        ),
                        resource_key=resource.external_key,
                    )
                )
                break
            self._artifact_parent_urls[pending_artifact.url] = set(
                pending_artifact.parent_record_urls
            )
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
                alias_urls = canonical.resource.metadata.setdefault(
                    "alias_urls", [canonical.final_url]
                )
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
                "official Fond Potanin competition cards listed in the sitemap, "
                "plus bounded same-origin documents and result pages linked from them"
            ),
            quality_limitations=(
                "Card completeness is measured only against URLs in the official sitemap at capture time.",
                "Linked artifacts are followed only on fondpotanin.ru under /upload/ and /press/, to a maximum depth of two.",
                "Application forms, other hosts, and unsupported file formats are retained as references rather than fetched.",
                "Raw files remain outside PostgreSQL; candidate payloads contain bounded inspection metadata, not complete document text.",
            ),
        )

    def fetch(
        self,
        resource: DiscoveredResource,
        context: AdapterContext,
    ) -> FetchResult:
        resource_kind = resource.metadata.get("kind")
        if resource_kind == "competition-card":
            normalize_competition_url(resource.url)
        elif resource_kind != "linked-artifact":
            raise ValueError("resource is not a competition card or linked artifact")
        fetched = self._get(resource, context)
        if resource_kind == "competition-card":
            return replace(
                fetched,
                final_url=normalize_competition_url(fetched.final_url),
            )
        return fetched

    def extract(
        self,
        fetched: FetchResult,
        context: AdapterContext,
    ) -> ExtractResult:
        del context
        if fetched.resource.metadata.get("kind") != "competition-card":
            return ExtractResult()
        source_url = normalize_competition_url(fetched.final_url)
        if "html" not in fetched.content_format.lower():
            discovery_index = fetched.resource.metadata.get("discovery_index")
            row_number = discovery_index if isinstance(discovery_index, int) else 1
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
        raw_last_modified_at = fetched.resource.metadata.get("sitemap_last_modified_at")
        sitemap_last_modified_at = (
            raw_last_modified_at if isinstance(raw_last_modified_at, str) else None
        )
        parsed = parse_competition_page(
            fetched.content,
            source_url=source_url,
            sitemap_last_modified_at=sitemap_last_modified_at,
        )
        payload: dict[str, Any] = dict(parsed.record_payload)
        payload[_PARSER_ISSUES_KEY] = _parser_issue_payload(parsed.issues)
        discovery_index = fetched.resource.metadata.get("discovery_index")
        row_number = discovery_index if isinstance(discovery_index, int) else 1
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
                if isinstance(parent_url, str):
                    parent_artifacts = artifacts_by_parent.setdefault(parent_url, [])
                    pair = (artifact_url, item)
                    if pair not in parent_artifacts:
                        parent_artifacts.append(pair)
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
                        enriched_artifact["collection_reason"] = "not_captured_in_run"
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
                for issue in inspection.issues:
                    warnings.append(f"{issue.code}: {issue.message}")
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
                    nested_artifact: dict[str, Any] = {
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
                    for issue in inspection.issues:
                        warnings.append(f"{issue.code}: {issue.message}")
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


def potanin_adapter() -> SourceAdapter:
    return PotaninCompetitionsAdapter()

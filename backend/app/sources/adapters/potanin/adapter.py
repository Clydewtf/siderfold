from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Any, Sequence

from app.import_bridge.contract import (
    ParsedRow,
    ValidationIssue,
    add_duplicate_key_issues,
    parse_record,
)
from app.sources.adapters.potanin.http import (
    HttpResponse,
    ResponseFetcher,
    UrllibResponseFetcher,
    fetch_result_from_response,
)
from app.sources.adapters.potanin.normalization import normalize_competition_url
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


POTANIN_ADAPTER_NAME = "potanin-competitions"
POTANIN_ADAPTER_VERSION = "1.0.0"
POTANIN_SITEMAP_URL = "https://fondpotanin.ru/sitemap-iblock-competitions.xml"
_SITEMAP_RESOURCE_KEY = "potanin:sitemap:competitions"
_PARSER_ISSUES_KEY = "_parser_issues"


def _sitemap_resource() -> DiscoveredResource:
    return DiscoveredResource(
        external_key=_SITEMAP_RESOURCE_KEY,
        url=POTANIN_SITEMAP_URL,
        metadata={"kind": "competitions-sitemap"},
    )


def _card_resource_key(url: str) -> str:
    digest = sha256(url.encode("utf-8")).hexdigest()[:20]
    return f"potanin:competition:{digest}"


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


class PotaninCompetitionsAdapter:
    """Bounded adapter for the public Fond Potanin competitions catalog."""

    name = POTANIN_ADAPTER_NAME
    version = POTANIN_ADAPTER_VERSION

    def __init__(self, *, fetcher: ResponseFetcher | None = None) -> None:
        self._fetcher = fetcher or UrllibResponseFetcher()

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

    def discover(self, context: AdapterContext) -> DiscoveryResult:
        sitemap_resource = _sitemap_resource()
        sitemap_fetch = self._get(sitemap_resource, context)
        sitemap = parse_competitions_sitemap(sitemap_fetch.content)
        resources = tuple(
            DiscoveredResource(
                external_key=_card_resource_key(entry.url),
                url=entry.url,
                metadata={
                    "kind": "competition-card",
                    "discovery_index": index,
                    "sitemap_last_modified_at": entry.last_modified_at,
                },
            )
            for index, entry in enumerate(sitemap.entries, 1)
        )
        return DiscoveryResult(
            resources=resources,
            captures=(sitemap_fetch,),
            issues=tuple(_discovery_issue(issue) for issue in sitemap.issues),
            request_count=1,
            response_bytes=len(sitemap_fetch.content),
            coverage_scope=(
                "accepted URLs in the official Fond Potanin competitions sitemap"
            ),
            quality_limitations=(
                "Coverage is limited to public card URLs present in the official sitemap at capture time.",
                "Freshness measures sitemap lastmod metadata coverage; it is not an eligibility or completeness guarantee.",
                "Referenced application portals, documents, and result pages are recorded when recognized but are not fetched.",
            ),
        )

    def fetch(
        self,
        resource: DiscoveredResource,
        context: AdapterContext,
    ) -> FetchResult:
        if resource.metadata.get("kind") != "competition-card":
            raise ValueError("only competition-card resources may be fetched")
        normalize_competition_url(resource.url)
        fetched = self._get(resource, context)
        return replace(
            fetched,
            final_url=normalize_competition_url(fetched.final_url),
        )

    def extract(
        self,
        fetched: FetchResult,
        context: AdapterContext,
    ) -> ExtractResult:
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

    def validate(
        self,
        records: Sequence[ExtractedRecord],
        context: AdapterContext,
    ) -> ValidationResult:
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

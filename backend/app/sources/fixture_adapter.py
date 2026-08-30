from __future__ import annotations

import json
from typing import Sequence

from app.sources.contract import (
    AdapterContext,
    AdapterIssue,
    AdapterRunSummary,
    AdapterReport,
    DiscoveredResource,
    DiscoveryResult,
    ExtractedRecord,
    ExtractResult,
    FetchResult,
    SourceAdapter,
    ValidationResult,
    adapter_report,
    validate_import_records,
)


class FixtureCatalogAdapter:
    """Deterministic local adapter backed by an anonymized JSON fixture."""

    name = "fixture-catalog"
    version = "1.0.0"

    def discover(self, context: AdapterContext) -> DiscoveryResult:
        prefix = context.source.allowed_url_prefixes[0].rstrip("/")
        return DiscoveryResult(
            resources=(
                DiscoveredResource(
                    external_key=f"{context.source.source_key}:fixture-v1",
                    url=f"{prefix}/v1.json",
                    metadata={"fixture": "catalog_v1.json"},
                ),
            )
        )

    def fetch(
        self,
        resource: DiscoveredResource,
        context: AdapterContext,
    ) -> FetchResult:
        source_url = context.require_allowed_url(resource.url)
        fixture_path = context.source.resolve_fixture_path(context.project_root)
        content = fixture_path.read_bytes()
        return FetchResult(
            resource=resource,
            final_url=source_url,
            content=content,
            content_format="application/json",
            received_at=context.started_at,
            external_content_uri=fixture_path.as_uri(),
            response_metadata={
                "access_method": "fixture",
                "fixture_name": fixture_path.name,
            },
        )

    def extract(
        self,
        fetched: FetchResult,
        context: AdapterContext,
    ) -> ExtractResult:
        try:
            payload = json.loads(fetched.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return ExtractResult(
                issues=(
                    AdapterIssue(
                        stage="extract",
                        severity="error",
                        code="invalid_fixture_json",
                        message=str(error),
                        resource_key=fetched.resource.external_key,
                    ),
                )
            )

        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            return ExtractResult(
                issues=(
                    AdapterIssue(
                        stage="extract",
                        severity="error",
                        code="invalid_fixture_envelope",
                        message="fixture must contain a records array",
                        resource_key=fetched.resource.external_key,
                    ),
                )
            )

        records = tuple(
            ExtractedRecord(
                row_number=index,
                raw_payload=value if isinstance(value, dict) else {"value": value},
                capture_key=fetched.resource.external_key,
            )
            for index, value in enumerate(payload["records"], 1)
        )
        return ExtractResult(records=records)

    def validate(
        self,
        records: Sequence[ExtractedRecord],
        context: AdapterContext,
    ) -> ValidationResult:
        return validate_import_records(records)

    def report(self, summary: AdapterRunSummary) -> AdapterReport:
        return adapter_report(self, summary)


def fixture_adapter() -> SourceAdapter:
    return FixtureCatalogAdapter()

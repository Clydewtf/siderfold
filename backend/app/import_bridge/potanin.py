from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.import_bridge.contract import (
    CONTRACT_VERSION,
    ContractAdapter,
    ContractCapture,
    ContractSource,
    ImportPackage,
    PackageMetadata,
    PackageValidationError,
    ParsedRow,
    ValidationIssue,
    add_duplicate_key_issues,
    parse_record,
)


POTANIN_ADAPTER_NAME = "potanin-local-output"
POTANIN_ADAPTER_VERSION = "1.0.0"

_SAFE_PAYLOAD_FIELDS = (
    "status",
    "publication_date",
    "application_start_date",
    "application_end_date",
    "organizer",
    "summary",
    "goals",
    "tasks",
    "target_audience",
    "requirements",
    "nominations",
    "project_directions",
    "procedure",
    "grant_fund_rub",
    "max_support_rub",
    "funding_text",
    "application_url",
    "result_urls",
    "document_urls",
    "sections",
)


def _issue(*, field: str, code: str, message: str) -> PackageValidationError:
    return PackageValidationError([ValidationIssue(field=field, code=code, message=message)])


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _as_warning_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _potanin_record_payload(value: dict[str, Any]) -> dict[str, Any]:
    source_url = _optional_text(value.get("source_url"))
    max_support = value.get("max_support_rub")
    funding: dict[str, Any] | None = None
    if isinstance(max_support, (int, float)) and max_support > 0:
        funding = {
            "value_kind": "maximum",
            "currency_code": "RUB",
            "max_amount": max_support,
        }

    warnings = _as_warning_list(value.get("parse_warnings"))
    grant_fund = value.get("grant_fund_rub")
    if isinstance(grant_fund, (int, float)) and grant_fund > 0:
        warnings.append(
            "grant_fund_rub is preserved as a total fund and is not mapped to per-program funding"
        )

    payload = {
        field: value[field]
        for field in _SAFE_PAYLOAD_FIELDS
        if value.get(field) not in (None, "", [], {})
    }
    return {
        "record_key": source_url or "missing-source-url",
        "title": value.get("title"),
        "record_url": source_url,
        "deadline_on": _optional_text(value.get("application_end_date")),
        "funding": funding,
        "payload": payload,
        "warnings": warnings,
    }


def load_potanin_output(path: Path) -> ImportPackage:
    """Adapt the untracked local Potanin JSON output in memory.

    The parser output remains in place. Only its bytes and selected normalized
    fields are used to build a package for the import bridge.
    """

    try:
        raw_bytes = path.read_bytes()
    except OSError as error:
        raise _issue(field="input", code="read_error", message=str(error)) from error

    try:
        values = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _issue(field="input", code="invalid_json", message=str(error)) from error

    if not isinstance(values, list) or not values:
        raise _issue(
            field="input",
            code="invalid_potanin_output",
            message="Potanin output must be a non-empty JSON array",
        )

    first_record = next((value for value in values if isinstance(value, dict)), None)
    if first_record is None:
        raise _issue(
            field="input",
            code="invalid_potanin_output",
            message="Potanin output does not contain object records",
        )

    source_host = _optional_text(first_record.get("source"))
    collected_at = _optional_text(first_record.get("collected_at"))
    if source_host is None or collected_at is None:
        raise _issue(
            field="input",
            code="missing_metadata",
            message="Potanin output requires source and collected_at in its first record",
        )

    try:
        metadata = PackageMetadata(
            contract_version=CONTRACT_VERSION,
            source=ContractSource(
                name="Фонд Потанина",
                canonical_url=f"https://{source_host}",
            ),
            capture=ContractCapture(
                source_url=f"https://{source_host}",
                received_at=collected_at,
                external_content_uri=path.resolve().as_uri(),
                content_format="application/json",
                response_metadata={
                    "input_kind": "potanin-local-output/v1",
                    "record_count": len(values),
                },
            ),
            adapter=ContractAdapter(
                name=POTANIN_ADAPTER_NAME,
                version=POTANIN_ADAPTER_VERSION,
            ),
        )
    except ValidationError as error:
        issues = [
            ValidationIssue(
                field=".".join(str(part) for part in item["loc"]),
                code=item["type"],
                message=item["msg"],
            )
            for item in error.errors(include_url=False)
        ]
        raise PackageValidationError(issues) from error

    rows: list[ParsedRow] = []
    for row_number, value in enumerate(values, 1):
        if not isinstance(value, dict):
            rows.append(
                ParsedRow(
                    row_number=row_number,
                    record=None,
                    raw_payload={"value": value},
                    issues=(
                        ValidationIssue(
                            row_number=row_number,
                            field="record",
                            code="model_type",
                            message="Potanin record must be an object",
                        ),
                    ),
                )
            )
            continue
        rows.append(parse_record(_potanin_record_payload(value), row_number=row_number))

    return ImportPackage(
        metadata=metadata,
        raw_bytes=raw_bytes,
        rows=add_duplicate_key_issues(rows),
    )

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.domain.models import FundingValueKind


CONTRACT_VERSION = "siderfold.import/v1"

CSV_COLUMNS = (
    "contract_version",
    "source_name",
    "source_canonical_url",
    "capture_source_url",
    "received_at",
    "external_content_uri",
    "content_format",
    "adapter_name",
    "adapter_version",
    "record_key",
    "title",
    "record_url",
    "deadline_on",
    "funding_value_kind",
    "currency_code",
    "exact_amount",
    "min_amount",
    "max_amount",
    "payload_json",
    "warnings_json",
)

CSV_PACKAGE_COLUMNS = CSV_COLUMNS[:9]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _require_http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("must be an absolute http(s) URL")
    return value


class ContractSource(ContractModel):
    name: str = Field(min_length=1, max_length=255)
    canonical_url: str = Field(min_length=1, max_length=1024)

    _validate_url = field_validator("canonical_url")(_require_http_url)


class ContractCapture(ContractModel):
    source_url: str = Field(min_length=1, max_length=2048)
    received_at: datetime
    external_content_uri: str = Field(min_length=1, max_length=2048)
    content_format: str = Field(min_length=1, max_length=100)
    response_metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_source_url = field_validator("source_url")(_require_http_url)

    @field_validator("external_content_uri")
    @classmethod
    def require_uri_scheme(cls, value: str) -> str:
        if not urlparse(value).scheme:
            raise ValueError("must be an absolute URI")
        return value

    @field_validator("received_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone")
        return value


class ContractAdapter(ContractModel):
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)


class FundingInput(ContractModel):
    value_kind: FundingValueKind
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    exact_amount: Decimal | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None

    @field_validator("currency_code")
    @classmethod
    def normalize_currency_code(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @model_validator(mode="after")
    def validate_values_match_kind(self) -> FundingInput:
        has_currency = self.currency_code is not None
        if self.value_kind is FundingValueKind.EXACT:
            valid = (
                has_currency
                and self.exact_amount is not None
                and self.exact_amount > 0
                and self.min_amount is None
                and self.max_amount is None
            )
        elif self.value_kind is FundingValueKind.MINIMUM:
            valid = (
                has_currency
                and self.exact_amount is None
                and self.min_amount is not None
                and self.min_amount > 0
                and self.max_amount is None
            )
        elif self.value_kind is FundingValueKind.MAXIMUM:
            valid = (
                has_currency
                and self.exact_amount is None
                and self.min_amount is None
                and self.max_amount is not None
                and self.max_amount > 0
            )
        elif self.value_kind is FundingValueKind.RANGE:
            valid = (
                has_currency
                and self.exact_amount is None
                and self.min_amount is not None
                and self.min_amount > 0
                and self.max_amount is not None
                and self.max_amount > 0
                and self.min_amount <= self.max_amount
            )
        else:
            valid = (
                not has_currency
                and self.exact_amount is None
                and self.min_amount is None
                and self.max_amount is None
            )

        if not valid:
            raise ValueError("funding values do not match value_kind")
        return self


class ImportRecord(ContractModel):
    record_key: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=500)
    record_url: str = Field(min_length=1, max_length=2048)
    deadline_on: date | None = None
    funding: FundingInput | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    _validate_record_url = field_validator("record_url")(_require_http_url)

    @field_validator("warnings")
    @classmethod
    def reject_blank_warnings(cls, value: list[str]) -> list[str]:
        if any(not warning.strip() for warning in value):
            raise ValueError("warnings cannot contain blank values")
        return value

    def candidate_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class PackageMetadata(ContractModel):
    contract_version: Literal[CONTRACT_VERSION]
    source: ContractSource
    capture: ContractCapture
    adapter: ContractAdapter


class JsonEnvelope(PackageMetadata):
    records: list[Any] = Field(min_length=1)


class ValidationIssue(ContractModel):
    row_number: int | None = Field(default=None, ge=1)
    field: str
    code: str
    message: str


@dataclass(frozen=True)
class ParsedRow:
    row_number: int
    record: ImportRecord | None
    raw_payload: dict[str, Any]
    issues: tuple[ValidationIssue, ...] = ()
    capture_key: str | None = None


@dataclass(frozen=True)
class ImportCapture:
    """One immutable source response and the rows extracted from it."""

    capture: ContractCapture
    raw_bytes: bytes
    rows: tuple[ParsedRow, ...] = ()
    capture_key: str | None = None


@dataclass(frozen=True)
class ImportPackage:
    metadata: PackageMetadata
    raw_bytes: bytes
    rows: tuple[ParsedRow, ...]
    captures: tuple[ImportCapture, ...] = ()

    def resolved_captures(self) -> tuple[ImportCapture, ...]:
        """Return per-response captures, preserving the legacy single-capture shape."""

        if self.captures:
            return self.captures
        return (
            ImportCapture(
                capture=self.metadata.capture,
                raw_bytes=self.raw_bytes,
                rows=self.rows,
            ),
        )

    def fingerprint_bytes(self) -> bytes:
        captures = []
        for capture in self.resolved_captures():
            capture_metadata = capture.capture.model_dump(mode="json")
            capture_metadata.pop("received_at", None)
            capture_metadata.pop("external_content_uri", None)
            capture_metadata.pop("response_metadata", None)
            captures.append(
                {
                    "capture_key": capture.capture_key,
                    "capture": capture_metadata,
                    "content_sha256": sha256(capture.raw_bytes).hexdigest(),
                    "rows": [row.raw_payload for row in capture.rows],
                }
            )
        normalized = {
            "contract_version": self.metadata.contract_version,
            "source": self.metadata.source.model_dump(mode="json"),
            "adapter": self.metadata.adapter.model_dump(mode="json"),
            "captures": captures,
        }
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")


class PackageValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        super().__init__("invalid import package")
        self.issues = issues


def _issues_from_validation_error(
    error: ValidationError,
    *,
    row_number: int | None,
) -> tuple[ValidationIssue, ...]:
    return tuple(
        ValidationIssue(
            row_number=row_number,
            field=".".join(str(part) for part in item["loc"]) or "package",
            code=item["type"],
            message=item["msg"],
        )
        for item in error.errors(include_url=False)
    )


def parse_record(
    raw_value: Any,
    *,
    row_number: int,
    capture_key: str | None = None,
) -> ParsedRow:
    raw_payload = raw_value if isinstance(raw_value, dict) else {"value": raw_value}
    try:
        record = ImportRecord.model_validate(raw_value)
    except ValidationError as error:
        return ParsedRow(
            row_number=row_number,
            record=None,
            raw_payload=raw_payload,
            issues=_issues_from_validation_error(error, row_number=row_number),
            capture_key=capture_key,
        )
    return ParsedRow(
        row_number=row_number,
        record=record,
        raw_payload=raw_payload,
        capture_key=capture_key,
    )


def add_duplicate_key_issues(rows: list[ParsedRow]) -> tuple[ParsedRow, ...]:
    seen_keys: set[str] = set()
    checked_rows: list[ParsedRow] = []
    for row in rows:
        if row.record is None or row.record.record_key not in seen_keys:
            if row.record is not None:
                seen_keys.add(row.record.record_key)
            checked_rows.append(row)
            continue

        issue = ValidationIssue(
            row_number=row.row_number,
            field="record_key",
            code="duplicate_record_key",
            message="record_key must be unique within one import package",
        )
        checked_rows.append(replace(row, issues=(*row.issues, issue)))
    return tuple(checked_rows)


def load_json_contract(path: Path) -> ImportPackage:
    try:
        raw_bytes = path.read_bytes()
    except OSError as error:
        raise PackageValidationError(
            [ValidationIssue(field="input", code="read_error", message=str(error))]
        ) from error

    try:
        payload = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackageValidationError(
            [ValidationIssue(field="input", code="invalid_json", message=str(error))]
        ) from error

    if not isinstance(payload, dict):
        raise PackageValidationError(
            [
                ValidationIssue(
                    field="input",
                    code="invalid_envelope",
                    message="JSON contract must be an object with package metadata and records",
                )
            ]
        )

    try:
        envelope = JsonEnvelope.model_validate(payload)
    except ValidationError as error:
        raise PackageValidationError(
            list(_issues_from_validation_error(error, row_number=None))
        ) from error

    metadata = PackageMetadata.model_validate(envelope.model_dump(exclude={"records"}))
    rows = [parse_record(record, row_number=index) for index, record in enumerate(envelope.records, 1)]
    return ImportPackage(
        metadata=metadata,
        raw_bytes=raw_bytes,
        rows=add_duplicate_key_issues(rows),
    )


def _csv_metadata_payload(row: dict[str, str | None]) -> dict[str, Any]:
    return {
        "contract_version": row.get("contract_version"),
        "source": {
            "name": row.get("source_name"),
            "canonical_url": row.get("source_canonical_url"),
        },
        "capture": {
            "source_url": row.get("capture_source_url"),
            "received_at": row.get("received_at"),
            "external_content_uri": row.get("external_content_uri"),
            "content_format": row.get("content_format"),
        },
        "adapter": {
            "name": row.get("adapter_name"),
            "version": row.get("adapter_version"),
        },
    }


def _csv_record_payload(
    row: dict[str, str | None],
    *,
    row_number: int,
) -> tuple[dict[str, Any], tuple[ValidationIssue, ...]]:
    issues: list[ValidationIssue] = []

    payload: dict[str, Any] = {}
    payload_value = (row.get("payload_json") or "").strip()
    if payload_value:
        try:
            parsed_payload = json.loads(payload_value)
            if not isinstance(parsed_payload, dict):
                raise ValueError("payload_json must decode to an object")
            payload = parsed_payload
        except (ValueError, json.JSONDecodeError) as error:
            issues.append(
                ValidationIssue(
                    row_number=row_number,
                    field="payload_json",
                    code="invalid_json",
                    message=str(error),
                )
            )

    warnings: list[str] = []
    warnings_value = (row.get("warnings_json") or "").strip()
    if warnings_value:
        try:
            parsed_warnings = json.loads(warnings_value)
            if not isinstance(parsed_warnings, list) or not all(
                isinstance(value, str) for value in parsed_warnings
            ):
                raise ValueError("warnings_json must decode to a list of strings")
            warnings = parsed_warnings
        except (ValueError, json.JSONDecodeError) as error:
            issues.append(
                ValidationIssue(
                    row_number=row_number,
                    field="warnings_json",
                    code="invalid_json",
                    message=str(error),
                )
            )

    funding_values = {
        "currency_code": (row.get("currency_code") or "").strip() or None,
        "exact_amount": (row.get("exact_amount") or "").strip() or None,
        "min_amount": (row.get("min_amount") or "").strip() or None,
        "max_amount": (row.get("max_amount") or "").strip() or None,
    }
    funding_kind = (row.get("funding_value_kind") or "").strip()
    if funding_kind:
        funding: dict[str, Any] | None = {"value_kind": funding_kind, **funding_values}
    elif any(value is not None for value in funding_values.values()):
        funding = None
        issues.append(
            ValidationIssue(
                row_number=row_number,
                field="funding_value_kind",
                code="missing",
                message="funding_value_kind is required when a funding value is supplied",
            )
        )
    else:
        funding = None

    return (
        {
            "record_key": row.get("record_key"),
            "title": row.get("title"),
            "record_url": row.get("record_url"),
            "deadline_on": (row.get("deadline_on") or "").strip() or None,
            "funding": funding,
            "payload": payload,
            "warnings": warnings,
        },
        tuple(issues),
    )


def load_csv_contract(path: Path) -> ImportPackage:
    try:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise PackageValidationError(
            [ValidationIssue(field="input", code="read_error", message=str(error))]
        ) from error

    reader = csv.DictReader(io.StringIO(text))
    headers = tuple(reader.fieldnames or ())
    missing = [column for column in CSV_COLUMNS if column not in headers]
    unexpected = [column for column in headers if column not in CSV_COLUMNS]
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing columns: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected columns: {', '.join(unexpected)}")
        raise PackageValidationError(
            [
                ValidationIssue(
                    field="header",
                    code="invalid_csv_header",
                    message="; ".join(details),
                )
            ]
        )

    raw_rows = list(reader)
    if not raw_rows:
        raise PackageValidationError(
            [
                ValidationIssue(
                    field="records",
                    code="empty_package",
                    message="CSV contract must contain at least one record row",
                )
            ]
        )

    try:
        metadata = PackageMetadata.model_validate(_csv_metadata_payload(raw_rows[0]))
    except ValidationError as error:
        raise PackageValidationError(
            list(_issues_from_validation_error(error, row_number=2))
        ) from error

    baseline_package_values = {
        column: raw_rows[0].get(column) for column in CSV_PACKAGE_COLUMNS
    }
    rows: list[ParsedRow] = []
    for csv_index, raw_row in enumerate(raw_rows, 2):
        record_payload, conversion_issues = _csv_record_payload(raw_row, row_number=csv_index)
        parsed_row = parse_record(record_payload, row_number=csv_index)
        issues = list(parsed_row.issues) + list(conversion_issues)
        for column in CSV_PACKAGE_COLUMNS:
            if raw_row.get(column) != baseline_package_values[column]:
                issues.append(
                    ValidationIssue(
                        row_number=csv_index,
                        field=column,
                        code="package_metadata_mismatch",
                        message="must match the first CSV row",
                    )
                )
        rows.append(replace(parsed_row, issues=tuple(issues)))

    return ImportPackage(
        metadata=metadata,
        raw_bytes=raw_bytes,
        rows=add_duplicate_key_issues(rows),
    )


def load_contract(path: Path, *, input_format: Literal["json", "csv"]) -> ImportPackage:
    if input_format == "json":
        return load_json_contract(path)
    return load_csv_contract(path)

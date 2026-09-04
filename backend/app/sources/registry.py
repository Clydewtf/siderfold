from __future__ import annotations

import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.sources.schedule import CronExpressionError, validate_cron_expression


REGISTRY_VERSION = 1
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "sources.toml"


class SourceAccessMethod(StrEnum):
    FIXTURE = "fixture"
    HTTP = "http"


class SourceRegistryStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class RegistryValidationError(ValueError):
    """Raised when the source registry cannot be loaded or validated."""


class UrlAllowlistError(ValueError):
    """Raised when a URL is outside a source's explicit allowlist."""


def _parsed_http_url(value: str) -> SplitResult:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials are not allowed in source URLs")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("source URL contains an invalid port") from error
    return parsed


def normalize_url(value: str) -> str:
    parsed = _parsed_http_url(value)
    hostname = parsed.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = parsed.port
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"

    return urlunsplit(
        (
            parsed.scheme.lower(),
            hostname,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def _normalize_allowlist_prefix(value: str) -> str:
    parsed = _parsed_http_url(value)
    if parsed.query:
        raise ValueError("allowlist URL prefixes must not contain a query")
    normalized = normalize_url(value)
    if normalized.endswith("/") and urlsplit(normalized).path != "/":
        return normalized.rstrip("/")
    return normalized


def _normalize_allowlist_url(value: str) -> str:
    """Normalize one exact URL allowed for a source transport request."""

    return normalize_url(value)


def _same_origin(left: SplitResult, right: SplitResult) -> bool:
    left_port = left.port or (443 if left.scheme.lower() == "https" else 80)
    right_port = right.port or (443 if right.scheme.lower() == "https" else 80)
    return (
        left.scheme.lower() == right.scheme.lower()
        and left.hostname.lower() == right.hostname.lower()
        and left_port == right_port
    )


def is_url_allowed(url: str, definition: SourceDefinition) -> bool:
    try:
        normalized_candidate = normalize_url(url)
        candidate = _parsed_http_url(normalized_candidate)
    except ValueError:
        return False

    if normalized_candidate in definition.allowed_exact_urls:
        return True

    for prefix in definition.allowed_url_prefixes:
        parsed_prefix = _parsed_http_url(prefix)
        if not _same_origin(candidate, parsed_prefix):
            continue
        prefix_path = parsed_prefix.path.rstrip("/") or "/"
        candidate_path = candidate.path.rstrip("/") or "/"
        if prefix_path == "/" or candidate_path in {
            prefix_path,
            f"{prefix_path}/",
        } or candidate_path.startswith(f"{prefix_path}/"):
            return True
    return False


def require_allowed_url(url: str, definition: SourceDefinition) -> str:
    normalized = normalize_url(url)
    if not is_url_allowed(normalized, definition):
        raise UrlAllowlistError(
            f"URL is outside the allowlist for source '{definition.source_key}': {normalized}"
        )
    return normalized


class SourceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_requests: int = Field(default=10, ge=1, le=1_000)
    max_response_bytes: int = Field(default=5_000_000, ge=1, le=100_000_000)
    max_total_bytes: int = Field(default=20_000_000, ge=1, le=500_000_000)
    max_records: int = Field(default=10_000, ge=1, le=1_000_000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_run_seconds: int = Field(default=900, ge=1, le=3_600)
    min_run_interval_seconds: int = Field(default=60, ge=0, le=86_400)


class TelegramChannelConfig(BaseModel):
    """Bounded configuration for a public, read-only Telegram channel."""

    model_config = ConfigDict(extra="forbid")

    channel_handle: str = Field(
        min_length=5,
        max_length=32,
        pattern=r"^[A-Za-z0-9_]+$",
    )
    public_read_url: str = Field(min_length=1, max_length=2_048)
    retention_days: int = Field(default=90, ge=1, le=365)
    min_request_interval_seconds: int = Field(default=2, ge=1, le=60)
    max_messages_per_run: int = Field(default=10_000, ge=1, le=1_000_000)

    @field_validator("channel_handle")
    @classmethod
    def normalize_channel_handle(cls, value: str) -> str:
        return value.lower()

    @field_validator("public_read_url")
    @classmethod
    def normalize_public_read_url(cls, value: str) -> str:
        return normalize_url(value)

    @model_validator(mode="after")
    def validate_public_read_url(self) -> TelegramChannelConfig:
        parsed = _parsed_http_url(self.public_read_url)
        expected_path = f"/s/{self.channel_handle}"
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname.lower() != "t.me"
            or parsed.path.rstrip("/") != expected_path
            or parsed.query
        ):
            raise ValueError(
                "public_read_url must be https://t.me/s/<configured channel handle>"
            )
        return self


class SourceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=255)
    canonical_url: str = Field(min_length=1, max_length=1024)
    allowed_url_prefixes: tuple[str, ...] = ()
    allowed_exact_urls: tuple[str, ...] = ()
    access_method: SourceAccessMethod
    schedule: str = Field(min_length=1, max_length=100)
    status: SourceRegistryStatus = SourceRegistryStatus.ACTIVE
    responsible: str = Field(min_length=1, max_length=255)
    adapter_name: str = Field(min_length=1, max_length=100)
    adapter_version: str = Field(min_length=1, max_length=100)
    limits: SourceLimits = Field(default_factory=SourceLimits)
    fixture_path: str | None = Field(default=None, max_length=1024)
    secret_env_vars: tuple[str, ...] = ()
    telegram_channel: TelegramChannelConfig | None = None

    @field_validator("name", "responsible", "adapter_name", "adapter_version")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("canonical_url")
    @classmethod
    def normalize_canonical_url(cls, value: str) -> str:
        return normalize_url(value)

    @field_validator("allowed_url_prefixes")
    @classmethod
    def normalize_allowed_url_prefixes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_normalize_allowlist_prefix(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowlist URL prefixes must be unique")
        return normalized

    @field_validator("allowed_exact_urls")
    @classmethod
    def normalize_allowed_exact_urls(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_normalize_allowlist_url(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("exact allowlist URLs must be unique")
        return normalized

    @field_validator("secret_env_vars")
    @classmethod
    def validate_secret_env_vars(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^[A-Z][A-Z0-9_]*$")
        if any(not pattern.fullmatch(value) for value in values):
            raise ValueError("secret_env_vars must contain environment variable names only")
        return values

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "manual":
            return normalized
        try:
            validate_cron_expression(normalized)
        except CronExpressionError as error:
            raise ValueError(
                "schedule must be 'manual' or a supported five-field cron expression"
            ) from error
        return normalized

    @model_validator(mode="after")
    def validate_access_configuration(self) -> SourceDefinition:
        if not self.allowed_url_prefixes and not self.allowed_exact_urls:
            raise ValueError("at least one allowed URL prefix or exact URL is required")
        if self.access_method is SourceAccessMethod.FIXTURE and not self.fixture_path:
            raise ValueError("fixture access requires fixture_path")
        if self.access_method is SourceAccessMethod.HTTP and self.fixture_path:
            raise ValueError("fixture_path is only valid for fixture access")
        if self.adapter_name == "telegram-discovery" and self.telegram_channel is None:
            raise ValueError("telegram-discovery requires telegram_channel configuration")
        if self.telegram_channel is not None:
            if self.adapter_name != "telegram-discovery":
                raise ValueError(
                    "telegram_channel configuration is only valid for telegram-discovery"
                )
            if self.access_method is not SourceAccessMethod.HTTP:
                raise ValueError("telegram-discovery requires http access")
            if not is_url_allowed(self.telegram_channel.public_read_url, self):
                raise ValueError(
                    "telegram public_read_url must be covered by the source allowlist"
                )
            canonical = _parsed_http_url(self.canonical_url)
            if (
                canonical.scheme.lower() != "https"
                or canonical.hostname.lower() != "t.me"
                or canonical.path.rstrip("/")
                != f"/{self.telegram_channel.channel_handle}"
                or canonical.query
            ):
                raise ValueError(
                    "telegram canonical_url must be https://t.me/<configured channel handle>"
                )
        return self

    def resolve_fixture_path(self, project_root: Path) -> Path:
        if self.fixture_path is None:
            raise RegistryValidationError(
                f"source '{self.source_key}' does not define a fixture path"
            )
        path = Path(self.fixture_path).expanduser()
        if not path.is_absolute():
            path = project_root / path
        return path.resolve()


class SourceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[REGISTRY_VERSION]
    sources: dict[str, SourceDefinition]

    @model_validator(mode="after")
    def validate_source_keys(self) -> SourceRegistry:
        mismatched = [
            key for key, definition in self.sources.items() if key != definition.source_key
        ]
        if mismatched:
            raise ValueError("source registry keys must match source_key")
        return self

    def get(self, source_key: str) -> SourceDefinition:
        try:
            return self.sources[source_key]
        except KeyError as error:
            raise RegistryValidationError(f"unknown source: {source_key}") from error


def load_registry(path: Path | None = None) -> SourceRegistry:
    registry_path = path or DEFAULT_REGISTRY_PATH
    try:
        with registry_path.open("rb") as stream:
            payload = tomllib.load(stream)
    except OSError as error:
        raise RegistryValidationError(f"cannot read source registry: {registry_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise RegistryValidationError(f"invalid source registry TOML: {registry_path}") from error

    try:
        return SourceRegistry.model_validate(payload)
    except ValueError as error:
        raise RegistryValidationError("source registry validation failed") from error

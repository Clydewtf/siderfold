from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


USER_AGENT = "siderfold-telegram-discovery/1.0"


class TelegramFetchError(RuntimeError):
    """A bounded public Telegram request could not produce a usable page."""


def _retry_after_seconds(headers: object) -> int | None:
    getter = getattr(headers, "get", None)
    value = getter("Retry-After") if callable(getter) else None
    if not isinstance(value, str) or not value.strip().isdigit():
        return None
    return int(value.strip())


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):  # type: ignore[no-untyped-def]
        del request, fp, message, headers
        raise TelegramFetchError(f"redirect response {code} to {newurl} is not allowed")


@dataclass(frozen=True)
class TelegramHttpResponse:
    requested_url: str
    final_url: str
    content: bytes
    content_format: str
    received_at: datetime
    response_metadata: Mapping[str, object]


class TelegramResponseFetcher(Protocol):
    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> TelegramHttpResponse:
        ...


class UrllibTelegramResponseFetcher:
    """Public, cookie-free HTTP transport with redirects and body size disabled."""

    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> TelegramHttpResponse:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                "Accept-Language": "ru",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with build_opener(_RejectRedirects()).open(
                request, timeout=timeout_seconds
            ) as response:
                content = response.read(max_response_bytes + 1)
                if len(content) > max_response_bytes:
                    raise TelegramFetchError(
                        f"response exceeded max_response_bytes ({max_response_bytes})"
                    )
                headers = response.headers
                content_type = headers.get_content_type() or "application/octet-stream"
                return TelegramHttpResponse(
                    requested_url=url,
                    final_url=response.geturl(),
                    content=content,
                    content_format=content_type,
                    received_at=datetime.now(timezone.utc),
                    response_metadata={
                        "http_status": response.getcode(),
                        "content_type": content_type,
                        "content_length": headers.get("Content-Length"),
                    },
                )
        except TelegramFetchError:
            raise
        except HTTPError as error:
            retry_after = _retry_after_seconds(error.headers)
            retry_hint = f"; Retry-After: {retry_after}" if retry_after is not None else ""
            raise TelegramFetchError(f"HTTP {error.code} for {url}{retry_hint}") from error
        except URLError as error:
            raise TelegramFetchError(f"transport error for {url}: {error.reason}") from error
        except OSError as error:
            raise TelegramFetchError(f"transport error for {url}: {error}") from error

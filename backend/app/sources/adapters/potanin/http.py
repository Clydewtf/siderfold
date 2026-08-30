from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.sources.contract import AdapterContext, DiscoveredResource, FetchResult


USER_AGENT = "siderfold-potanin-adapter/1.0 (+https://fondpotanin.ru/)"


class SourceFetchError(RuntimeError):
    """A bounded HTTP request could not produce one usable source response."""


class _RejectRedirects(HTTPRedirectHandler):
    """Keep a request on its originally allowlisted URL.

    urllib follows redirects by default, which could make a request to an
    unapproved host before the adapter gets a chance to inspect final_url.
    The Potanin adapter uses canonical sitemap and card URLs, so failing
    closed is preferable to following even a same-origin redirect implicitly.
    """

    def redirect_request(self, request, fp, code, message, headers, newurl):  # type: ignore[no-untyped-def]
        del request, fp, message, headers
        raise SourceFetchError(f"redirect response {code} to {newurl} is not allowed")


@dataclass(frozen=True)
class HttpResponse:
    requested_url: str
    final_url: str
    content: bytes
    content_format: str
    received_at: datetime
    response_metadata: Mapping[str, object]


class ResponseFetcher(Protocol):
    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> HttpResponse:
        ...


class UrllibResponseFetcher:
    """Small standard-library transport with a strict response-size cap."""

    def get(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> HttpResponse:
        request = Request(
            url,
            headers={
                "Accept": "application/xml,text/xml,text/html;q=0.9,*/*;q=0.1",
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
                    raise SourceFetchError(
                        f"response exceeded max_response_bytes ({max_response_bytes})"
                    )
                headers = response.headers
                content_type = headers.get_content_type() or "application/octet-stream"
                content_length = headers.get("Content-Length")
                return HttpResponse(
                    requested_url=url,
                    final_url=response.geturl(),
                    content=content,
                    content_format=content_type,
                    received_at=datetime.now(timezone.utc),
                    response_metadata={
                        "http_status": response.getcode(),
                        "content_type": content_type,
                        "content_length": content_length,
                        "last_modified": headers.get("Last-Modified"),
                    },
                )
        except SourceFetchError:
            raise
        except HTTPError as error:
            raise SourceFetchError(f"HTTP {error.code} for {url}") from error
        except URLError as error:
            raise SourceFetchError(f"transport error for {url}: {error.reason}") from error
        except OSError as error:
            raise SourceFetchError(f"transport error for {url}: {error}") from error


def _extension_for_content_type(content_format: str) -> str:
    if "xml" in content_format:
        return ".xml"
    if "html" in content_format:
        return ".html"
    return ".bin"


def archive_raw_content(response: HttpResponse, context: AdapterContext) -> str:
    """Store a response outside PostgreSQL unless this is a dry run."""

    digest = sha256(response.content).hexdigest()
    if context.dry_run or context.raw_capture_dir is None:
        return f"urn:sha256:{digest}"

    directory = context.raw_capture_dir / context.source.source_key
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{digest}{_extension_for_content_type(response.content_format)}"
    if not destination.exists():
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.",
            suffix=".tmp",
            dir=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(response.content)
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
    return destination.resolve().as_uri()


def fetch_result_from_response(
    resource: DiscoveredResource,
    response: HttpResponse,
    context: AdapterContext,
) -> FetchResult:
    context.require_allowed_url(response.final_url)
    return FetchResult(
        resource=resource,
        final_url=response.final_url,
        content=response.content,
        content_format=response.content_format,
        received_at=response.received_at,
        external_content_uri=archive_raw_content(response, context),
        response_metadata=response.response_metadata,
    )

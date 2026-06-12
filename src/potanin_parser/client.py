import time
from typing import Protocol
from urllib.request import Request, build_opener


USER_AGENT = "potanin-competitions-parser/0.1 (+https://fondpotanin.ru/)"


class Opener(Protocol):
    def open(self, request: Request, timeout: int): ...


class FetchError(RuntimeError):
    def __init__(self, url: str, original_error: Exception) -> None:
        self.url = url
        self.original_error = original_error
        super().__init__(f"Failed to fetch {url}: {original_error}")


class HttpClient:
    def __init__(
        self,
        opener: Opener | None = None,
        retries: int = 2,
        delay_seconds: float = 1.0,
    ) -> None:
        if retries < 1:
            raise ValueError("retries must be at least 1")
        if delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative")
        self.opener = opener or build_opener()
        self.retries = retries
        self.delay_seconds = delay_seconds

    def get(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ru",
            },
        )
        last_error: Exception | None = None

        for attempt in range(self.retries):
            try:
                with self.opener.open(request, timeout=30) as response:
                    body = response.read()
                    charset = response.headers.get_content_charset() or "utf-8"
                    try:
                        return body.decode(charset)
                    except LookupError:
                        return body.decode("utf-8")
            except Exception as error:
                last_error = error
                if attempt + 1 < self.retries:
                    time.sleep(self.delay_seconds)

        assert last_error is not None
        raise FetchError(url, last_error) from last_error

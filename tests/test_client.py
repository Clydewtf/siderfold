import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request

from potanin_parser.client import FetchError, HttpClient
from potanin_parser.cli import run_pipeline


class FakeHeaders:
    def __init__(self, charset: str | None = None) -> None:
        self.charset = charset

    def get_content_charset(self) -> str | None:
        return self.charset


class FakeResponse:
    def __init__(self, body: bytes, charset: str | None = None) -> None:
        self.body = body
        self.headers = FakeHeaders(charset)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeOpener:
    def __init__(self, results: list[object]) -> None:
        self.results = iter(results)
        self.calls = 0
        self.requests: list[Request] = []
        self.timeouts: list[int] = []

    def open(self, request, timeout: int):
        self.calls += 1
        self.requests.append(request)
        self.timeouts.append(timeout)
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return result


class HttpClientTests(unittest.TestCase):
    def test_client_retries_then_returns_html(self):
        opener = FakeOpener([TimeoutError(), FakeResponse(b"<html>ok</html>")])
        client = HttpClient(opener=opener, retries=2, delay_seconds=0)

        self.assertEqual(client.get("https://example.test"), "<html>ok</html>")
        self.assertEqual(opener.calls, 2)


class FakePipelineClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> str:
        self.urls.append(url)
        if "SHOWALL_1=1" in url:
            return """
                <a class="programms__item-link" href="/competitions/ok">OK</a>
                <a class="programms__item-link" href="/competitions/fail">Fail</a>
            """
        if url.endswith("/ok"):
            return "<html><body><h1>Рабочий конкурс</h1></body></html>"
        raise FetchError(url, TimeoutError("timed out"))


class AdditionalHttpClientTests(unittest.TestCase):
    def test_client_sends_polite_headers_and_timeout(self):
        opener = FakeOpener([FakeResponse(b"ok")])
        client = HttpClient(opener=opener, retries=1, delay_seconds=0)

        client.get("https://example.test")

        request = opener.requests[0]
        self.assertIn("potanin", request.get_header("User-agent").lower())
        self.assertEqual(request.get_header("Accept-language"), "ru")
        self.assertEqual(opener.timeouts, [30])

    def test_client_decodes_response_charset(self):
        opener = FakeOpener([FakeResponse("Привет".encode("cp1251"), "cp1251")])
        client = HttpClient(opener=opener, retries=1, delay_seconds=0)

        self.assertEqual(client.get("https://example.test"), "Привет")

    def test_client_falls_back_to_utf8_without_charset(self):
        opener = FakeOpener([FakeResponse("Привет".encode())])
        client = HttpClient(opener=opener, retries=1, delay_seconds=0)

        self.assertEqual(client.get("https://example.test"), "Привет")

    def test_client_falls_back_to_utf8_when_declared_charset_is_wrong(self):
        opener = FakeOpener([FakeResponse("Привет".encode(), "ascii")])
        client = HttpClient(opener=opener, retries=2, delay_seconds=0)

        self.assertEqual(client.get("https://example.test"), "Привет")
        self.assertEqual(opener.calls, 1)

    def test_client_raises_fetch_error_after_final_failure(self):
        original_error = TimeoutError("timed out")
        opener = FakeOpener([TimeoutError("first"), original_error])
        client = HttpClient(opener=opener, retries=2, delay_seconds=0)

        with self.assertRaises(FetchError) as context:
            client.get("https://example.test/card")

        self.assertIn("https://example.test/card", str(context.exception))
        self.assertIs(context.exception.__cause__, original_error)
        self.assertEqual(opener.calls, 2)


class PipelineTests(unittest.TestCase):
    def test_pipeline_continues_after_card_failure_and_calls_outputs(self):
        client = FakePipelineClient()
        exported: list[tuple[list, Path]] = []
        analyzed: list[tuple[list, Path, int, str]] = []

        def exporter(records, output_dir):
            exported.append((records, output_dir))

        def analyzer(records, output_dir, failed_pages, collected_at):
            analyzed.append((records, output_dir, failed_pages, collected_at))

        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with self.assertLogs("potanin_parser", level="WARNING") as logs:
                records = run_pipeline(
                    catalog_url="https://example.test/competitions/?kind=all",
                    output_dir=output_dir,
                    delay_seconds=0,
                    limit=None,
                    client=client,
                    exporter=exporter,
                    analyzer=analyzer,
                )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "Рабочий конкурс")
        self.assertIn("SHOWALL_1=1", client.urls[0])
        self.assertIn("kind=all", client.urls[0])
        self.assertEqual(exported[0][0], records)
        self.assertEqual(analyzed[0][0], records)
        self.assertEqual(analyzed[0][2], 1)
        self.assertTrue(analyzed[0][3])
        self.assertTrue(any("/fail" in message for message in logs.output))

    def test_pipeline_sleeps_once_before_each_card_request(self):
        events: list[tuple[str, object]] = []

        class TracedClient(FakePipelineClient):
            def get(self, url: str) -> str:
                events.append(("get", url))
                return super().get(url)

        def sleep(seconds: float) -> None:
            events.append(("sleep", seconds))

        with TemporaryDirectory() as directory:
            with self.assertLogs("potanin_parser", level="WARNING"):
                run_pipeline(
                    catalog_url="https://example.test/competitions/",
                    output_dir=Path(directory),
                    delay_seconds=2.5,
                    limit=None,
                    client=TracedClient(),
                    exporter=lambda records, output_dir: None,
                    analyzer=lambda records, output_dir, failed_pages, collected_at: None,
                    sleep=sleep,
                )

        self.assertEqual(
            events,
            [
                ("get", "https://example.test/competitions/?SHOWALL_1=1"),
                ("sleep", 2.5),
                ("get", "https://example.test/competitions/ok"),
                ("sleep", 2.5),
                ("get", "https://example.test/competitions/fail"),
            ],
        )


if __name__ == "__main__":
    unittest.main()

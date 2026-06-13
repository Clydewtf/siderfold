import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.request import Request

from potanin_parser.client import FetchError, HttpClient
from potanin_parser.cli import _default_analyzer, main, run_pipeline
from potanin_parser.models import Competition


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
    def test_client_rejects_non_finite_delays(self):
        for delay in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(delay=delay):
                with self.assertRaisesRegex(ValueError, "finite"):
                    HttpClient(delay_seconds=delay)

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
    @staticmethod
    def _minimal_export(records, output_dir: Path) -> None:
        (output_dir / "competitions.json").write_bytes(b"[]")
        (output_dir / "competitions.csv").write_bytes(b"title\n")

    @staticmethod
    def _minimal_analysis(records, output_dir: Path, failed_pages, collected_at) -> None:
        (output_dir / "summary.json").write_bytes(b"{}")

    @staticmethod
    def _write_existing_artifacts(output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        charts_dir = output_dir / "charts"
        charts_dir.mkdir()
        for name in ("competitions.json", "competitions.csv", "summary.json"):
            (output_dir / name).write_bytes(f"old:{name}".encode())
        for name in (
            "statuses.png",
            "deadlines.png",
            "maximum_support.png",
            "grant_funds.png",
        ):
            (charts_dir / name).write_bytes(f"old:{name}".encode())
        (output_dir / "run.log").write_bytes(b"existing log")
        (output_dir / "custom.txt").write_bytes(b"custom output")
        (charts_dir / "custom.png").write_bytes(b"custom chart")

    @staticmethod
    def _snapshot(directory: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*")
            if path.is_file()
        }

    def test_pipeline_continues_after_card_failure_and_calls_outputs(self):
        client = FakePipelineClient()
        exported: list[tuple[list, Path]] = []
        analyzed: list[tuple[list, Path, int, str]] = []

        def exporter(records, output_dir):
            exported.append((records, output_dir))
            self._minimal_export(records, output_dir)

        def analyzer(records, output_dir, failed_pages, collected_at):
            analyzed.append((records, output_dir, failed_pages, collected_at))
            self._minimal_analysis(records, output_dir, failed_pages, collected_at)

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

        def exporter(records, output_dir):
            self._minimal_export(records, output_dir)

        def analyzer(records, output_dir, failed_pages, collected_at):
            self._minimal_analysis(records, output_dir, failed_pages, collected_at)

        with TemporaryDirectory() as directory:
            with self.assertLogs("potanin_parser", level="WARNING"):
                run_pipeline(
                    catalog_url="https://example.test/competitions/",
                    output_dir=Path(directory),
                    delay_seconds=2.5,
                    limit=None,
                    client=TracedClient(),
                    exporter=exporter,
                    analyzer=analyzer,
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

    def test_pipeline_keeps_existing_artifacts_when_analyzer_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            self._write_existing_artifacts(output_dir)
            before = self._snapshot(output_dir)

            def failing_analyzer(
                records, staging_dir, failed_pages, collected_at
            ) -> None:
                self.assertNotEqual(staging_dir, output_dir)
                (staging_dir / "summary.json").write_bytes(b"partial summary")
                charts_dir = staging_dir / "charts"
                charts_dir.mkdir()
                (charts_dir / "statuses.png").write_bytes(b"partial chart")
                raise RuntimeError("analytics failed")

            with self.assertLogs("potanin_parser", level="WARNING"):
                with self.assertRaisesRegex(RuntimeError, "analytics failed"):
                    run_pipeline(
                        catalog_url="https://example.test/competitions/",
                        output_dir=output_dir,
                        delay_seconds=0,
                        limit=None,
                        client=FakePipelineClient(),
                        analyzer=failing_analyzer,
                    )

            self.assertEqual(self._snapshot(output_dir), before)
            self.assertEqual(list(root.glob(".output.*")), [])

    def test_pipeline_rejects_missing_mandatory_staged_artifacts(self):
        for callback_kind in ("noop", "partial"):
            with self.subTest(callback_kind=callback_kind):
                with TemporaryDirectory() as directory:
                    root = Path(directory)
                    output_dir = root / "output"
                    self._write_existing_artifacts(output_dir)
                    before = self._snapshot(output_dir)

                    def exporter(records, staging_dir):
                        if callback_kind == "partial":
                            (staging_dir / "competitions.json").write_bytes(b"[]")

                    def analyzer(records, staging_dir, failed_pages, collected_at):
                        if callback_kind == "partial":
                            (staging_dir / "summary.json").write_bytes(b"{}")

                    with self.assertLogs("potanin_parser", level="WARNING"):
                        with self.assertRaisesRegex(
                            RuntimeError, "missing mandatory staged artifacts"
                        ) as context:
                            run_pipeline(
                                catalog_url="https://example.test/competitions/",
                                output_dir=output_dir,
                                delay_seconds=0,
                                limit=None,
                                client=FakePipelineClient(),
                                exporter=exporter,
                                analyzer=analyzer,
                            )

                    if callback_kind == "partial":
                        self.assertIn("competitions.csv", str(context.exception))
                    self.assertEqual(self._snapshot(output_dir), before)
                    self.assertEqual(list(root.glob(".output.*")), [])

    def test_pipeline_rejects_non_regular_mandatory_staged_artifact(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            self._write_existing_artifacts(output_dir)
            before = self._snapshot(output_dir)

            def exporter(records, staging_dir):
                (staging_dir / "competitions.json").write_bytes(b"[]")
                (staging_dir / "competitions.csv").mkdir()

            def analyzer(records, staging_dir, failed_pages, collected_at):
                (staging_dir / "summary.json").write_bytes(b"{}")

            with self.assertLogs("potanin_parser", level="WARNING"):
                with self.assertRaisesRegex(
                    RuntimeError, "non-regular mandatory staged artifacts"
                ):
                    run_pipeline(
                        catalog_url="https://example.test/competitions/",
                        output_dir=output_dir,
                        delay_seconds=0,
                        limit=None,
                        client=FakePipelineClient(),
                        exporter=exporter,
                        analyzer=analyzer,
                    )

            self.assertEqual(self._snapshot(output_dir), before)
            self.assertEqual(list(root.glob(".output.*")), [])

    def test_staged_validation_failure_does_not_create_output_directory(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "output"

            with self.assertLogs("potanin_parser", level="WARNING"):
                with self.assertRaisesRegex(
                    RuntimeError, "missing mandatory staged artifacts"
                ):
                    run_pipeline(
                        catalog_url="https://example.test/competitions/",
                        output_dir=output_dir,
                        delay_seconds=0,
                        limit=None,
                        client=FakePipelineClient(),
                        exporter=lambda records, staging_dir: None,
                        analyzer=lambda records, staging_dir, failed, collected: None,
                    )

            self.assertFalse(output_dir.exists())

    def test_pipeline_publishes_complete_set_and_preserves_unrelated_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            self._write_existing_artifacts(output_dir)

            with self.assertLogs("potanin_parser", level="WARNING"):
                run_pipeline(
                    catalog_url="https://example.test/competitions/",
                    output_dir=output_dir,
                    delay_seconds=0,
                    limit=None,
                    client=FakePipelineClient(),
                )

            records = json.loads(
                (output_dir / "competitions.json").read_text(encoding="utf-8")
            )
            summary = json.loads(
                (output_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(records[0]["title"], "Рабочий конкурс")
            self.assertEqual(summary["record_count"], 1)
            self.assertEqual(summary["generated_charts"], [])
            self.assertTrue((output_dir / "competitions.csv").read_bytes())
            for name in (
                "statuses.png",
                "deadlines.png",
                "maximum_support.png",
                "grant_funds.png",
            ):
                self.assertFalse((output_dir / "charts" / name).exists())
            self.assertEqual((output_dir / "run.log").read_bytes(), b"existing log")
            self.assertEqual((output_dir / "custom.txt").read_bytes(), b"custom output")
            self.assertEqual(
                (output_dir / "charts" / "custom.png").read_bytes(),
                b"custom chart",
            )
            self.assertEqual(list(root.glob(".output.*")), [])

    def test_pipeline_rolls_back_mid_publication_failure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            self._write_existing_artifacts(output_dir)
            before = self._snapshot(output_dir)
            from potanin_parser import cli

            real_replace = cli.os.replace
            calls = 0

            def failing_replace(source, destination):
                nonlocal calls
                calls += 1
                if calls == 9:
                    raise OSError("publication failed")
                return real_replace(source, destination)

            with patch("potanin_parser.cli.os.replace", side_effect=failing_replace):
                with self.assertLogs("potanin_parser", level="WARNING"):
                    with self.assertRaisesRegex(OSError, "publication failed"):
                        run_pipeline(
                            catalog_url="https://example.test/competitions/",
                            output_dir=output_dir,
                            delay_seconds=0,
                            limit=None,
                            client=FakePipelineClient(),
                        )

            self.assertEqual(self._snapshot(output_dir), before)
            self.assertEqual(list(root.glob(".output.*")), [])

    def test_pipeline_rollback_restores_relative_and_broken_symlinks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            self._write_existing_artifacts(output_dir)
            targets_dir = output_dir / "targets"
            targets_dir.mkdir()
            (targets_dir / "old.json").write_bytes(b"old target")

            json_path = output_dir / "competitions.json"
            csv_path = output_dir / "competitions.csv"
            json_path.unlink()
            csv_path.unlink()
            json_path.symlink_to("targets/old.json")
            csv_path.symlink_to("missing.csv")

            from potanin_parser import cli

            real_replace = cli.os.replace

            def failing_replace(source, destination):
                source = Path(source)
                if (
                    ".output.staging-" in source.parent.name
                    and source.name == "summary.json"
                ):
                    raise OSError("publication failed")
                return real_replace(source, destination)

            with patch("potanin_parser.cli.os.replace", side_effect=failing_replace):
                with self.assertLogs("potanin_parser", level="WARNING"):
                    with self.assertRaisesRegex(OSError, "publication failed"):
                        run_pipeline(
                            catalog_url="https://example.test/competitions/",
                            output_dir=output_dir,
                            delay_seconds=0,
                            limit=None,
                            client=FakePipelineClient(),
                        )

            self.assertTrue(json_path.is_symlink())
            self.assertEqual(json_path.readlink(), Path("targets/old.json"))
            self.assertTrue(csv_path.is_symlink())
            self.assertEqual(csv_path.readlink(), Path("missing.csv"))
            self.assertEqual((targets_dir / "old.json").read_bytes(), b"old target")
            self.assertEqual(list(root.glob(".output.*")), [])

    def test_successful_publication_replaces_managed_links_and_directories(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            self._write_existing_artifacts(output_dir)
            targets_dir = output_dir / "targets"
            targets_dir.mkdir()
            (targets_dir / "old.json").write_bytes(b"old target")

            json_path = output_dir / "competitions.json"
            status_path = output_dir / "charts" / "statuses.png"
            stale_path = output_dir / "charts" / "grant_funds.png"
            json_path.unlink()
            status_path.unlink()
            stale_path.unlink()
            json_path.symlink_to("targets/old.json")
            status_path.mkdir()
            stale_path.symlink_to("missing-grant.png")

            with self.assertLogs("potanin_parser", level="WARNING"):
                run_pipeline(
                    catalog_url="https://example.test/competitions/",
                    output_dir=output_dir,
                    delay_seconds=0,
                    limit=None,
                    client=FakePipelineClient(),
                )

            self.assertTrue(json_path.is_file())
            self.assertFalse(json_path.is_symlink())
            self.assertFalse(status_path.exists())
            self.assertFalse(status_path.is_symlink())
            self.assertFalse(stale_path.exists())
            self.assertFalse(stale_path.is_symlink())
            self.assertEqual((output_dir / "custom.txt").read_bytes(), b"custom output")
            self.assertEqual(
                (output_dir / "charts" / "custom.png").read_bytes(),
                b"custom chart",
            )
            self.assertEqual(list(root.glob(".output.*")), [])

    def test_successful_publication_does_not_follow_output_charts_symlink(self):
        for link_kind in ("relative", "absolute"):
            with self.subTest(link_kind=link_kind):
                with TemporaryDirectory() as directory:
                    root = Path(directory)
                    output_dir = root / "output"
                    external_dir = root / "external"
                    external_dir.mkdir()
                    (external_dir / "statuses.png").write_bytes(b"external status")
                    (external_dir / "custom.png").write_bytes(b"external custom")
                    self._write_existing_artifacts(output_dir)
                    charts_path = output_dir / "charts"
                    for child in charts_path.iterdir():
                        child.unlink()
                    charts_path.rmdir()
                    target = (
                        Path("../external")
                        if link_kind == "relative"
                        else external_dir
                    )
                    charts_path.symlink_to(target, target_is_directory=True)

                    def analyzer(records, staging_dir, failed_pages, collected_at):
                        self._minimal_analysis(
                            records, staging_dir, failed_pages, collected_at
                        )
                        staged_charts = staging_dir / "charts"
                        staged_charts.mkdir()
                        (staged_charts / "statuses.png").write_bytes(b"new status")

                    with self.assertLogs("potanin_parser", level="WARNING"):
                        run_pipeline(
                            catalog_url="https://example.test/competitions/",
                            output_dir=output_dir,
                            delay_seconds=0,
                            limit=None,
                            client=FakePipelineClient(),
                            exporter=self._minimal_export,
                            analyzer=analyzer,
                        )

                    self.assertTrue(charts_path.is_dir())
                    self.assertFalse(charts_path.is_symlink())
                    self.assertEqual(
                        (charts_path / "statuses.png").read_bytes(), b"new status"
                    )
                    self.assertEqual(
                        (external_dir / "statuses.png").read_bytes(),
                        b"external status",
                    )
                    self.assertEqual(
                        (external_dir / "custom.png").read_bytes(),
                        b"external custom",
                    )
                    self.assertEqual(
                        (output_dir / "custom.txt").read_bytes(), b"custom output"
                    )

    def test_publication_failure_restores_output_charts_symlink(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            external_dir = root / "external"
            external_dir.mkdir()
            (external_dir / "statuses.png").write_bytes(b"external status")
            (external_dir / "custom.png").write_bytes(b"external custom")
            self._write_existing_artifacts(output_dir)
            charts_path = output_dir / "charts"
            for child in charts_path.iterdir():
                child.unlink()
            charts_path.rmdir()
            charts_path.symlink_to("../external", target_is_directory=True)

            def analyzer(records, staging_dir, failed_pages, collected_at):
                self._minimal_analysis(
                    records, staging_dir, failed_pages, collected_at
                )
                staged_charts = staging_dir / "charts"
                staged_charts.mkdir()
                (staged_charts / "statuses.png").write_bytes(b"new status")

            from potanin_parser import cli

            real_replace = cli.os.replace

            def failing_replace(source, destination):
                source = Path(source)
                if source.parent.name == "charts" and source.name == "statuses.png":
                    raise OSError("chart publication failed")
                return real_replace(source, destination)

            with patch("potanin_parser.cli.os.replace", side_effect=failing_replace):
                with self.assertLogs("potanin_parser", level="WARNING"):
                    with self.assertRaisesRegex(OSError, "chart publication failed"):
                        run_pipeline(
                            catalog_url="https://example.test/competitions/",
                            output_dir=output_dir,
                            delay_seconds=0,
                            limit=None,
                            client=FakePipelineClient(),
                            exporter=self._minimal_export,
                            analyzer=analyzer,
                        )

            self.assertTrue(charts_path.is_symlink())
            self.assertEqual(charts_path.readlink(), Path("../external"))
            self.assertEqual(
                (external_dir / "statuses.png").read_bytes(), b"external status"
            )
            self.assertEqual(
                (external_dir / "custom.png").read_bytes(), b"external custom"
            )
            self.assertEqual(list(root.glob(".output.*")), [])

    def test_pipeline_rejects_unsafe_staged_charts_before_output_changes(self):
        for unsafe_kind in ("charts_symlink", "chart_symlink"):
            with self.subTest(unsafe_kind=unsafe_kind):
                with TemporaryDirectory() as directory:
                    root = Path(directory)
                    output_dir = root / "output"
                    external_dir = root / "external"
                    external_dir.mkdir()
                    (external_dir / "statuses.png").write_bytes(b"external status")
                    self._write_existing_artifacts(output_dir)
                    before = self._snapshot(output_dir)

                    def analyzer(records, staging_dir, failed_pages, collected_at):
                        self._minimal_analysis(
                            records, staging_dir, failed_pages, collected_at
                        )
                        staged_charts = staging_dir / "charts"
                        if unsafe_kind == "charts_symlink":
                            staged_charts.symlink_to(
                                external_dir, target_is_directory=True
                            )
                        else:
                            staged_charts.mkdir()
                            (staged_charts / "statuses.png").symlink_to(
                                external_dir / "statuses.png"
                            )

                    with self.assertLogs("potanin_parser", level="WARNING"):
                        with self.assertRaisesRegex(
                            RuntimeError, "unsafe staged charts"
                        ):
                            run_pipeline(
                                catalog_url="https://example.test/competitions/",
                                output_dir=output_dir,
                                delay_seconds=0,
                                limit=None,
                                client=FakePipelineClient(),
                                exporter=self._minimal_export,
                                analyzer=analyzer,
                            )

                    self.assertEqual(self._snapshot(output_dir), before)
                    self.assertEqual(
                        (external_dir / "statuses.png").read_bytes(),
                        b"external status",
                    )
                    self.assertEqual(list(root.glob(".output.*")), [])

    def test_incomplete_rollback_preserves_recovery_backups(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            self._write_existing_artifacts(output_dir)
            from potanin_parser import cli

            real_replace = cli.os.replace

            def failing_replace(source, destination):
                source = Path(source)
                destination = Path(destination)
                if ".output.staging-" in source.parent.name and source.name == "competitions.csv":
                    raise OSError("publication unavailable")
                if ".output.recovery-" in source.parent.name and destination.name == "competitions.csv":
                    raise OSError("rollback unavailable")
                return real_replace(source, destination)

            with patch("potanin_parser.cli.os.replace", side_effect=failing_replace):
                with self.assertLogs("potanin_parser", level="WARNING"):
                    with self.assertRaisesRegex(
                        RuntimeError, "recovery"
                    ) as context:
                        run_pipeline(
                            catalog_url="https://example.test/competitions/",
                            output_dir=output_dir,
                            delay_seconds=0,
                            limit=None,
                            client=FakePipelineClient(),
                        )

            recovery_dirs = list(root.glob(".output.recovery-*"))
            self.assertEqual(len(recovery_dirs), 1)
            recovery_dir = recovery_dirs[0]
            self.assertIn(str(recovery_dir), str(context.exception))
            self.assertIn("publication unavailable", str(context.exception))
            self.assertIn("rollback unavailable", str(context.exception))
            self.assertEqual(str(context.exception.__cause__), "publication unavailable")
            self.assertEqual(
                [str(error) for error in context.exception.rollback_errors],
                ["rollback unavailable"],
            )
            self.assertEqual(
                (recovery_dir / "competitions.csv").read_bytes(),
                b"old:competitions.csv",
            )

    def test_pipeline_rejects_invalid_delay_before_io(self):
        cases = (
            (float("nan"), "finite"),
            (float("inf"), "finite"),
            (float("-inf"), "finite"),
            (-1.0, "negative"),
        )
        for delay, message in cases:
            with self.subTest(delay=delay):
                with TemporaryDirectory() as directory:
                    output_dir = Path(directory) / "output"
                    client = FakePipelineClient()

                    with self.assertRaisesRegex(ValueError, message):
                        run_pipeline(
                            catalog_url="https://example.test/competitions/",
                            output_dir=output_dir,
                            delay_seconds=delay,
                            limit=None,
                            client=client,
                        )

                    self.assertFalse(output_dir.exists())
                    self.assertEqual(client.urls, [])

    def test_pipeline_rejects_symlinked_output_root_before_network_io(self):
        for link_kind in ("relative", "absolute"):
            with self.subTest(link_kind=link_kind):
                with TemporaryDirectory() as directory:
                    root = Path(directory)
                    external_dir = root / "external"
                    external_dir.mkdir()
                    (external_dir / "competitions.json").write_bytes(
                        b"external managed"
                    )
                    (external_dir / "custom.txt").write_bytes(b"external custom")
                    output_dir = root / "output"
                    target = (
                        Path("external")
                        if link_kind == "relative"
                        else external_dir
                    )
                    output_dir.symlink_to(target, target_is_directory=True)
                    client = FakePipelineClient()

                    with self.assertRaisesRegex(
                        ValueError, "output_dir must be a real directory"
                    ):
                        run_pipeline(
                            catalog_url="https://example.test/competitions/",
                            output_dir=output_dir,
                            delay_seconds=0,
                            limit=None,
                            client=client,
                        )

                    self.assertEqual(client.urls, [])
                    self.assertTrue(output_dir.is_symlink())
                    self.assertEqual(output_dir.readlink(), target)
                    self.assertEqual(
                        (external_dir / "competitions.json").read_bytes(),
                        b"external managed",
                    )
                    self.assertEqual(
                        (external_dir / "custom.txt").read_bytes(),
                        b"external custom",
                    )

    def test_pipeline_rejects_non_directory_output_root_before_network_io(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "output"
            output_dir.write_bytes(b"existing file")
            client = FakePipelineClient()

            with self.assertRaisesRegex(
                ValueError, "output_dir must be a real directory"
            ):
                run_pipeline(
                    catalog_url="https://example.test/competitions/",
                    output_dir=output_dir,
                    delay_seconds=0,
                    limit=None,
                    client=client,
                )

            self.assertEqual(client.urls, [])
            self.assertEqual(output_dir.read_bytes(), b"existing file")

    def test_pipeline_rejects_missing_output_below_symlink_parent(self):
        for link_kind in ("relative", "absolute"):
            for missing_parts in (("new",), ("missing", "new")):
                with self.subTest(
                    link_kind=link_kind, missing_parts=missing_parts
                ):
                    with TemporaryDirectory() as directory:
                        root = Path(directory)
                        external_dir = root / "external"
                        external_dir.mkdir()
                        sentinel = external_dir / "sentinel.txt"
                        sentinel.write_bytes(b"external sentinel")
                        link = root / "link"
                        target = (
                            Path("external")
                            if link_kind == "relative"
                            else external_dir
                        )
                        link.symlink_to(target, target_is_directory=True)
                        output_dir = link.joinpath(*missing_parts)
                        client = FakePipelineClient()

                        with self.assertRaisesRegex(
                            ValueError, "output_dir must be below a real directory"
                        ):
                            run_pipeline(
                                catalog_url="https://example.test/competitions/",
                                output_dir=output_dir,
                                delay_seconds=0,
                                limit=None,
                                client=client,
                            )

                        self.assertEqual(client.urls, [])
                        self.assertEqual(sentinel.read_bytes(), b"external sentinel")
                        self.assertFalse(
                            external_dir.joinpath(*missing_parts).exists()
                        )

    def test_pipeline_rejects_existing_directory_below_symlink_component(self):
        for link_kind in ("relative", "absolute"):
            with self.subTest(link_kind=link_kind):
                with TemporaryDirectory() as directory:
                    root = Path(directory)
                    external_dir = root / "external"
                    existing_dir = external_dir / "existing"
                    existing_dir.mkdir(parents=True)
                    sentinel = existing_dir / "sentinel.txt"
                    sentinel.write_bytes(b"external sentinel")
                    link = root / "link"
                    target = (
                        Path("external")
                        if link_kind == "relative"
                        else external_dir
                    )
                    link.symlink_to(target, target_is_directory=True)
                    output_dir = link / "existing" / "new"
                    client = FakePipelineClient()

                    with self.assertRaisesRegex(
                        ValueError, "output_dir must be below a real directory"
                    ):
                        run_pipeline(
                            catalog_url="https://example.test/competitions/",
                            output_dir=output_dir,
                            delay_seconds=0,
                            limit=None,
                            client=client,
                        )

                    self.assertEqual(client.urls, [])
                    self.assertEqual(sentinel.read_bytes(), b"external sentinel")
                    self.assertFalse((existing_dir / "new").exists())


class CliTests(unittest.TestCase):
    def test_cli_rejects_non_finite_delays(self):
        for delay in ("nan", "inf", "-inf"):
            with self.subTest(delay=delay):
                with (
                    patch("potanin_parser.cli.configure_logging") as configure,
                    patch("potanin_parser.cli.run_pipeline") as pipeline,
                    self.assertRaisesRegex(SystemExit, "finite"),
                ):
                    main([f"--delay={delay}"])
                configure.assert_not_called()
                pipeline.assert_not_called()

    def test_cli_validates_output_before_configuring_logging(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            external_dir = root / "external"
            external_dir.mkdir()
            (external_dir / "run.log").write_bytes(b"existing log")
            (external_dir / "competitions.json").write_bytes(b"managed data")
            (external_dir / "custom.txt").write_bytes(b"custom data")
            output_dir = root / "output"
            output_dir.symlink_to(external_dir, target_is_directory=True)

            with (
                patch("potanin_parser.cli.configure_logging") as configure,
                patch("potanin_parser.cli.run_pipeline") as pipeline,
                self.assertRaisesRegex(
                    ValueError, "output_dir must be a real directory"
                ),
            ):
                main(["--output", str(output_dir), "--delay", "0"])

            configure.assert_not_called()
            pipeline.assert_not_called()
            self.assertEqual(
                (external_dir / "run.log").read_bytes(), b"existing log"
            )
            self.assertEqual(
                (external_dir / "competitions.json").read_bytes(), b"managed data"
            )
            self.assertEqual(
                (external_dir / "custom.txt").read_bytes(), b"custom data"
            )

    def test_default_analyzer_records_chart_paths_relative_to_output(self):
        record = Competition(
            source="Фонд Потанина",
            source_url="https://example.test/competition",
            collected_at="2026-06-13T00:00:00+07:00",
            title="Конкурс",
            status="Открыт",
        )

        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            summary = _default_analyzer(
                [record],
                output_dir,
                failed_pages=0,
                collected_at=record.collected_at,
            )

        self.assertEqual(summary["generated_charts"], ["charts/statuses.png"])


if __name__ == "__main__":
    unittest.main()

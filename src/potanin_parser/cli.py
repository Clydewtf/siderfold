import argparse
import json
import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .client import HttpClient
from .html_parser import parse_catalog, parse_competition
from .models import Competition


DEFAULT_CATALOG_URL = "https://fondpotanin.ru/competitions/"
LOGGER = logging.getLogger("potanin_parser")
Exporter = Callable[[list[Competition], Path], object]
Analyzer = Callable[[list[Competition], Path, int, str], object]


def _show_all_url(catalog_url: str) -> str:
    parts = urlsplit(catalog_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["SHOWALL_1"] = "1"
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _default_exporter(records: list[Competition], output_dir: Path) -> object:
    from .exporters import export_records

    return export_records(records, output_dir)


def _default_analyzer(
    records: list[Competition],
    output_dir: Path,
    failed_pages: int,
    collected_at: str,
) -> object:
    from .analytics import build_summary, generate_charts

    summary = build_summary(
        records,
        collected_at=collected_at,
        failed_pages=failed_pages,
    )
    chart_files = generate_charts(records, output_dir / "charts")
    summary["generated_charts"] = [str(path) for path in chart_files]
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def run_pipeline(
    catalog_url: str,
    output_dir: Path,
    delay_seconds: float,
    limit: int | None,
    client: HttpClient | None = None,
    exporter: Exporter | None = None,
    analyzer: Analyzer | None = None,
) -> list[Competition]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    http_client = client or HttpClient(delay_seconds=delay_seconds)
    collected_at = datetime.now(timezone.utc).isoformat()

    catalog_html = http_client.get(_show_all_url(catalog_url))
    links = parse_catalog(catalog_html, catalog_url)
    if limit is not None:
        links = links[:limit]

    records: list[Competition] = []
    failed_pages = 0
    for index, url in enumerate(links):
        try:
            html = http_client.get(url)
            records.append(parse_competition(html, url, collected_at))
        except Exception as error:
            failed_pages += 1
            LOGGER.warning("Failed to process card %s: %s", url, error)

        if delay_seconds and index + 1 < len(links):
            time.sleep(delay_seconds)

    (exporter or _default_exporter)(records, output_dir)
    (analyzer or _default_analyzer)(
        records,
        output_dir,
        failed_pages,
        collected_at,
    )
    return records


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Fond Potanin competitions")
    parser.add_argument("--catalog-url", default=DEFAULT_CATALOG_URL)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--limit", type=_positive_int)
    return parser


def configure_logging(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    file_handler = logging.FileHandler(output_dir / "run.log", encoding="utf-8")
    console_handler = logging.StreamHandler()
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.delay < 0:
        raise SystemExit("--delay must not be negative")
    configure_logging(args.output)
    run_pipeline(
        catalog_url=args.catalog_url,
        output_dir=args.output,
        delay_seconds=args.delay,
        limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

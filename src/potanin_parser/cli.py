import argparse
import json
import logging
import math
import os
import shutil
import stat
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ._path_safety import validate_directory_path
from .client import HttpClient
from .html_parser import parse_catalog, parse_competition
from .models import Competition


DEFAULT_CATALOG_URL = "https://fondpotanin.ru/competitions/"
UNKNOWN_SOURCE = "unknown source"
LOGGER = logging.getLogger("potanin_parser")
Exporter = Callable[[list[Competition], Path], object]
Analyzer = Callable[[list[Competition], Path, int, str, str], object]
MANAGED_ROOT_FILENAMES = (
    "competitions.json",
    "competitions.csv",
    "summary.json",
)


class ArtifactPublicationError(RuntimeError):
    def __init__(
        self,
        publication_error: Exception,
        rollback_errors: list[Exception],
        recovery_dir: Path,
    ) -> None:
        self.publication_error = publication_error
        self.rollback_errors = rollback_errors
        self.recovery_dir = recovery_dir
        rollback_details = "; ".join(str(error) for error in rollback_errors)
        super().__init__(
            f"Artifact publication failed: {publication_error}; "
            f"rollback incomplete: {rollback_details}; "
            f"recoverable backups preserved at {recovery_dir}"
        )


def _show_all_url(catalog_url: str) -> str:
    parts = urlsplit(catalog_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["SHOWALL_1"] = "1"
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _catalog_source(catalog_url: str) -> str:
    stripped_url = catalog_url.strip()
    return urlsplit(stripped_url).hostname or stripped_url or UNKNOWN_SOURCE


def _default_exporter(records: list[Competition], output_dir: Path) -> object:
    from .exporters import export_records

    return export_records(records, output_dir)


def _default_analyzer(
    records: list[Competition],
    output_dir: Path,
    failed_pages: int,
    collected_at: str,
    source: str,
) -> object:
    from .analytics import build_summary, generate_charts

    summary = build_summary(
        records,
        collected_at=collected_at,
        failed_pages=failed_pages,
        source=source,
    )
    chart_files = generate_charts(records, output_dir / "charts")
    summary["generated_charts"] = [
        str(path.relative_to(output_dir)) for path in chart_files
    ]
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _managed_chart_paths() -> list[Path]:
    from .analytics import MANAGED_CHART_FILENAMES

    return [
        Path("charts") / filename for filename in sorted(MANAGED_CHART_FILENAMES)
    ]


def _entry_mode(path: Path) -> int | None:
    try:
        return path.stat(follow_symlinks=False).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return None


def _validate_output_dir(output_dir: Path) -> None:
    validate_directory_path(output_dir, label="output_dir")


def _validate_staged_artifacts(staging_dir: Path) -> None:
    missing = []
    non_regular = []
    for filename in MANAGED_ROOT_FILENAMES:
        path = staging_dir / filename
        try:
            mode = path.stat(follow_symlinks=False).st_mode
        except FileNotFoundError:
            missing.append(filename)
            continue
        if not stat.S_ISREG(mode):
            non_regular.append(filename)

    if missing:
        raise RuntimeError(
            f"missing mandatory staged artifacts: {', '.join(missing)}"
        )
    if non_regular:
        raise RuntimeError(
            "non-regular mandatory staged artifacts: "
            f"{', '.join(non_regular)}"
        )

    charts_dir = staging_dir / "charts"
    charts_mode = _entry_mode(charts_dir)
    if charts_mode is None:
        return
    if not stat.S_ISDIR(charts_mode):
        raise RuntimeError("unsafe staged charts directory: must be a real directory")

    unsafe_charts = []
    for relative_path in _managed_chart_paths():
        chart_mode = _entry_mode(staging_dir / relative_path)
        if chart_mode is not None and not stat.S_ISREG(chart_mode):
            unsafe_charts.append(relative_path.name)
    if unsafe_charts:
        raise RuntimeError(
            "unsafe staged charts: expected regular files: "
            f"{', '.join(unsafe_charts)}"
        )


def _entry_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _remove_entry(path: Path) -> None:
    try:
        mode = path.stat(follow_symlinks=False).st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _publish_staged_artifacts(staging_dir: Path, output_dir: Path) -> None:
    _validate_output_dir(output_dir)
    _validate_staged_artifacts(staging_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    root_paths = [Path(filename) for filename in MANAGED_ROOT_FILENAMES]
    chart_paths = _managed_chart_paths()
    prefix = f".{output_dir.name}.recovery-"
    backup_dir = Path(mkdtemp(prefix=prefix, dir=output_dir.parent))
    backed_up: list[Path] = []
    published: list[Path] = []
    try:
        for relative_path in root_paths:
            destination = output_dir / relative_path
            if _entry_exists(destination):
                backup = backup_dir / relative_path
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
                backed_up.append(relative_path)

        output_charts = output_dir / "charts"
        output_charts_mode = _entry_mode(output_charts)
        if output_charts_mode is not None and not stat.S_ISDIR(output_charts_mode):
            backup = backup_dir / "charts"
            os.replace(output_charts, backup)
            backed_up.append(Path("charts"))
        elif output_charts_mode is not None:
            for relative_path in chart_paths:
                destination = output_dir / relative_path
                if _entry_exists(destination):
                    backup = backup_dir / relative_path
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, backup)
                    backed_up.append(relative_path)

        for relative_path in root_paths:
            staged = staging_dir / relative_path
            if staged.is_file():
                destination = output_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, destination)
                published.append(relative_path)

        staged_chart_paths = [
            relative_path
            for relative_path in chart_paths
            if _entry_mode(staging_dir / relative_path) is not None
        ]
        if staged_chart_paths and not _entry_exists(output_charts):
            output_charts.mkdir()
            published.append(Path("charts"))
        for relative_path in staged_chart_paths:
            staged = staging_dir / relative_path
            destination = output_dir / relative_path
            os.replace(staged, destination)
            published.append(relative_path)
    except Exception as publication_error:
        rollback_errors = []
        for relative_path in reversed(published):
            destination = output_dir / relative_path
            try:
                _remove_entry(destination)
            except Exception as rollback_error:
                rollback_errors.append(rollback_error)
        for relative_path in reversed(backed_up):
            backup = backup_dir / relative_path
            if not _entry_exists(backup):
                continue
            try:
                destination = output_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, destination)
            except Exception as rollback_error:
                rollback_errors.append(rollback_error)

        if rollback_errors:
            raise ArtifactPublicationError(
                publication_error,
                rollback_errors,
                backup_dir,
            ) from publication_error
        shutil.rmtree(backup_dir)
        raise
    else:
        shutil.rmtree(backup_dir)


def _validate_delay_seconds(delay_seconds: float) -> None:
    if not math.isfinite(delay_seconds):
        raise ValueError("delay_seconds must be finite")
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative")


def run_pipeline(
    catalog_url: str,
    output_dir: Path,
    delay_seconds: float,
    limit: int | None,
    client: HttpClient | None = None,
    exporter: Exporter | None = None,
    analyzer: Analyzer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Competition]:
    output_dir = Path(output_dir)
    _validate_delay_seconds(delay_seconds)
    _validate_output_dir(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    http_client = client or HttpClient(delay_seconds=delay_seconds)
    collected_at = datetime.now(timezone.utc).isoformat()
    source = _catalog_source(catalog_url)

    catalog_html = http_client.get(_show_all_url(catalog_url))
    links = parse_catalog(catalog_html, catalog_url)
    if limit is not None:
        links = links[:limit]

    records: list[Competition] = []
    failed_pages = 0
    for url in links:
        if delay_seconds:
            sleep(delay_seconds)
        try:
            html = http_client.get(url)
            records.append(parse_competition(html, url, collected_at))
        except Exception as error:
            failed_pages += 1
            LOGGER.warning("Failed to process card %s: %s", url, error)

    staging_prefix = f".{output_dir.name}.staging-"
    with TemporaryDirectory(prefix=staging_prefix, dir=output_dir.parent) as name:
        staging_dir = Path(name)
        (exporter or _default_exporter)(records, staging_dir)
        (analyzer or _default_analyzer)(
            records,
            staging_dir,
            failed_pages,
            collected_at,
            source,
        )
        _publish_staged_artifacts(staging_dir, output_dir)
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
    if not math.isfinite(args.delay):
        raise SystemExit("--delay must be finite")
    if args.delay < 0:
        raise SystemExit("--delay must not be negative")
    _validate_output_dir(args.output)
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

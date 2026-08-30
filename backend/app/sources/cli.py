from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.core.config import get_settings
from app.db.session import create_db_engine
from app.sources.registry import RegistryValidationError, load_registry
from app.sources.runner import list_registered_sources, run_registered_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and run allowlisted Siderfold source adapters."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        help="Path to the source registry TOML (defaults to SOURCE_REGISTRY_PATH)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List registered sources")
    dry_run = subparsers.add_parser("dry-run", help="Run an adapter without database writes")
    dry_run.add_argument("source_key")
    run = subparsers.add_parser("run", help="Run an adapter and persist raw/staging data")
    run.add_argument("source_key")
    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    registry_path = args.registry or settings.source_registry_path

    try:
        if args.command == "list":
            _print_json(list_registered_sources(load_registry(registry_path)))
            return 0

        if args.command == "dry-run":
            report = run_registered_source(
                args.source_key,
                registry_path=registry_path,
                dry_run=True,
                raw_capture_dir=settings.raw_capture_dir,
            )
        else:
            engine = create_db_engine(settings)
            try:
                report = run_registered_source(
                    args.source_key,
                registry_path=registry_path,
                engine=engine,
                raw_capture_dir=settings.raw_capture_dir,
            )
            finally:
                engine.dispose()
    except (RegistryValidationError, ValueError) as error:
        _print_json({"status": "failed", "error": str(error)})
        return 2

    _print_json(report.model_dump(mode="json"))
    return 2 if report.status == "failed" or report.statistics.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

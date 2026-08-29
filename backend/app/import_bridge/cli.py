from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.core.config import get_settings
from app.db.session import create_db_engine
from app.import_bridge.contract import PackageValidationError, load_contract
from app.import_bridge.potanin import load_potanin_output
from app.import_bridge.service import ImportReport, import_package


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a versioned local package into Siderfold staging."
    )
    parser.add_argument("input_path", type=Path, help="JSON or CSV input file")
    parser.add_argument(
        "--format",
        dest="input_format",
        choices=("json", "csv", "potanin-json"),
        required=True,
        help="Input contract format; potanin-json adapts the local parser output in memory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run validation and database writes inside a transaction that is rolled back",
    )
    return parser


def _load_package(input_path: Path, input_format: str):
    if input_format == "potanin-json":
        return load_potanin_output(input_path)
    return load_contract(input_path, input_format=input_format)


def _print_report(report: ImportReport) -> None:
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.input_format == "potanin-json" and not args.dry_run:
        parser.error("potanin-json is limited to --dry-run")
    try:
        package = _load_package(args.input_path, args.input_format)
    except PackageValidationError as error:
        _print_report(
            ImportReport.invalid_package(error.issues).model_copy(update={"dry_run": args.dry_run})
        )
        return 2

    engine = create_db_engine(get_settings())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                report = import_package(connection, package)
            except Exception:
                transaction.rollback()
                raise
            if args.dry_run:
                transaction.rollback()
                report = report.model_copy(update={"dry_run": True})
            else:
                transaction.commit()
    finally:
        engine.dispose()

    _print_report(report)
    return 2 if report.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.session import create_db_engine
from app.sources.registry import RegistryValidationError, load_registry
from app.sources.operations import (
    SourceExecutionResult,
    list_execution_runs,
    prune_execution_journal,
    run_due_sources,
    run_managed_source,
)
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
    schedule_once = subparsers.add_parser(
        "schedule-once",
        help="Run only sources due at one UTC minute, then exit",
    )
    schedule_once.add_argument(
        "--at",
        type=_parse_timestamp,
        help="UTC evaluation time in ISO-8601 format; defaults to the current time",
    )
    runs = subparsers.add_parser("runs", help="Show recent managed source executions")
    runs.add_argument("--source-key")
    runs.add_argument("--limit", type=int, default=50)
    prune = subparsers.add_parser(
        "prune-journal",
        help="Explicitly remove old operational journal rows without touching provenance",
    )
    prune.add_argument("--retention-days", type=int)
    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _print_progress(source_key: str, message: str) -> None:
    sys.stderr.write(f"[sources:{source_key}] {message}\n")
    sys.stderr.flush()


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--at must include a timezone offset")
    return parsed


def _notify_failure(result: SourceExecutionResult) -> None:
    if not result.is_failure:
        return
    payload = {
        "event": "source_execution_failed",
        "source_key": result.source_key,
        "execution_id": str(result.execution_id),
        "error_codes": list(result.error_codes),
    }
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    registry_path = args.registry or settings.source_registry_path

    try:
        if args.command == "list":
            _print_json(list_registered_sources(load_registry(registry_path)))
            return 0

        if args.command == "dry-run":
            _print_progress(args.source_key, "dry run started")
            report = run_registered_source(
                args.source_key,
                registry_path=registry_path,
                dry_run=True,
                raw_capture_dir=settings.raw_capture_dir,
                progress_reporter=lambda message: _print_progress(
                    args.source_key, message
                ),
            )
            _print_progress(
                args.source_key,
                (
                    f"finished: status={report.status}; "
                    f"fetched={report.statistics.fetched}; "
                    f"artifacts={report.statistics.artifact_fetched}"
                ),
            )
            _print_json(report.model_dump(mode="json"))
            return 2 if report.status == "failed" or report.statistics.errors else 0

        engine = create_db_engine(settings)
        try:
            if args.command == "run":
                _print_progress(args.source_key, "managed run started")
                result = run_managed_source(
                    args.source_key,
                    engine=engine,
                    settings=settings,
                    registry_path=registry_path,
                    progress_reporter=lambda message: _print_progress(
                        args.source_key, message
                    ),
                )
                _print_progress(
                    args.source_key,
                    (
                        f"finished: status={result.status.value}; "
                        f"attempts={result.attempt_count}"
                    ),
                )
                _print_json(result.model_dump(mode="json"))
                _notify_failure(result)
                return 2 if result.is_failure else 0

            if args.command == "schedule-once":
                tick = run_due_sources(
                    engine=engine,
                    settings=settings,
                    registry_path=registry_path,
                    at=args.at,
                )
                _print_json(tick.model_dump(mode="json"))
                for result in tick.results:
                    _notify_failure(result)
                return 2 if tick.has_failures else 0

            if args.command == "runs":
                _print_json(
                    list_execution_runs(
                        engine,
                        source_key=args.source_key,
                        limit=args.limit,
                    )
                )
                return 0

            if args.command == "prune-journal":
                retention_days = (
                    args.retention_days
                    if args.retention_days is not None
                    else settings.scheduler_journal_retention_days
                )
                removed = prune_execution_journal(
                    engine,
                    retention_days=retention_days,
                )
                _print_json(
                    {
                        "status": "completed",
                        "retention_days": retention_days,
                        "removed_execution_runs": removed,
                    }
                )
                return 0

            raise RuntimeError(f"unsupported source command: {args.command}")
        finally:
            engine.dispose()
    except KeyboardInterrupt:
        sys.stderr.write("Source command interrupted; no further requests will be made.\n")
        return 130
    except (RegistryValidationError, ValueError, SQLAlchemyError) as error:
        _print_json({"status": "failed", "error": str(error)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

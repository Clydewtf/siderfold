from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Sequence
from uuid import UUID

from app.analytics.baseline import compare_snapshot_counts
from app.analytics.snapshots import (
    AnalyticsSnapshotError,
    create_analytics_snapshot,
    get_analytics_snapshot,
    recalculate_snapshot_metrics,
)
from app.core.config import get_settings
from app.db.session import create_db_engine
from app.sources.registry import load_registry


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--at must include a timezone offset")
    return parsed


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("snapshot identifiers must be UUIDs") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or recalculate a reproducible internal catalog analytics snapshot."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        help="Path to the source registry TOML (defaults to SOURCE_REGISTRY_PATH)",
    )
    parser.add_argument(
        "--at",
        type=_parse_timestamp,
        help="Snapshot time in ISO-8601 format; defaults to the current time",
    )
    parser.add_argument(
        "--freshness-window-days",
        type=int,
        default=30,
        help="Rolling observation window used by freshness and source coverage",
    )
    parser.add_argument(
        "--snapshot-id",
        type=_parse_uuid,
        help="Recalculate a stored snapshot from its frozen manifest instead of creating one",
    )
    parser.add_argument(
        "--compare-to",
        type=_parse_uuid,
        help="Optional earlier snapshot ID for a comparable opportunity-count delta",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.freshness_window_days < 1:
        build_parser().error("--freshness-window-days must be positive")
    if args.snapshot_id is not None and args.at is not None:
        build_parser().error("--at cannot be used with --snapshot-id")
    if args.compare_to is not None and args.snapshot_id is None:
        build_parser().error("--compare-to requires --snapshot-id")
    settings = get_settings()
    engine = create_db_engine(settings)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                if args.snapshot_id is None:
                    registry = load_registry(args.registry or settings.source_registry_path)
                    result = create_analytics_snapshot(
                        connection,
                        registry=registry,
                        as_of=args.at,
                        freshness_window_days=args.freshness_window_days,
                    )
                    report = result.report()
                else:
                    snapshot = get_analytics_snapshot(connection, args.snapshot_id)
                    if snapshot is None:
                        build_parser().error(f"snapshot not found: {args.snapshot_id}")
                    try:
                        recalculated = recalculate_snapshot_metrics(snapshot)
                    except AnalyticsSnapshotError as error:
                        build_parser().error(str(error))
                    if recalculated != snapshot.metrics:
                        build_parser().error(
                            "stored metrics differ from the frozen-manifest recalculation"
                        )
                    comparison = None
                    if args.compare_to is not None:
                        previous = get_analytics_snapshot(connection, args.compare_to)
                        if previous is None:
                            build_parser().error(f"comparison snapshot not found: {args.compare_to}")
                        comparison = compare_snapshot_counts(snapshot, previous)
                    report = {
                        "snapshot_id": str(snapshot.id),
                        "created": False,
                        "scope": snapshot.scope,
                        "calculation_version": snapshot.calculation_version,
                        "as_of": snapshot.as_of.isoformat(),
                        "input_fingerprint": snapshot.input_fingerprint,
                        "registry_fingerprint": snapshot.registry_fingerprint,
                        "metrics": recalculated,
                        "comparison": comparison,
                        "limitations": list(snapshot.limitations),
                    }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Sequence

from app.analytics.snapshots import create_analytics_snapshot
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a reproducible internal catalog quality snapshot."
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.freshness_window_days < 1:
        build_parser().error("--freshness-window-days must be positive")
    settings = get_settings()
    registry = load_registry(args.registry or settings.source_registry_path)
    engine = create_db_engine(settings)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                result = create_analytics_snapshot(
                    connection,
                    registry=registry,
                    as_of=args.at,
                    freshness_window_days=args.freshness_window_days,
                )
        print(json.dumps(result.report(), ensure_ascii=False, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

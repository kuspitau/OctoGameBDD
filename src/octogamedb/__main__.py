"""Command-line entry point for OctoGameDB."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from octogamedb.db import DEFAULT_DB_PATH, apply_migrations, connect_database


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m octogamedb")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser(
        "status",
        help="Initialize the database if needed and report foundation status.",
    )
    status_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH}).",
    )

    return parser


def _status(db_path: Path) -> int:
    with connect_database(db_path) as connection:
        apply_migrations(connection)

        row = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM schema_migrations) AS migration_count,
                (SELECT COALESCE(MAX(version), 0) FROM schema_migrations) AS schema_version,
                (SELECT COUNT(*) FROM data_sources) AS source_count,
                (SELECT COUNT(*) FROM import_batches) AS import_batch_count
            """
        ).fetchone()

    print(f"Database: {db_path}")
    print(f"Schema version: {row['schema_version']}")
    print(f"Applied migrations: {row['migration_count']}")
    print(f"Registered sources: {row['source_count']}")
    print(f"Import batches: {row['import_batch_count']}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "status":
        return _status(args.db)

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

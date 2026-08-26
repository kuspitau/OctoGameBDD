from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - project requires Python 3.11+
    tomllib = None  # type: ignore[assignment]

from octogamedb.db import apply_migrations, connect_database
from octogamedb.importers.quest_item_facts import reconcile_quest_item_facts
from octogamedb.importers.quest_source_evidence import (
    SOURCE_TORTOISE,
    TORTOISE_PINNED_REVISION,
    QuestSourceError,
    detect_git_revision,
    load_tortoise_quest_projection,
    write_json,
)
from octogamedb.quest_items import quest_item_facts_by_id

CANONICAL_DB = Path("data/generated/octogamedb.sqlite3")
CANONICAL_BACKUP = Path("data/generated/octogamedb_bak.sqlite3")


def _load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    if tomllib is None:
        raise RuntimeError("Python 3.11+ is required to read TOML configuration")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _configured_path(config: dict[str, Any], key: str) -> Path | None:
    value = config.get("source_paths", {}).get(key)
    return None if not value else Path(str(value)).expanduser()


def _load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise QuestSourceError(f"snapshot must be a JSON object: {path}")
    return payload


def _load_snapshots(paths: list[Path]) -> list[dict[str, Any]]:
    snapshots = [_load_snapshot(path) for path in paths]
    keys = [str(snapshot.get("source_key", "")) for snapshot in snapshots]
    if len(keys) != len(set(keys)):
        raise QuestSourceError("provide at most one JSON snapshot per source_key")
    return snapshots


def cmd_tortoise_full(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.config))
    repo = Path(args.tortoise_repo).expanduser() if args.tortoise_repo else _configured_path(
        config, "tortoise_repo"
    )
    if repo is None:
        raise QuestSourceError(
            "tortoise_repo unresolved; run get_path.bat / validate_p3_t05b.py configure-paths"
        )
    revision = detect_git_revision(repo)
    if revision is None:
        raise QuestSourceError("cannot determine Tortoise Git revision from the configured checkout")
    if not args.allow_unpinned and revision != TORTOISE_PINNED_REVISION:
        raise QuestSourceError(
            f"Tortoise checkout must be {TORTOISE_PINNED_REVISION}, got {revision}"
        )
    projection = load_tortoise_quest_projection(repo, quest_ids=None, source_revision=revision)
    write_json(Path(args.output), projection)
    print(f"wrote {args.output}")
    print(f"source_key={projection['source_key']}")
    print(f"source_revision={projection['source_revision']}")
    print(f"content_hash={projection['content_hash']}")
    print(f"projection_hash={projection['projection_hash']}")
    print(f"quests={len(projection['quests'])}")
    return 0


def _canonical_paths(project_root: Path) -> tuple[Path, Path]:
    return (project_root / CANONICAL_DB).resolve(), (project_root / CANONICAL_BACKUP).resolve()


def _prepare_canonical_backup(database: Path, project_root: Path, canonical: bool) -> None:
    canonical_path, backup_path = _canonical_paths(project_root)
    if database.resolve() != canonical_path:
        if canonical:
            raise QuestSourceError(
                f"--canonical requires --database {canonical_path}; got {database.resolve()}"
            )
        return
    if not canonical:
        raise QuestSourceError(
            "refusing to mutate the canonical DB without --canonical; validate a disposable copy first"
        )
    if not canonical_path.is_file():
        raise QuestSourceError(f"canonical DB does not exist: {canonical_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(canonical_path, backup_path)
    print(f"canonical backup refreshed: {backup_path}")


def _schema_version(connection) -> int:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if table is None:
        return 0
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return 0 if row is None or row[0] is None else int(row[0])


def _db_checks(connection) -> dict[str, Any]:
    version = _schema_version(connection)
    foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
    integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
    if version < 10:
        return {
            "schema_version": version,
            "p3_t05_schema_ready": False,
            "foreign_key_check": foreign_keys,
            "integrity_check": integrity,
            "canonical_counts": {},
        }
    counts = {
        "required_item": int(connection.execute("SELECT COUNT(*) FROM quest_required_items").fetchone()[0]),
        "required_source": int(
            connection.execute("SELECT COUNT(*) FROM quest_required_sources").fetchone()[0]
        ),
        "provided_item": int(
            connection.execute("SELECT COUNT(*) FROM quest_provided_items").fetchone()[0]
        ),
        "reward_item": int(connection.execute("SELECT COUNT(*) FROM quest_reward_items").fetchone()[0]),
        "choice_reward_item": int(
            connection.execute("SELECT COUNT(*) FROM quest_choice_reward_items").fetchone()[0]
        ),
    }
    return {
        "schema_version": version,
        "p3_t05_schema_ready": True,
        "foreign_key_check": foreign_keys,
        "integrity_check": integrity,
        "canonical_counts": counts,
    }


def cmd_apply(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    database = Path(args.database).resolve()
    snapshots = _load_snapshots([Path(path) for path in args.snapshot])
    if not args.allow_without_tortoise and SOURCE_TORTOISE not in {
        snapshot.get("source_key") for snapshot in snapshots
    }:
        raise QuestSourceError(
            "normal P3-T05 validation requires a full Tortoise snapshot; "
            "use --allow-without-tortoise only for bounded diagnostics/tests"
        )
    if args.canonical and not args.twice:
        raise QuestSourceError("--canonical requires --twice for the P3-T05 idempotence gate")
    _prepare_canonical_backup(database, project_root, bool(args.canonical))

    with connect_database(database) as connection:
        applied = apply_migrations(connection)
        print("applied_migrations=" + ",".join(migration.name for migration in applied))
        first = reconcile_quest_item_facts(connection, snapshots=snapshots)
        first_payload = first.to_dict()
        second_payload = None
        if args.twice:
            second = reconcile_quest_item_facts(connection, snapshots=snapshots)
            second_payload = second.to_dict()
            if (
                second.rows_inserted != 0
                or second.rows_updated != 0
                or int(second.details.get("canonical_rows_deleted", 0)) != 0
            ):
                raise QuestSourceError(
                    "same-snapshot second run changed canonical P3-T05 rows: "
                    + json.dumps(second_payload, sort_keys=True)
                )
        checks = _db_checks(connection)
        if not checks["p3_t05_schema_ready"]:
            raise QuestSourceError(
                f"P3-T05 schema is not ready after apply; schema_version={checks['schema_version']}"
            )
        if checks["foreign_key_check"]:
            raise QuestSourceError(
                "foreign_key_check failed: " + json.dumps(checks["foreign_key_check"])
            )
        if checks["integrity_check"] != ["ok"]:
            raise QuestSourceError(
                "integrity_check failed: " + json.dumps(checks["integrity_check"])
            )

    payload = {"first": first_payload, "second": second_payload, "checks": checks}
    if args.output:
        write_json(Path(args.output), payload)
        print(f"wrote {args.output}")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    database = Path(args.database)
    if not database.is_file():
        raise QuestSourceError(f"database does not exist: {database}")
    with connect_database(database) as connection:
        # A check command must be read-only. Migration is performed only by ``apply``, where
        # canonical targets are guarded by the D-029 backup workflow.
        payload = _db_checks(connection)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not payload["p3_t05_schema_ready"]:
        return 5
    return 0 if not payload["foreign_key_check"] and payload["integrity_check"] == ["ok"] else 4


def cmd_quest(args: argparse.Namespace) -> int:
    database = Path(args.database)
    if not database.is_file():
        raise QuestSourceError(f"database does not exist: {database}")
    with connect_database(database) as connection:
        version = _schema_version(connection)
        if version < 10:
            raise QuestSourceError(
                f"P3-T05 query requires schema version 10; current schema version is {version}"
            )
        payload = quest_item_facts_by_id(connection, int(args.quest_id))
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P3-T05 quest item/reward validation helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tortoise = subparsers.add_parser(
        "tortoise-full", help="Build the full pinned Tortoise quest projection for P3-T05"
    )
    tortoise.add_argument("--config", default="config.local.toml")
    tortoise.add_argument("--tortoise-repo")
    tortoise.add_argument("--output", required=True)
    tortoise.add_argument("--allow-unpinned", action="store_true")
    tortoise.set_defaults(func=cmd_tortoise_full)

    apply = subparsers.add_parser(
        "apply", help="Apply migration 10 and reconcile one JSON snapshot per available source"
    )
    apply.add_argument("--database", required=True)
    apply.add_argument("--snapshot", action="append", required=True)
    apply.add_argument("--project-root", default=".")
    apply.add_argument("--twice", action="store_true")
    apply.add_argument("--canonical", action="store_true")
    apply.add_argument("--allow-without-tortoise", action="store_true")
    apply.add_argument("--output")
    apply.set_defaults(func=cmd_apply)

    check = subparsers.add_parser("check", help="Run schema/FK/integrity/count checks")
    check.add_argument("--database", required=True)
    check.set_defaults(func=cmd_check)

    quest = subparsers.add_parser("quest", help="Print the P3-T05 read model for one quest")
    quest.add_argument("--database", required=True)
    quest.add_argument("--quest-id", required=True, type=int)
    quest.set_defaults(func=cmd_quest)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (
        QuestSourceError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        sqlite3.Error,
    ) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

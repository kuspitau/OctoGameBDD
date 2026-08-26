"""P4-T03 disposable full-data validation and guarded canonical promotion.

The normal ``validate`` command copies the validated migration-11 canonical DB,
applies migration 12 on the copy, imports the exact matching Octo DBC reagent
slice twice, and proves idempotence/integrity without mutating the canonical DB.
``promote`` is the D-029 guarded mutation path after the human reviews that proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tomllib
from pathlib import Path
from typing import Any

from octogamedb.db import apply_migrations, connect_database
from octogamedb.importers.octo_dbc_recipe_reagents import (
    compute_octodbc_recipe_reagent_revision,
    import_octodbc_recipe_reagents,
    inspect_octodbc_recipe_reagent_layouts,
)

DEFAULT_CONFIG = Path("config.local.toml")
DEFAULT_CANONICAL_DB = Path("data/generated/octogamedb.sqlite3")
DEFAULT_WORK_DB = Path("data/generated/p4_t03_validation.sqlite3")
DEFAULT_BACKUP_DB = Path("data/generated/octogamedb_bak.sqlite3")
_REQUIRED_DBC = ("Spell.dbc", "SkillLine.dbc", "SkillLineAbility.dbc")


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"{path}: TOML root must be a table")
    return value


def _resolve_dbc_root(explicit: Path | None, config_path: Path) -> Path:
    if explicit is not None:
        root = explicit.expanduser()
    else:
        config = _load_config(config_path)
        source_paths = config.get("source_paths", {})
        if not isinstance(source_paths, dict):
            raise TypeError(f"{config_path}: [source_paths] must be a table")
        value = source_paths.get("octo_dbc")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "[source_paths].octo_dbc is not configured; P4-T03 reuses the "
                "already validated P4-T02 path contract"
            )
        root = Path(value).expanduser()
    missing = [name for name in _REQUIRED_DBC if not (root / name).is_file()]
    if missing:
        raise ValueError(
            f"invalid Octo DBC root {root}: missing required file(s): {', '.join(missing)}"
        )
    return root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _schema_version(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
    )


def _snapshot(connection: sqlite3.Connection) -> list[list[Any]]:
    return [
        list(row)
        for row in connection.execute(
            """
            SELECT recipe_id, reagent_index, native_item_id, item_id, required_quantity
            FROM recipe_reagents
            ORDER BY recipe_id, reagent_index
            """
        ).fetchall()
    ]


def _domain_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "recipe_count": int(connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]),
        "recipe_reagent_count": int(
            connection.execute("SELECT COUNT(*) FROM recipe_reagents").fetchone()[0]
        ),
        "recipes_with_reagents": int(
            connection.execute(
                "SELECT COUNT(DISTINCT recipe_id) FROM recipe_reagents"
            ).fetchone()[0]
        ),
        "unresolved_reagent_count": int(
            connection.execute(
                "SELECT COUNT(*) FROM recipe_reagents WHERE item_id IS NULL"
            ).fetchone()[0]
        ),
        "zero_quantity_reagent_count": int(
            connection.execute(
                "SELECT COUNT(*) FROM recipe_reagents WHERE required_quantity = 0"
            ).fetchone()[0]
        ),
    }


def _sample_reagents(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT
                rr.recipe_id,
                s.name AS recipe_name,
                rr.reagent_index,
                rr.native_item_id,
                i.name AS reagent_name,
                rr.required_quantity
            FROM recipe_reagents AS rr
            JOIN recipes AS r ON r.recipe_id = rr.recipe_id
            JOIN spells AS s ON s.spell_id = r.crafting_spell_id
            LEFT JOIN items AS i ON i.item_id = rr.item_id
            ORDER BY rr.recipe_id, rr.reagent_index
            LIMIT 24
            """
        ).fetchall()
    ]


def validate(*, source_db: Path, work_db: Path, dbc_root: Path) -> dict[str, Any]:
    if not source_db.is_file():
        raise FileNotFoundError(f"canonical baseline not found: {source_db}")
    layouts = inspect_octodbc_recipe_reagent_layouts(dbc_root)
    revision = compute_octodbc_recipe_reagent_revision(dbc_root)
    baseline_sha256 = _sha256(source_db)

    work_db.parent.mkdir(parents=True, exist_ok=True)
    if work_db.exists():
        work_db.unlink()
    shutil.copy2(source_db, work_db)

    with connect_database(work_db) as connection:
        before_version = _schema_version(connection)
        if before_version != 11:
            raise ValueError(
                "P4-T03 expects the validated P4-T02 migration-11 baseline, "
                f"got schema version {before_version}"
            )
        applied = apply_migrations(connection)
        if not applied or applied[-1].version != 12:
            raise ValueError("P4-T03 validation copy did not apply migration 12")

        first = import_octodbc_recipe_reagents(
            connection, source_root=dbc_root, source_revision=revision
        )
        first_snapshot = _snapshot(connection)
        second = import_octodbc_recipe_reagents(
            connection, source_root=dbc_root, source_revision=revision
        )
        if _snapshot(connection) != first_snapshot:
            raise ValueError("second import materially changed canonical P4-T03 content")
        if second.rows_inserted != 0 or second.rows_updated != 0:
            raise ValueError(
                "second P4-T03 import is not canonically idempotent: "
                f"inserted={second.rows_inserted}, updated={second.rows_updated}"
            )

        counts = _domain_counts(connection)
        if counts["recipe_count"] <= 0:
            raise ValueError("migration-11 baseline contains no recipes")
        if counts["recipe_reagent_count"] <= 0:
            raise ValueError("full-data P4-T03 import produced no recipe reagents")
        if counts["unresolved_reagent_count"] != int(
            first.details["unresolved_reagent_count"]
        ):
            raise ValueError("unresolved reagent table/summary counts disagree")
        if counts["zero_quantity_reagent_count"] != int(
            first.details["zero_quantity_reagent_count"]
        ):
            raise ValueError("zero-quantity reagent table/summary counts disagree")

        foreign_key_rows = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if foreign_key_rows or integrity != "ok":
            raise ValueError(
                f"SQLite integrity failure: foreign_key_check={foreign_key_rows}, "
                f"integrity_check={integrity!r}"
            )
        schema_version = _schema_version(connection)
        samples = _sample_reagents(connection)

    if _sha256(source_db) != baseline_sha256:
        raise ValueError("canonical migration-11 baseline changed during disposable validation")

    return {
        "status": "ok",
        "source_db": str(source_db),
        "source_db_sha256": baseline_sha256,
        "work_db": str(work_db),
        "schema_version": schema_version,
        "source_revision": revision,
        "dbc_layouts": [layout.__dict__ for layout in layouts],
        **counts,
        "first_import": first.to_dict(),
        "second_import": second.to_dict(),
        "sample_reagents": samples,
        "foreign_key_check": foreign_key_rows,
        "integrity_check": integrity,
        "canonical_baseline_unchanged": True,
    }


def promote(
    *,
    canonical_db: Path,
    backup_db: Path,
    dbc_root: Path,
    validation_json: Path,
) -> dict[str, Any]:
    if not validation_json.is_file():
        raise FileNotFoundError(f"validation evidence not found: {validation_json}")
    evidence = json.loads(validation_json.read_text(encoding="utf-8"))
    if evidence.get("status") != "ok" or evidence.get("canonical_baseline_unchanged") is not True:
        raise ValueError("validation JSON is not a successful non-destructive P4-T03 proof")
    if not canonical_db.is_file():
        raise FileNotFoundError(f"canonical DB not found: {canonical_db}")

    current_hash = _sha256(canonical_db)
    if current_hash != evidence.get("source_db_sha256"):
        raise ValueError(
            "canonical DB bytes differ from the migration-11 baseline that was validated; "
            "rerun disposable validation before promotion"
        )
    revision = compute_octodbc_recipe_reagent_revision(dbc_root)
    if revision != evidence.get("source_revision"):
        raise ValueError(
            "configured Octo DBC content differs from the validated P4-T03 source revision"
        )
    inspect_octodbc_recipe_reagent_layouts(dbc_root)

    with sqlite3.connect(str(canonical_db)) as check:
        before_version = int(
            check.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
    if before_version != 11:
        raise ValueError(
            f"canonical P4-T03 promotion requires schema version 11, got {before_version}"
        )

    backup_db.parent.mkdir(parents=True, exist_ok=True)
    if backup_db.exists():
        backup_db.unlink()
    shutil.copy2(canonical_db, backup_db)
    backup_hash = _sha256(backup_db)
    if backup_hash != current_hash:
        raise ValueError("D-029 backup is not byte-identical to the canonical pre-mutation DB")

    try:
        with connect_database(canonical_db) as connection:
            applied = apply_migrations(connection)
            if not applied or applied[-1].version != 12:
                raise ValueError("canonical P4-T03 promotion did not apply migration 12")
            first = import_octodbc_recipe_reagents(
                connection, source_root=dbc_root, source_revision=revision
            )
            second = import_octodbc_recipe_reagents(
                connection, source_root=dbc_root, source_revision=revision
            )
            if second.rows_inserted != 0 or second.rows_updated != 0:
                raise ValueError(
                    "canonical second P4-T03 import is not idempotent: "
                    f"inserted={second.rows_inserted}, updated={second.rows_updated}"
                )
            foreign_key_rows = [
                list(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()
            ]
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if foreign_key_rows or integrity != "ok":
                raise ValueError(
                    f"canonical SQLite integrity failure: {foreign_key_rows}, {integrity!r}"
                )
            counts = _domain_counts(connection)
            schema_version = _schema_version(connection)
    except Exception:
        shutil.copy2(backup_db, canonical_db)
        raise

    return {
        "status": "ok",
        "schema_version": schema_version,
        "source_revision": revision,
        **counts,
        "first_import": first.to_dict(),
        "second_import": second.to_dict(),
        "foreign_key_check": foreign_key_rows,
        "integrity_check": integrity,
        "backup_sha256": backup_hash,
        "canonical_sha256": _sha256(canonical_db),
    }


def _write_result(result: dict[str, Any], json_out: Path | None) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(text + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--source-db", type=Path, default=DEFAULT_CANONICAL_DB)
    validate_parser.add_argument("--work-db", type=Path, default=DEFAULT_WORK_DB)
    validate_parser.add_argument("--dbc-root", type=Path)
    validate_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    validate_parser.add_argument("--json-out", type=Path)

    promote_parser = sub.add_parser("promote")
    promote_parser.add_argument("--canonical-db", type=Path, default=DEFAULT_CANONICAL_DB)
    promote_parser.add_argument("--backup-db", type=Path, default=DEFAULT_BACKUP_DB)
    promote_parser.add_argument("--dbc-root", type=Path)
    promote_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    promote_parser.add_argument("--validation-json", type=Path, required=True)
    promote_parser.add_argument("--json-out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dbc_root = _resolve_dbc_root(args.dbc_root, args.config)
        if args.command == "validate":
            result = validate(
                source_db=args.source_db,
                work_db=args.work_db,
                dbc_root=dbc_root,
            )
        else:
            result = promote(
                canonical_db=args.canonical_db,
                backup_db=args.backup_db,
                dbc_root=dbc_root,
                validation_json=args.validation_json,
            )
        _write_result(result, args.json_out)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary must emit a useful failure
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

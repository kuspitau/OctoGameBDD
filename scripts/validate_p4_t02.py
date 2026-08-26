"""P4-T02 local path configuration and disposable full-data validation.

Normal validation never mutates data/generated/octogamedb.sqlite3.  It copies that validated
migration-10 baseline to a dedicated disposable DB, applies migration 11, imports the configured
Octo DBC recipe slice twice, and checks canonical/idempotence/integrity invariants.
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
from octogamedb.importers.octo_dbc_recipes import (
    compute_octodbc_recipe_revision,
    import_octodbc_recipes,
    inspect_octodbc_recipe_layouts,
)

DEFAULT_CONFIG = Path("config.local.toml")
DEFAULT_CANONICAL_DB = Path("data/generated/octogamedb.sqlite3")
DEFAULT_WORK_DB = Path("data/generated/p4_t02_validation.sqlite3")
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


def _valid_dbc_root(path: Path) -> bool:
    return path.is_dir() and all((path / filename).is_file() for filename in _REQUIRED_DBC)


def _configured_dbc_root(config_path: Path) -> Path | None:
    config = _load_config(config_path)
    source_paths = config.get("source_paths", {})
    if not isinstance(source_paths, dict):
        raise TypeError(f"{config_path}: [source_paths] must be a table")
    value = source_paths.get("octo_dbc")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def _resolve_dbc_root(explicit: Path | None, config_path: Path) -> Path:
    root = explicit.expanduser() if explicit is not None else _configured_dbc_root(config_path)
    if root is None:
        raise ValueError(
            "[source_paths].octo_dbc is not configured; run get_path.bat or pass --dbc-root"
        )
    if not _valid_dbc_root(root):
        missing = [name for name in _REQUIRED_DBC if not (root / name).is_file()]
        raise ValueError(
            f"invalid Octo DBC root {root}: missing required file(s): {', '.join(missing)}"
        )
    return root


def _toml_string(value: str) -> str:
    return json.dumps(value.replace("\\", "/"), ensure_ascii=False)


def _set_source_path(config_path: Path, key: str, value: Path) -> None:
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    lines = text.splitlines()
    section_start: int | None = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[source_paths]":
            section_start = index
            continue
        if section_start is not None and stripped.startswith("[") and stripped.endswith("]"):
            section_end = index
            break

    assignment = f"{key} = {_toml_string(str(value.resolve()))}"
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[source_paths]", assignment])
    else:
        found = False
        for index in range(section_start + 1, section_end):
            stripped = lines[index].strip()
            if stripped.startswith((f"{key} ", f"{key}=")):
                lines[index] = assignment
                found = True
                break
        if not found:
            lines.insert(section_end, assignment)
    config_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _candidate_roots(config_path: Path) -> list[Path]:
    candidates = [Path("data/raw/octo_dbc"), Path("data/raw/dbc")]
    config = _load_config(config_path)
    source_paths = config.get("source_paths", {})
    if isinstance(source_paths, dict):
        wow_root = source_paths.get("wow_root")
        if isinstance(wow_root, str) and wow_root.strip():
            root = Path(wow_root).expanduser()
            candidates.extend((root / "dbc", root / "Data" / "dbc", root / "Data" / "DBC"))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def configure_path(config_path: Path) -> int:
    current = _configured_dbc_root(config_path)
    if current is not None and _valid_dbc_root(current):
        print(f"octo_dbc already valid: {current}")
        return 0

    discovered = [
        candidate for candidate in _candidate_roots(config_path) if _valid_dbc_root(candidate)
    ]
    if len(discovered) == 1:
        selected = discovered[0]
        print(f"Discovered Octo DBC root: {selected}")
    else:
        if len(discovered) > 1:
            print("Multiple candidate Octo DBC roots were found:")
            for candidate in discovered:
                print(f"  - {candidate}")
        else:
            print("No valid Octo DBC root was discovered automatically.")
        raw = input(
            "Paste the directory containing Spell.dbc, SkillLine.dbc and "
            "SkillLineAbility.dbc: "
        ).strip().strip('"')
        selected = Path(raw).expanduser()

    if not _valid_dbc_root(selected):
        print(f"ERROR: {selected} is not a valid P4 Octo DBC root.", file=sys.stderr)
        return 2
    _set_source_path(config_path, "octo_dbc", selected)
    print(f"Updated {config_path}: [source_paths].octo_dbc = {selected.resolve()}")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot(connection: sqlite3.Connection) -> dict[str, list[list[Any]]]:
    queries = {
        "spells": "SELECT spell_id, name, rank_text FROM spells ORDER BY spell_id",
        "skill_lines": "SELECT skill_line_id, name FROM skill_lines ORDER BY skill_line_id",
        "recipes": "SELECT recipe_id, crafting_spell_id FROM recipes ORDER BY recipe_id",
        "recipe_skill_lines": """
            SELECT recipe_id, skill_line_ability_id, skill_line_id, required_skill_value
            FROM recipe_skill_lines
            ORDER BY recipe_id, skill_line_ability_id
        """,
        "recipe_outputs": """
            SELECT recipe_id, effect_index, native_item_id, item_id
            FROM recipe_outputs
            ORDER BY recipe_id, effect_index
        """,
    }
    return {
        key: [list(row) for row in connection.execute(sql).fetchall()]
        for key, sql in queries.items()
    }


def validate(
    *,
    source_db: Path,
    work_db: Path,
    dbc_root: Path,
) -> dict[str, Any]:
    if not source_db.is_file():
        raise FileNotFoundError(f"canonical baseline not found: {source_db}")
    layouts = inspect_octodbc_recipe_layouts(dbc_root)
    revision = compute_octodbc_recipe_revision(dbc_root)
    baseline_sha256 = _sha256(source_db)

    work_db.parent.mkdir(parents=True, exist_ok=True)
    if work_db.exists():
        work_db.unlink()
    shutil.copy2(source_db, work_db)

    with connect_database(work_db) as connection:
        before_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        if before_version != 10:
            raise ValueError(
                "P4-T02 expects a validated migration-10 baseline, "
                f"got schema version {before_version}"
            )
        applied = apply_migrations(connection)
        if not applied or applied[-1].version != 11:
            raise ValueError(
                "P4-T02 validation copy did not apply migration 11 as the final pending migration"
            )

        first = import_octodbc_recipes(connection, source_root=dbc_root, source_revision=revision)
        first_snapshot = _snapshot(connection)
        second = import_octodbc_recipes(connection, source_root=dbc_root, source_revision=revision)
        second_snapshot = _snapshot(connection)
        if first_snapshot != second_snapshot:
            raise ValueError("second import materially changed canonical P4 content")
        if second.rows_inserted != 0 or second.rows_updated != 0:
            raise ValueError(
                "second import is not canonically idempotent: "
                f"inserted={second.rows_inserted}, updated={second.rows_updated}"
            )

        foreign_key_rows = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if foreign_key_rows or integrity != "ok":
            raise ValueError(
                f"SQLite integrity failure: foreign_key_check={foreign_key_rows}, "
                f"integrity_check={integrity!r}"
            )

        recipe_count = int(connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0])
        profession_count = int(
            connection.execute(
                "SELECT COUNT(DISTINCT skill_line_id) FROM recipe_skill_lines"
            ).fetchone()[0]
        )
        output_count = int(connection.execute("SELECT COUNT(*) FROM recipe_outputs").fetchone()[0])
        unresolved_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM recipe_outputs WHERE item_id IS NULL"
            ).fetchone()[0]
        )
        if recipe_count <= 0:
            raise ValueError("full-data import produced no canonical recipes")
        if profession_count < 2:
            raise ValueError(
                "full-data proof requires at least two represented skill lines, "
                f"got {profession_count}"
            )
        if output_count <= 0:
            raise ValueError("full-data import produced no recipe outputs")
        if unresolved_count != first.warning_count:
            raise ValueError(
                "unresolved output count disagrees with import summary: "
                f"table={unresolved_count}, summary={first.warning_count}"
            )

        samples = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    r.recipe_id,
                    s.name AS spell_name,
                    sl.skill_line_id,
                    sl.name AS skill_line_name,
                    rsl.required_skill_value,
                    COUNT(ro.effect_index) AS output_count
                FROM recipes AS r
                JOIN spells AS s ON s.spell_id = r.crafting_spell_id
                JOIN recipe_skill_lines AS rsl ON rsl.recipe_id = r.recipe_id
                JOIN skill_lines AS sl ON sl.skill_line_id = rsl.skill_line_id
                LEFT JOIN recipe_outputs AS ro ON ro.recipe_id = r.recipe_id
                GROUP BY
                    r.recipe_id, s.name, sl.skill_line_id, sl.name, rsl.required_skill_value
                ORDER BY r.recipe_id, sl.skill_line_id
                LIMIT 12
                """
            ).fetchall()
        ]
        schema_version = int(
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        )

    if _sha256(source_db) != baseline_sha256:
        raise ValueError("canonical baseline changed during disposable P4-T02 validation")

    return {
        "status": "ok",
        "source_db": str(source_db),
        "source_db_sha256": baseline_sha256,
        "work_db": str(work_db),
        "schema_version": schema_version,
        "source_revision": revision,
        "dbc_layouts": [layout.__dict__ for layout in layouts],
        "recipe_count": recipe_count,
        "represented_skill_line_count": profession_count,
        "output_count": output_count,
        "unresolved_output_count": unresolved_count,
        "orphan_spell_skill_line_ability_count": int(
            first.details.get("orphan_spell_skill_line_ability_count", 0)
        ),
        "orphan_spell_ids": list(first.details.get("orphan_spell_ids", [])),
        "orphan_skill_line_ability_count": int(
            first.details.get("orphan_skill_line_ability_count", 0)
        ),
        "orphan_skill_line_ids": list(first.details.get("orphan_skill_line_ids", [])),
        "first_import": first.to_dict(),
        "second_import": second.to_dict(),
        "sample_recipes": samples,
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
    """Promote a previously validated exact source/baseline under the D-029 backup rule."""

    if not validation_json.is_file():
        raise FileNotFoundError(f"validation evidence not found: {validation_json}")
    evidence = json.loads(validation_json.read_text(encoding="utf-8"))
    if evidence.get("status") != "ok" or evidence.get("canonical_baseline_unchanged") is not True:
        raise ValueError("validation JSON is not a successful non-destructive P4-T02 proof")
    if not canonical_db.is_file():
        raise FileNotFoundError(f"canonical DB not found: {canonical_db}")

    current_hash = _sha256(canonical_db)
    if current_hash != evidence.get("source_db_sha256"):
        raise ValueError(
            "canonical DB bytes differ from the migration-10 baseline that was validated; "
            "rerun disposable validation before promotion"
        )
    revision = compute_octodbc_recipe_revision(dbc_root)
    if revision != evidence.get("source_revision"):
        raise ValueError(
            "configured Octo DBC content differs from the source revision that was validated; "
            "rerun disposable validation before promotion"
        )
    inspect_octodbc_recipe_layouts(dbc_root)

    with sqlite3.connect(str(canonical_db)) as check:
        before_version = int(
            check.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
        )
    if before_version != 10:
        raise ValueError(
            f"canonical promotion requires schema version 10, got {before_version}"
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
            if not applied or applied[-1].version != 11:
                raise ValueError("canonical promotion did not apply migration 11")
            first = import_octodbc_recipes(
                connection,
                source_root=dbc_root,
                source_revision=revision,
            )
            second = import_octodbc_recipes(
                connection,
                source_root=dbc_root,
                source_revision=revision,
            )
            if second.rows_inserted != 0 or second.rows_updated != 0:
                raise ValueError(
                    "canonical second import is not idempotent: "
                    f"inserted={second.rows_inserted}, updated={second.rows_updated}"
                )
            foreign_key_rows = [
                list(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()
            ]
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if foreign_key_rows or integrity != "ok":
                raise ValueError(
                    f"canonical integrity failure: foreign_key_check={foreign_key_rows}, "
                    f"integrity_check={integrity!r}"
                )
            counts = dict(
                connection.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM recipes) AS recipe_count,
                        (SELECT COUNT(DISTINCT skill_line_id) FROM recipe_skill_lines)
                            AS represented_skill_line_count,
                        (SELECT COUNT(*) FROM recipe_outputs) AS output_count,
                        (SELECT COUNT(*) FROM recipe_outputs WHERE item_id IS NULL)
                            AS unresolved_output_count
                    """
                ).fetchone()
            )
            schema_version = int(
                connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            )
    except Exception:
        shutil.copy2(backup_db, canonical_db)
        raise

    return {
        "status": "ok",
        "schema_version": schema_version,
        "source_revision": revision,
        "backup_db": str(backup_db),
        "backup_sha256": backup_hash,
        "canonical_db": str(canonical_db),
        "canonical_sha256": _sha256(canonical_db),
        **counts,
        "orphan_spell_skill_line_ability_count": int(
            first.details.get("orphan_spell_skill_line_ability_count", 0)
        ),
        "orphan_spell_ids": list(first.details.get("orphan_spell_ids", [])),
        "orphan_skill_line_ability_count": int(
            first.details.get("orphan_skill_line_ability_count", 0)
        ),
        "orphan_skill_line_ids": list(first.details.get("orphan_skill_line_ids", [])),
        "first_import": first.to_dict(),
        "second_import": second.to_dict(),
        "foreign_key_check": foreign_key_rows,
        "integrity_check": integrity,
    }

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure-path")
    configure.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    validate_parser.add_argument("--dbc-root", type=Path)
    validate_parser.add_argument("--source-db", type=Path, default=DEFAULT_CANONICAL_DB)
    validate_parser.add_argument("--work-db", type=Path, default=DEFAULT_WORK_DB)
    validate_parser.add_argument("--json-out", type=Path)

    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    promote_parser.add_argument("--dbc-root", type=Path)
    promote_parser.add_argument("--canonical-db", type=Path, default=DEFAULT_CANONICAL_DB)
    promote_parser.add_argument("--backup-db", type=Path, default=DEFAULT_BACKUP_DB)
    promote_parser.add_argument(
        "--validation-json",
        type=Path,
        default=Path("data/generated/p4_t02_validation.json"),
    )
    promote_parser.add_argument("--json-out", type=Path)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "configure-path":
        return configure_path(args.config)
    if args.command in {"validate", "promote"}:
        try:
            dbc_root = _resolve_dbc_root(args.dbc_root, args.config)
            if args.command == "validate":
                payload = validate(
                    source_db=args.source_db,
                    work_db=args.work_db,
                    dbc_root=dbc_root,
                )
            else:
                payload = promote(
                    canonical_db=args.canonical_db,
                    backup_db=args.backup_db,
                    dbc_root=dbc_root,
                    validation_json=args.validation_json,
                )
        # CLI boundary: convert any validator failure into a stable non-zero exit.
        except Exception as exc:  # noqa: BLE001
            print(f"P4-T02 {args.command} FAILED: {exc}", file=sys.stderr)
            return 1
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        print(rendered)
        if args.json_out is not None:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(rendered + "\n", encoding="utf-8")
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

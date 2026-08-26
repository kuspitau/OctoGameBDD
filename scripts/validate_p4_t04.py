"""P4-T04 disposable full-data validation and guarded canonical promotion.

``validate`` copies the validated migration-12 canonical DB, applies migration 13,
imports the configured Tortoise-world + exact matching Octo-DBC acquisition slice
twice, and proves canonical idempotence/integrity without mutating the canonical DB.
``promote`` is the D-029 mutation path after the human reviews that proof.
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
)
from octogamedb.importers.recipe_acquisition_sources import (
    TORTOISE_PINNED_SEMANTIC_REVISION,
    import_recipe_acquisition_sources,
    load_octodbc_learn_effects,
    load_tortoise_acquisition_slice,
)

DEFAULT_CONFIG = Path("config.local.toml")
DEFAULT_CANONICAL_DB = Path("data/generated/octogamedb.sqlite3")
DEFAULT_WORK_DB = Path("data/generated/p4_t04_validation.sqlite3")
DEFAULT_BACKUP_DB = Path("data/generated/octogamedb_bak.sqlite3")
_REQUIRED_DBC = ("Spell.dbc", "SkillLine.dbc", "SkillLineAbility.dbc")
_REQUIRED_TORTOISE = (
    Path("sql/base/tw_world_npc_trainer.sql"),
    Path("sql/base/tw_world_npc_trainer_template.sql"),
    Path("sql/base/tw_world_quest_template.sql"),
    Path("sql/base/tw_world_item_template.sql"),
    Path("sql/base/tw_world_creature_template.sql"),
    Path("sql/base/tw_world_spell_learn_spell.sql"),
    Path("sql/database_updates/world"),
)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"{path}: TOML root must be a table")
    return value


def _resolve_source_paths(
    *, dbc_root: Path | None, tortoise_repo: Path | None, config_path: Path
) -> tuple[Path, Path]:
    config = _load_config(config_path)
    source_paths = config.get("source_paths", {})
    if not isinstance(source_paths, dict):
        raise TypeError(f"{config_path}: [source_paths] must be a table")

    if dbc_root is None:
        value = source_paths.get("octo_dbc")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("[source_paths].octo_dbc is not configured")
        dbc_root = Path(value)
    if tortoise_repo is None:
        value = source_paths.get("tortoise_repo")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("[source_paths].tortoise_repo is not configured")
        tortoise_repo = Path(value)

    dbc_root = dbc_root.expanduser()
    tortoise_repo = tortoise_repo.expanduser()
    missing_dbc = [name for name in _REQUIRED_DBC if not (dbc_root / name).is_file()]
    if missing_dbc:
        raise ValueError(
            f"invalid Octo DBC root {dbc_root}: missing {', '.join(missing_dbc)}"
        )
    missing_tortoise = [str(path) for path in _REQUIRED_TORTOISE if not (tortoise_repo / path).exists()]
    if missing_tortoise:
        raise ValueError(
            f"invalid Tortoise repository {tortoise_repo}: missing {', '.join(missing_tortoise)}"
        )
    return dbc_root, tortoise_repo


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0])


def _snapshot(connection: sqlite3.Connection) -> dict[str, list[list[Any]]]:
    return {
        "teaching_items": [
            list(row)
            for row in connection.execute(
                """
                SELECT recipe_id, native_item_id, item_id, item_spell_slot, spell_trigger,
                       spell_charges, acquisition_spell_id, learning_proof_kind,
                       learn_effect_index, server_learn_active
                FROM recipe_teaching_items
                ORDER BY recipe_id, native_item_id, item_spell_slot, acquisition_spell_id
                """
            ).fetchall()
        ],
        "trainer_sources": [
            list(row)
            for row in connection.execute(
                """
                SELECT recipe_id, trainer_kind, native_trainer_entry, creature_id,
                       trainer_template_id, acquisition_spell_id, learning_proof_kind,
                       learn_effect_index, server_learn_active, spell_cost,
                       required_skill_line_id, required_skill_value, required_character_level
                FROM recipe_trainer_sources
                ORDER BY recipe_id, trainer_kind, native_trainer_entry, acquisition_spell_id
                """
            ).fetchall()
        ],
        "quest_learning_sources": [
            list(row)
            for row in connection.execute(
                """
                SELECT recipe_id, native_quest_id, quest_id, reward_spell_field,
                       acquisition_spell_id, learning_proof_kind, learn_effect_index,
                       server_learn_active
                FROM recipe_quest_learning_sources
                ORDER BY recipe_id, native_quest_id, reward_spell_field, acquisition_spell_id
                """
            ).fetchall()
        ],
    }

def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "recipe_count": int(connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]),
        "teaching_item_count": int(connection.execute("SELECT COUNT(*) FROM recipe_teaching_items").fetchone()[0]),
        "trainer_source_count": int(connection.execute("SELECT COUNT(*) FROM recipe_trainer_sources").fetchone()[0]),
        "direct_trainer_source_count": int(connection.execute("SELECT COUNT(*) FROM recipe_trainer_sources WHERE trainer_kind='direct'").fetchone()[0]),
        "template_trainer_source_count": int(connection.execute("SELECT COUNT(*) FROM recipe_trainer_sources WHERE trainer_kind='template'").fetchone()[0]),
        "quest_learning_source_count": int(connection.execute("SELECT COUNT(*) FROM recipe_quest_learning_sources").fetchone()[0]),
        "unresolved_teaching_item_count": int(connection.execute("SELECT COUNT(*) FROM recipe_teaching_items WHERE item_id IS NULL").fetchone()[0]),
        "unresolved_trainer_count": int(connection.execute("SELECT COUNT(*) FROM recipe_trainer_sources WHERE creature_id IS NULL").fetchone()[0]),
        "unresolved_quest_learning_count": int(connection.execute("SELECT COUNT(*) FROM recipe_quest_learning_sources WHERE quest_id IS NULL").fetchone()[0]),
        "dbc_proven_acquisition_count": int(connection.execute(
            "SELECT (SELECT COUNT(*) FROM recipe_teaching_items WHERE learning_proof_kind='octo_dbc_learn_spell') + "
            "(SELECT COUNT(*) FROM recipe_trainer_sources WHERE learning_proof_kind='octo_dbc_learn_spell') + "
            "(SELECT COUNT(*) FROM recipe_quest_learning_sources WHERE learning_proof_kind='octo_dbc_learn_spell')"
        ).fetchone()[0]),
        "server_fallback_acquisition_count": int(connection.execute(
            "SELECT (SELECT COUNT(*) FROM recipe_teaching_items WHERE learning_proof_kind='tortoise_spell_learn_spell') + "
            "(SELECT COUNT(*) FROM recipe_trainer_sources WHERE learning_proof_kind='tortoise_spell_learn_spell') + "
            "(SELECT COUNT(*) FROM recipe_quest_learning_sources WHERE learning_proof_kind='tortoise_spell_learn_spell')"
        ).fetchone()[0]),
    }

def _samples(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    return {
        "trainers": [
            dict(row)
            for row in connection.execute(
                """
                SELECT rts.recipe_id, s.name AS recipe_name, rts.trainer_kind,
                       rts.native_trainer_entry, c.name AS creature_name,
                       rts.trainer_template_id, rts.acquisition_spell_id,
                       rts.learning_proof_kind, rts.learn_effect_index, rts.spell_cost,
                       rts.required_skill_line_id, rts.required_skill_value,
                       rts.required_character_level
                FROM recipe_trainer_sources AS rts
                JOIN spells AS s ON s.spell_id = rts.recipe_id
                LEFT JOIN creatures AS c ON c.creature_id = rts.creature_id
                ORDER BY rts.recipe_id, rts.trainer_kind, rts.native_trainer_entry
                LIMIT 24
                """
            ).fetchall()
        ],
        "teaching_items": [
            dict(row)
            for row in connection.execute(
                """
                SELECT rti.recipe_id, s.name AS recipe_name, rti.native_item_id,
                       i.name AS item_name, rti.item_spell_slot, rti.acquisition_spell_id,
                       rti.learning_proof_kind, rti.learn_effect_index
                FROM recipe_teaching_items AS rti
                JOIN spells AS s ON s.spell_id = rti.recipe_id
                LEFT JOIN items AS i ON i.item_id = rti.item_id
                ORDER BY rti.recipe_id, rti.native_item_id, rti.item_spell_slot
                LIMIT 24
                """
            ).fetchall()
        ],
        "quests": [
            dict(row)
            for row in connection.execute(
                """
                SELECT rql.recipe_id, s.name AS recipe_name, rql.native_quest_id,
                       q.name AS quest_name, rql.reward_spell_field,
                       rql.acquisition_spell_id, rql.learning_proof_kind,
                       rql.learn_effect_index
                FROM recipe_quest_learning_sources AS rql
                JOIN spells AS s ON s.spell_id = rql.recipe_id
                LEFT JOIN quests AS q ON q.quest_id = rql.quest_id
                ORDER BY rql.recipe_id, rql.native_quest_id
                LIMIT 24
                """
            ).fetchall()
        ],
    }


def validate(
    *, source_db: Path, work_db: Path, dbc_root: Path, tortoise_repo: Path
) -> dict[str, Any]:
    if not source_db.is_file():
        raise FileNotFoundError(f"canonical baseline not found: {source_db}")
    baseline_sha256 = _sha256(source_db)

    # Parse/contract checks happen before touching even the disposable DB copy.
    tortoise_slice = load_tortoise_acquisition_slice(tortoise_repo)
    if tortoise_slice.git_revision != TORTOISE_PINNED_SEMANTIC_REVISION:
        raise ValueError(
            "P4-T04 Level-2 validation requires the pinned Tortoise revision "
            f"{TORTOISE_PINNED_SEMANTIC_REVISION}, got {tortoise_slice.git_revision!r}"
        )
    learn_effects = load_octodbc_learn_effects(dbc_root)
    dbc_revision = compute_octodbc_recipe_reagent_revision(dbc_root)
    if not tortoise_slice.trainer_offers:
        raise ValueError("configured Tortoise source produced no trainer offers")
    if not learn_effects:
        raise ValueError("configured Octo Spell.dbc produced no LEARN_SPELL effects")

    work_db.parent.mkdir(parents=True, exist_ok=True)
    if work_db.exists():
        work_db.unlink()
    shutil.copy2(source_db, work_db)

    with connect_database(work_db) as connection:
        before_version = _schema_version(connection)
        if before_version != 12:
            raise ValueError(
                "P4-T04 expects the validated P4-T03 migration-12 baseline, "
                f"got schema version {before_version}"
            )
        applied = apply_migrations(connection)
        if not applied or applied[-1].version != 13:
            raise ValueError("P4-T04 validation copy did not apply migration 13")

        first = import_recipe_acquisition_sources(
            connection, tortoise_repo=tortoise_repo, dbc_root=dbc_root
        )
        first_snapshot = _snapshot(connection)
        second = import_recipe_acquisition_sources(
            connection, tortoise_repo=tortoise_repo, dbc_root=dbc_root
        )
        if _snapshot(connection) != first_snapshot:
            raise ValueError("second P4-T04 import materially changed canonical acquisition content")
        if second.rows_inserted != 0 or second.rows_updated != 0:
            raise ValueError(
                "second P4-T04 import is not canonically idempotent: "
                f"inserted={second.rows_inserted}, updated={second.rows_updated}"
            )

        counts = _counts(connection)
        if counts["recipe_count"] <= 0:
            raise ValueError("migration-12 baseline contains no recipes")
        total = (
            counts["teaching_item_count"]
            + counts["trainer_source_count"]
            + counts["quest_learning_source_count"]
        )
        if total <= 0:
            raise ValueError("full-data P4-T04 import produced no proven acquisition relations")
        if counts["trainer_source_count"] <= 0:
            raise ValueError("full-data P4-T04 import produced no proven trainer sources")

        foreign_key_rows = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if foreign_key_rows or integrity != "ok":
            raise ValueError(
                f"SQLite integrity failure: foreign_key_check={foreign_key_rows}, integrity_check={integrity!r}"
            )
        schema_version = _schema_version(connection)
        samples = _samples(connection)

    if _sha256(source_db) != baseline_sha256:
        raise ValueError("canonical migration-12 baseline changed during disposable validation")

    return {
        "status": "ok",
        "source_db": str(source_db),
        "source_db_sha256": baseline_sha256,
        "work_db": str(work_db),
        "schema_version": schema_version,
        "tortoise_source_revision": tortoise_slice.source_revision,
        "tortoise_git_revision": tortoise_slice.git_revision,
        "tortoise_trainer_offer_count": len(tortoise_slice.trainer_offers),
        "tortoise_item_spell_slot_count": len(tortoise_slice.item_spell_slots),
        "tortoise_quest_reward_spell_count": len(tortoise_slice.quest_reward_spells),
        "tortoise_server_spell_learn_link_count": len(tortoise_slice.server_learn_links),
        "tortoise_unmapped_trainer_template_count": len(tortoise_slice.unmapped_trainer_template_ids),
        "octo_dbc_revision": dbc_revision,
        "octo_learn_effect_count": len(learn_effects),
        **counts,
        "first_import": first.to_dict(),
        "second_import": second.to_dict(),
        "samples": samples,
        "foreign_key_check": foreign_key_rows,
        "integrity_check": integrity,
        "canonical_baseline_unchanged": True,
    }


def promote(
    *, canonical_db: Path, backup_db: Path, dbc_root: Path, tortoise_repo: Path,
    validation_json: Path
) -> dict[str, Any]:
    if not validation_json.is_file():
        raise FileNotFoundError(f"validation evidence not found: {validation_json}")
    evidence = json.loads(validation_json.read_text(encoding="utf-8"))
    if evidence.get("status") != "ok" or evidence.get("canonical_baseline_unchanged") is not True:
        raise ValueError("validation JSON is not a successful non-destructive P4-T04 proof")
    if not canonical_db.is_file():
        raise FileNotFoundError(f"canonical DB not found: {canonical_db}")

    current_hash = _sha256(canonical_db)
    if current_hash != evidence.get("source_db_sha256"):
        raise ValueError(
            "canonical DB bytes differ from the migration-12 baseline that was validated; "
            "rerun disposable validation before promotion"
        )

    # Re-parse both source families so promotion cannot silently use changed inputs.
    source_check = load_tortoise_acquisition_slice(tortoise_repo)
    if source_check.git_revision != TORTOISE_PINNED_SEMANTIC_REVISION:
        raise ValueError(
            "P4-T04 promotion requires the pinned Tortoise revision "
            f"{TORTOISE_PINNED_SEMANTIC_REVISION}, got {source_check.git_revision!r}"
        )
    load_octodbc_learn_effects(dbc_root)
    dbc_revision = compute_octodbc_recipe_reagent_revision(dbc_root)
    if source_check.source_revision != evidence.get("tortoise_source_revision"):
        raise ValueError("configured Tortoise source differs from the validated P4-T04 source")
    if dbc_revision != evidence.get("octo_dbc_revision"):
        raise ValueError("configured Octo DBC source differs from the validated P4-T04 source")

    with sqlite3.connect(str(canonical_db)) as check:
        before_version = int(check.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0])
    if before_version != 12:
        raise ValueError(f"canonical P4-T04 promotion requires schema version 12, got {before_version}")

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
            if not applied or applied[-1].version != 13:
                raise ValueError("canonical P4-T04 promotion did not apply migration 13")
            first = import_recipe_acquisition_sources(
                connection, tortoise_repo=tortoise_repo, dbc_root=dbc_root
            )
            second = import_recipe_acquisition_sources(
                connection, tortoise_repo=tortoise_repo, dbc_root=dbc_root
            )
            if second.rows_inserted != 0 or second.rows_updated != 0:
                raise ValueError(
                    "canonical second P4-T04 import is not idempotent: "
                    f"inserted={second.rows_inserted}, updated={second.rows_updated}"
                )
            foreign_key_rows = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if foreign_key_rows or integrity != "ok":
                raise ValueError(
                    f"canonical SQLite integrity failure: {foreign_key_rows}, {integrity!r}"
                )
            counts = _counts(connection)
            schema_version = _schema_version(connection)
    except Exception:
        shutil.copy2(backup_db, canonical_db)
        raise

    return {
        "status": "ok",
        "schema_version": schema_version,
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
    validate_parser.add_argument("--tortoise-repo", type=Path)
    validate_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    validate_parser.add_argument("--json-out", type=Path)

    promote_parser = sub.add_parser("promote")
    promote_parser.add_argument("--canonical-db", type=Path, default=DEFAULT_CANONICAL_DB)
    promote_parser.add_argument("--backup-db", type=Path, default=DEFAULT_BACKUP_DB)
    promote_parser.add_argument("--dbc-root", type=Path)
    promote_parser.add_argument("--tortoise-repo", type=Path)
    promote_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    promote_parser.add_argument("--validation-json", type=Path, required=True)
    promote_parser.add_argument("--json-out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dbc_root, tortoise_repo = _resolve_source_paths(
            dbc_root=args.dbc_root,
            tortoise_repo=args.tortoise_repo,
            config_path=args.config,
        )
        if args.command == "validate":
            result = validate(
                source_db=args.source_db,
                work_db=args.work_db,
                dbc_root=dbc_root,
                tortoise_repo=tortoise_repo,
            )
        else:
            result = promote(
                canonical_db=args.canonical_db,
                backup_db=args.backup_db,
                dbc_root=dbc_root,
                tortoise_repo=tortoise_repo,
                validation_json=args.validation_json,
            )
        _write_result(result, args.json_out)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary must emit actionable failure
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

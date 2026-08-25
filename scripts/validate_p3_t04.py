"""Level-2 validator for P3-T04 against a local OctoGameDB SQLite copy.

Run from the repository root against a disposable copy of the canonical P3-T03 database. Source
roots default to config.local.toml. The script applies migration 9, reconciles P3-T04 twice, checks
canonical idempotence/integrity, and prints objective counts, diagnostics, provenance and geography
representatives as JSON.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tomllib
from pathlib import Path
from typing import Any

from octogamedb.db import apply_migrations, connect_database
from octogamedb.importers.pfquest_quest_objectives import (
    OBJECTIVE_FACTS,
    compute_pfquest_quest_objectives_revision,
    compute_pfquest_turtle_quest_objectives_revision,
    reconcile_pfquest_turtle_quest_objectives,
)
from octogamedb.quest_objectives import quest_objectives_by_id


def _configured_source_paths(config_path: Path) -> tuple[Path, Path]:
    if not config_path.is_file():
        raise SystemExit(f"missing local config: {config_path}")
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    source_paths = data.get("source_paths")
    if not isinstance(source_paths, dict):
        raise SystemExit(f"{config_path} has no [source_paths] table")
    try:
        return Path(str(source_paths["pfquest"])), Path(str(source_paths["pfquest_turtle"]))
    except KeyError as exc:
        raise SystemExit(f"missing [source_paths].{exc.args[0]} in {config_path}") from exc


def _condensed_summary(summary) -> dict[str, Any]:
    details = summary.details
    unresolved = details["unresolved_objective_materialization"]
    by_subtype: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for row in unresolved:
        subtype = str(row.get("subtype", row.get("target_kind", "auxiliary")))
        reason = str(row.get("reason", "unknown"))
        by_subtype[subtype] = by_subtype.get(subtype, 0) + 1
        by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "status": summary.status,
        "source_revision": summary.source_revision,
        "rows_read": summary.rows_read,
        "rows_accepted": summary.rows_accepted,
        "rows_skipped": summary.rows_skipped,
        "rows_inserted": summary.rows_inserted,
        "rows_updated": summary.rows_updated,
        "canonical_objective_rows_deleted": details["canonical_objective_rows_deleted"],
        "warning_count": summary.warning_count,
        "error_count": summary.error_count,
        "base_objective_revision": details["base_objective_revision"],
        "turtle_objective_revision": details["turtle_objective_revision"],
        "changed_effective_objective_quest_count": len(
            details["changed_effective_objective_quest_ids"]
        ),
        "changed_effective_itemreq_count": len(details["changed_effective_itemreq_ids"]),
        "changed_effective_area_trigger_count": len(
            details["changed_effective_area_trigger_ids"]
        ),
        "duplicate_source_objective_member_count": len(
            details["duplicate_source_objective_members"]
        ),
        "unresolved_objective_materialization_count": len(unresolved),
        "unresolved_by_subtype": dict(sorted(by_subtype.items())),
        "unresolved_by_reason": dict(sorted(by_reason.items())),
        "unresolved_sample": unresolved[:20],
        "duplicate_sample": details["duplicate_source_objective_members"][:20],
        "objective_counts_by_subtype": details["objective_counts_by_subtype"],
        "area_trigger_count": details["area_trigger_count"],
        "area_trigger_location_count": details["area_trigger_location_count"],
        "item_use_creature_target_count": details["item_use_creature_target_count"],
        "item_use_gameobject_target_count": details["item_use_gameobject_target_count"],
        "protected_canonical_rows_retained": details["protected_canonical_rows_retained"],
    }


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "quests",
        "quest_objective_sets",
        "quest_creature_objectives",
        "quest_gameobject_objectives",
        "quest_item_objectives",
        "quest_item_use_objectives",
        "quest_area_trigger_objectives",
        "quest_zone_objectives",
        "area_triggers",
        "area_trigger_locations",
        "item_use_target_sets",
        "item_use_creature_targets",
        "item_use_gameobject_targets",
        "observation_groups",
        "source_observations",
        "canonical_selections",
        "import_batches",
    )
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def _first_quest_for_table(connection: sqlite3.Connection, table: str) -> int | None:
    row = connection.execute(f"SELECT quest_id FROM {table} ORDER BY quest_id LIMIT 1").fetchone()
    return None if row is None else int(row[0])


def _representatives(connection: sqlite3.Connection) -> dict[str, Any]:
    required_tables = {
        "creature": OBJECTIVE_FACTS["U"][2],
        "gameobject": OBJECTIVE_FACTS["O"][2],
        "item": OBJECTIVE_FACTS["I"][2],
    }
    representatives: dict[str, Any] = {}
    for label, table in required_tables.items():
        quest_id = _first_quest_for_table(connection, table)
        if quest_id is None:
            raise AssertionError(f"expected at least one real {label} objective")
        view = quest_objectives_by_id(connection, quest_id)
        if view is None or view["provenance"] is None:
            raise AssertionError(f"{label} objective representative lacks selected provenance")
        rows = [
            row
            for row in view["objectives"]
            if row["source_subtype"] == {"creature": "U", "gameobject": "O", "item": "I"}[label]
        ]
        if not rows:
            raise AssertionError(f"{label} representative query lost its objective member")
        representatives[label] = {
            "quest_id": quest_id,
            "objective_set_provenance": view["provenance"],
            "objective": rows[0],
        }

    for subtype, label in (("IR", "item_use"), ("A", "area_trigger"), ("Z", "zone")):
        quest_id = _first_quest_for_table(connection, OBJECTIVE_FACTS[subtype][2])
        if quest_id is None:
            representatives[label] = None
            continue
        view = quest_objectives_by_id(connection, quest_id)
        if view is None:
            raise AssertionError(f"{label} objective representative disappeared")
        rows = [row for row in view["objectives"] if row["source_subtype"] == subtype]
        representatives[label] = {
            "quest_id": quest_id,
            "objective_set_provenance": view["provenance"],
            "objective": None if not rows else rows[0],
        }

    geography_candidates = [
        representatives["creature"]["objective"],
        representatives["gameobject"]["objective"],
        representatives.get("area_trigger", {}).get("objective")
        if representatives.get("area_trigger")
        else None,
        representatives.get("zone", {}).get("objective")
        if representatives.get("zone")
        else None,
    ]
    if not any(
        row is not None and row.get("geography_resolved") is True for row in geography_candidates
    ):
        raise AssertionError("no representative objective exposes resolved geography")
    return representatives


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.local.toml"))
    parser.add_argument("--pfquest", type=Path)
    parser.add_argument("--pfquest-turtle", type=Path)
    args = parser.parse_args()

    configured_pfquest, configured_turtle = _configured_source_paths(args.config)
    pfquest = args.pfquest or configured_pfquest
    turtle = args.pfquest_turtle or configured_turtle
    if not args.db.is_file():
        raise SystemExit(f"database does not exist: {args.db}")
    if not pfquest.is_dir():
        raise SystemExit(f"pfQuest source root does not exist: {pfquest}")
    if not turtle.is_dir():
        raise SystemExit(f"pfQuest-turtle source root does not exist: {turtle}")

    base_revision = compute_pfquest_quest_objectives_revision(pfquest)
    turtle_revision = compute_pfquest_turtle_quest_objectives_revision(turtle)

    with connect_database(args.db) as connection:
        applied = apply_migrations(connection)
        first = reconcile_pfquest_turtle_quest_objectives(
            connection,
            pfquest_root=pfquest,
            pfquest_turtle_root=turtle,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )
        second = reconcile_pfquest_turtle_quest_objectives(
            connection,
            pfquest_root=pfquest,
            pfquest_turtle_root=turtle,
            pfquest_revision=base_revision,
            turtle_revision=turtle_revision,
        )

        if first.status != "succeeded" or first.error_count != 0:
            raise AssertionError("first P3-T04 reconciliation did not succeed cleanly")
        if (
            second.rows_inserted != 0
            or second.rows_updated != 0
            or second.details["canonical_objective_rows_deleted"] != 0
        ):
            raise AssertionError("same-revision second P3-T04 pass is not canonically idempotent")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise AssertionError(f"foreign_key_check failed: {foreign_keys[:10]}")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise AssertionError(f"integrity_check failed: {integrity}")
        last_migration = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if tuple(last_migration) != (9, "0009_quest_objectives.sql"):
            raise AssertionError(f"unexpected latest migration: {tuple(last_migration)}")

        payload = {
            "validation": "P3-T04",
            "database": str(args.db),
            "source_paths": {"pfquest": str(pfquest), "pfquest_turtle": str(turtle)},
            "applied_migrations_this_run": [
                [migration.version, migration.name] for migration in applied
            ],
            "expected_revisions": {
                "pfquest_objectives": base_revision,
                "pfquest_turtle_objectives": turtle_revision,
            },
            "first_pass": _condensed_summary(first),
            "second_pass": _condensed_summary(second),
            "foreign_key_check": "ok",
            "integrity_check": integrity,
            "counts": _counts(connection),
            "representatives": _representatives(connection),
        }

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

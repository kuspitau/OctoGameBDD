"""Level-2 validator for P3-T03 against a local OctoGameDB SQLite copy.

Run from the repository root after creating a dedicated validation copy (preferred) or the required
canonical `_bak` before mutating the canonical database.  Source roots default to config.local.toml.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tomllib
from pathlib import Path
from typing import Any

from octogamedb.db import apply_migrations, connect_database
from octogamedb.importers.pfquest_quest_progression import (
    compute_pfquest_quest_progression_revision,
    compute_pfquest_turtle_quest_progression_revision,
    reconcile_pfquest_turtle_quest_progression,
)
from octogamedb.quests import quest_by_id


def _configured_source_paths(config_path: Path) -> tuple[Path, Path]:
    if not config_path.is_file():
        raise SystemExit(f"missing local config: {config_path}")
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    source_paths = data.get("source_paths")
    if not isinstance(source_paths, dict):
        raise SystemExit(f"{config_path} has no [source_paths] table")
    try:
        pfquest = Path(str(source_paths["pfquest"]))
        turtle = Path(str(source_paths["pfquest_turtle"]))
    except KeyError as exc:
        raise SystemExit(f"missing [source_paths].{exc.args[0]} in {config_path}") from exc
    return pfquest, turtle


def _condensed_summary(summary) -> dict[str, Any]:
    details = summary.details
    return {
        "status": summary.status,
        "source_revision": summary.source_revision,
        "rows_read": summary.rows_read,
        "rows_accepted": summary.rows_accepted,
        "rows_skipped": summary.rows_skipped,
        "rows_inserted": summary.rows_inserted,
        "rows_updated": summary.rows_updated,
        "canonical_progression_rows_deleted": details[
            "canonical_progression_rows_deleted"
        ],
        "warning_count": summary.warning_count,
        "error_count": summary.error_count,
        "base_progression_revision": details["base_progression_revision"],
        "turtle_progression_revision": details["turtle_progression_revision"],
        "changed_effective_progression_count": len(
            details["changed_effective_progression_ids"]
        ),
        "unresolved_progression_relation_count": len(
            details["unresolved_progression_relations"]
        ),
        "duplicate_source_member_count": len(details["duplicate_source_members"]),
        "self_prerequisite_count": len(details["self_prerequisite_ids"]),
        "prerequisite_cycle_count": len(details["prerequisite_cycles"]),
        "close_self_member_count": len(details["close_self_member_ids"]),
        "close_self_missing_count": len(details["close_self_missing_ids"]),
        "close_group_mismatch_count": len(details["close_group_mismatch_pairs"]),
        "protected_canonical_rows_retained": details["protected_canonical_rows_retained"],
        "unresolved_sample": details["unresolved_progression_relations"][:10],
        "cycle_sample": details["prerequisite_cycles"][:10],
        "close_mismatch_sample": details["close_group_mismatch_pairs"][:10],
    }


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "quests",
        "quest_prerequisite_sets",
        "quest_prerequisite_set_members",
        "quest_close_sets",
        "quest_close_set_members",
        "observation_groups",
        "source_observations",
        "canonical_selections",
        "import_batches",
    )
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def _representatives(connection: sqlite3.Connection) -> dict[str, Any]:
    restricted = connection.execute(
        """
        SELECT quest_id FROM quests
        WHERE race_mask IS NOT NULL OR class_mask IS NOT NULL
        ORDER BY quest_id LIMIT 1
        """
    ).fetchone()
    if restricted is None:
        raise AssertionError("expected at least one real race/class restricted quest")

    close_group = connection.execute(
        """
        SELECT quest_id FROM quest_close_sets
        WHERE selected_member_count >= 2
        ORDER BY quest_id LIMIT 1
        """
    ).fetchone()
    if close_group is None:
        raise AssertionError("expected at least one real multi-member close set")

    chain = connection.execute(
        """
        SELECT a.quest_id AS first_id,
               a.member_quest_id AS second_id,
               b.member_quest_id AS third_id
        FROM quest_prerequisite_set_members AS a
        JOIN quest_prerequisite_set_members AS b ON b.quest_id = a.member_quest_id
        WHERE a.quest_id <> a.member_quest_id
          AND a.member_quest_id <> b.member_quest_id
          AND a.quest_id <> b.member_quest_id
        ORDER BY a.quest_id, a.member_quest_id, b.member_quest_id
        LIMIT 1
        """
    ).fetchone()
    if chain is None:
        raise AssertionError("expected at least one real multi-step prerequisite chain")

    restricted_view = quest_by_id(connection, int(restricted[0]))
    close_view = quest_by_id(connection, int(close_group[0]))
    chain_ids = [int(chain[0]), int(chain[1]), int(chain[2])]
    chain_views = [quest_by_id(connection, quest_id) for quest_id in chain_ids]
    if restricted_view is None or close_view is None or any(view is None for view in chain_views):
        raise AssertionError("representative quest identity unexpectedly missing")

    scalar_provenance = restricted_view["progression"]["provenance"]
    if (
        scalar_provenance["race_mask"] is None
        and scalar_provenance["class_mask"] is None
    ):
        raise AssertionError("restricted quest lacks selected race/class provenance")
    if close_view["progression"]["provenance"]["close_set"] is None:
        raise AssertionError("close representative lacks selected close-set provenance")

    return {
        "restricted_quest": {
            "quest_id": restricted_view["quest_id"],
            "name": restricted_view["name"],
            "race_mask": restricted_view["progression"]["race_mask"],
            "class_mask": restricted_view["progression"]["class_mask"],
            "race_provenance": scalar_provenance["race_mask"],
            "class_provenance": scalar_provenance["class_mask"],
        },
        "close_set": {
            "quest_id": close_view["quest_id"],
            "name": close_view["name"],
            "close_set": close_view["progression"]["close_set"],
            "provenance": close_view["progression"]["provenance"]["close_set"],
        },
        "prerequisite_chain": [
            {
                "quest_id": view["quest_id"],
                "name": view["name"],
                "prerequisite_set": view["progression"]["prerequisite_set"],
                "prerequisite_provenance": view["progression"]["provenance"][
                    "prerequisite_set"
                ],
            }
            for view in chain_views
        ],
    }


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

    expected_base_revision = compute_pfquest_quest_progression_revision(pfquest)
    expected_turtle_revision = compute_pfquest_turtle_quest_progression_revision(turtle)

    with connect_database(args.db) as connection:
        applied = apply_migrations(connection)
        first = reconcile_pfquest_turtle_quest_progression(
            connection,
            pfquest_root=pfquest,
            pfquest_turtle_root=turtle,
            pfquest_revision=expected_base_revision,
            turtle_revision=expected_turtle_revision,
        )
        second = reconcile_pfquest_turtle_quest_progression(
            connection,
            pfquest_root=pfquest,
            pfquest_turtle_root=turtle,
            pfquest_revision=expected_base_revision,
            turtle_revision=expected_turtle_revision,
        )

        if first.status != "succeeded" or first.error_count != 0:
            raise AssertionError("first P3-T03 reconciliation did not succeed cleanly")
        if (
            second.rows_inserted != 0
            or second.rows_updated != 0
            or second.details["canonical_progression_rows_deleted"] != 0
        ):
            raise AssertionError("same-revision second pass is not canonically idempotent")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise AssertionError(f"foreign_key_check failed: {foreign_keys[:10]}")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise AssertionError(f"integrity_check failed: {integrity}")
        last_migration = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if tuple(last_migration) != (8, "0008_quest_progression.sql"):
            raise AssertionError(f"unexpected latest migration: {tuple(last_migration)}")

        payload = {
            "validation": "P3-T03",
            "database": str(args.db),
            "source_paths": {"pfquest": str(pfquest), "pfquest_turtle": str(turtle)},
            "applied_migrations_this_run": [
                [migration.version, migration.name] for migration in applied
            ],
            "expected_revisions": {
                "pfquest": expected_base_revision,
                "pfquest_turtle": expected_turtle_revision,
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

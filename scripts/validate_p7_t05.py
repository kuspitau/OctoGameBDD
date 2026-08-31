"""Read-only Level-2 validator for P7-T05 against the accepted canonical DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from octogamedb.world_entity_search import (
    MATCH_KNOWN,
    query_world_entities,
    world_entity_query_page_to_dict,
)

EXPECTED_CANONICAL_SHA256 = "60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23"
EXPECTED_SCHEMA_VERSION = 14


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"canonical database not found: {path}")
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _one(connection: sqlite3.Connection, sql: str) -> sqlite3.Row:
    row = connection.execute(sql).fetchone()
    if row is None:
        raise RuntimeError(
            "accepted canonical DB has no representative row for required P7-T05 gate"
        )
    return row


def _detail(connection: sqlite3.Connection, entity_kind: str, entity_id: int) -> dict[str, Any]:
    page = query_world_entities(
        connection,
        entity_kind=entity_kind,
        entity_id=entity_id,
        limit=10,
    )
    matches = [
        result
        for result in page.results
        if result.entity["entity_kind"] == entity_kind
        and result.entity["entity_id"] == entity_id
    ]
    if len(matches) != 1 or matches[0].match_state != MATCH_KNOWN:
        raise RuntimeError(f"{entity_kind} {entity_id} did not round-trip as one known_match")
    return matches[0].entity


def _path_exists(entity: dict[str, Any], *, item_id: int, path_kind: str) -> bool:
    return any(
        item["item_id"] == item_id
        and any(path["path_kind"] == path_kind for path in item["acquisition_paths"])
        for item in entity["roles"]["item_acquisition"]
    )


def _role_exists(entity: dict[str, Any], *, quest_id: int, role: str) -> bool:
    return any(
        row["quest_id"] == quest_id and row["role"] == role
        for row in entity["roles"]["quests"]
    )


def _first_unlocated_detail(connection: sqlite3.Connection) -> dict[str, Any] | None:
    rows = connection.execute(
        """
        SELECT 'creature' AS entity_kind, c.creature_id AS entity_id
        FROM creatures AS c
        WHERE NOT EXISTS (
            SELECT 1 FROM creature_spawns AS s WHERE s.creature_id = c.creature_id
        )
        UNION ALL
        SELECT 'gameobject' AS entity_kind, g.gameobject_id AS entity_id
        FROM gameobjects AS g
        WHERE NOT EXISTS (
            SELECT 1 FROM gameobject_spawns AS s WHERE s.gameobject_id = g.gameobject_id
        )
        ORDER BY entity_kind, entity_id
        LIMIT 100
        """
    ).fetchall()
    for row in rows:
        entity = _detail(connection, str(row["entity_kind"]), int(row["entity_id"]))
        if not entity["spawns"]:
            return entity
    return None


def _first_duplicate_spawn_set_detail(connection: sqlite3.Connection) -> dict[str, Any] | None:
    rows = connection.execute(
        """
        SELECT og.subject_kind AS entity_kind, CAST(og.subject_key AS INTEGER) AS entity_id,
               so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        WHERE og.fact_key = 'spawn_set' AND og.fact_instance_key = ''
          AND og.subject_kind IN ('creature', 'gameobject')
        ORDER BY og.subject_kind, CAST(og.subject_key AS INTEGER)
        """
    ).fetchall()
    for row in rows:
        value = json.loads(str(row["value_json"]))
        if not isinstance(value, list):
            continue
        keys = [
            member.get("spawn_key")
            for member in value
            if isinstance(member, dict) and isinstance(member.get("spawn_key"), str)
        ]
        if len(keys) == len(value) and len(set(keys)) < len(keys):
            entity = _detail(
                connection,
                str(row["entity_kind"]),
                int(row["entity_id"]),
            )
            coverage = entity["spawn_set"]
            expected_duplicates = len(keys) - len(set(keys))
            if coverage["duplicate_source_member_count"] != expected_duplicates:
                raise RuntimeError(
                    "duplicate selected spawn_set membership was not reported deterministically"
                )
            if coverage["selected_distinct_member_count"] != len(set(keys)):
                raise RuntimeError(
                    "duplicate selected spawn_set membership distorted distinct identity count"
                )
            return entity
    return None


def _first_complete_spawn_set_detail(connection: sqlite3.Connection) -> dict[str, Any] | None:
    rows = connection.execute(
        """
        SELECT og.subject_kind AS entity_kind, CAST(og.subject_key AS INTEGER) AS entity_id
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        WHERE og.fact_key = 'spawn_set' AND og.fact_instance_key = ''
          AND og.subject_kind IN ('creature', 'gameobject')
        ORDER BY og.subject_kind, CAST(og.subject_key AS INTEGER)
        LIMIT 200
        """
    ).fetchall()
    for row in rows:
        entity = _detail(connection, str(row["entity_kind"]), int(row["entity_id"]))
        if entity["spawn_set"]["is_complete_for_canonical_view"]:
            return entity
    return None


def validate(
    db_path: Path, *, expected_sha256: str = EXPECTED_CANONICAL_SHA256
) -> dict[str, object]:
    before_sha = _sha256(db_path)
    if before_sha != expected_sha256:
        raise RuntimeError(
            f"unexpected canonical SHA-256: expected {expected_sha256}, observed {before_sha}"
        )

    connection = _open_readonly(db_path)
    try:
        schema_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        if schema_version != EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                "unexpected schema version: "
                f"expected {EXPECTED_SCHEMA_VERSION}, observed {schema_version}"
            )

        creature_count = int(connection.execute("SELECT COUNT(*) FROM creatures").fetchone()[0])
        gameobject_count = int(connection.execute("SELECT COUNT(*) FROM gameobjects").fetchone()[0])
        if creature_count <= 0 or gameobject_count <= 0:
            raise RuntimeError("expected non-empty creature and gameobject identity surfaces")

        creature_sample = _one(
            connection,
            "SELECT creature_id AS entity_id FROM creatures ORDER BY creature_id LIMIT 1",
        )
        gameobject_sample = _one(
            connection,
            "SELECT gameobject_id AS entity_id FROM gameobjects ORDER BY gameobject_id LIMIT 1",
        )
        creature_sample_id = int(creature_sample["entity_id"])
        gameobject_sample_id = int(gameobject_sample["entity_id"])
        _detail(connection, "creature", creature_sample_id)
        _detail(connection, "gameobject", gameobject_sample_id)

        multi_spawn = _one(
            connection,
            """
            SELECT entity_kind, entity_id, spawn_count
            FROM (
                SELECT 'creature' AS entity_kind, creature_id AS entity_id,
                       COUNT(*) AS spawn_count
                FROM creature_spawns
                GROUP BY creature_id
                HAVING COUNT(*) >= 2
                UNION ALL
                SELECT 'gameobject', gameobject_id, COUNT(*)
                FROM gameobject_spawns
                GROUP BY gameobject_id
                HAVING COUNT(*) >= 2
            )
            ORDER BY entity_kind, entity_id
            LIMIT 1
            """,
        )
        multi_kind = str(multi_spawn["entity_kind"])
        multi_id = int(multi_spawn["entity_id"])
        multi_detail = _detail(connection, multi_kind, multi_id)
        if len(multi_detail["spawns"]) != int(multi_spawn["spawn_count"]):
            raise RuntimeError(
                "multi-spawn entity did not preserve every canonical spawn independently"
            )
        if len({row["spawn_key"] for row in multi_detail["spawns"]}) != len(
            multi_detail["spawns"]
        ):
            raise RuntimeError("multi-spawn entity collapsed distinct spawn keys")

        located = _one(
            connection,
            """
            SELECT entity_kind, entity_id, zone_id, map_id
            FROM (
                SELECT 'creature' AS entity_kind, s.creature_id AS entity_id, s.zone_id,
                       COALESCE(s.map_id, z.map_id) AS map_id
                FROM creature_spawns AS s
                LEFT JOIN zones AS z ON z.zone_id = s.zone_id
                WHERE s.zone_id IS NOT NULL AND COALESCE(s.map_id, z.map_id) IS NOT NULL
                UNION ALL
                SELECT 'gameobject', s.gameobject_id, s.zone_id,
                       COALESCE(s.map_id, z.map_id)
                FROM gameobject_spawns AS s
                LEFT JOIN zones AS z ON z.zone_id = s.zone_id
                WHERE s.zone_id IS NOT NULL AND COALESCE(s.map_id, z.map_id) IS NOT NULL
            )
            ORDER BY entity_kind, entity_id
            LIMIT 1
            """,
        )
        located_kind = str(located["entity_kind"])
        located_id = int(located["entity_id"])
        located_page = query_world_entities(
            connection,
            entity_kind=located_kind,
            entity_id=located_id,
            zone_id=int(located["zone_id"]),
            map_id=int(located["map_id"]),
            limit=10,
        )
        if not any(
            result.entity["entity_kind"] == located_kind
            and result.entity["entity_id"] == located_id
            and result.match_state == MATCH_KNOWN
            for result in located_page.results
        ):
            raise RuntimeError("known spawn geography did not round-trip as known_match")

        provenance_spawn = _one(
            connection,
            """
            SELECT entity_kind, entity_id, spawn_key
            FROM (
                SELECT 'creature' AS entity_kind, s.creature_id AS entity_id, s.spawn_key
                FROM creature_spawns AS s
                JOIN observation_groups AS og
                  ON og.subject_kind = 'creature_spawn'
                 AND og.subject_key = s.spawn_key
                 AND og.fact_key = 'position'
                 AND og.fact_instance_key = ''
                JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
                UNION ALL
                SELECT 'gameobject', s.gameobject_id, s.spawn_key
                FROM gameobject_spawns AS s
                JOIN observation_groups AS og
                  ON og.subject_kind = 'gameobject_spawn'
                 AND og.subject_key = s.spawn_key
                 AND og.fact_key = 'position'
                 AND og.fact_instance_key = ''
                JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            )
            ORDER BY entity_kind, entity_id, spawn_key
            LIMIT 1
            """,
        )
        provenance_detail = _detail(
            connection,
            str(provenance_spawn["entity_kind"]),
            int(provenance_spawn["entity_id"]),
        )
        selected_spawn = next(
            row
            for row in provenance_detail["spawns"]
            if row["spawn_key"] == str(provenance_spawn["spawn_key"])
        )
        if selected_spawn["provenance"]["position"] is None:
            raise RuntimeError("selected spawn position provenance disappeared from entity detail")

        complete_detail = _first_complete_spawn_set_detail(connection)
        if complete_detail is None:
            raise RuntimeError(
                "expected at least one selected complete spawn set in accepted P1 view"
            )

        duplicate_spawn_set_detail = _first_duplicate_spawn_set_detail(connection)
        if duplicate_spawn_set_detail is None:
            raise RuntimeError(
                "expected accepted canonical P1 evidence to retain a duplicate spawn_set member"
            )

        unlocated_detail = _first_unlocated_detail(connection)
        if unlocated_detail is None:
            raise RuntimeError("expected at least one unlocated canonical world entity")

        direct = _one(
            connection,
            """
            SELECT 'creature' AS entity_kind, creature_id AS entity_id, item_id
            FROM creature_loot
            UNION ALL
            SELECT 'gameobject', gameobject_id, item_id FROM gameobject_loot
            ORDER BY entity_kind, entity_id, item_id
            LIMIT 1
            """,
        )
        direct_detail = _detail(connection, str(direct["entity_kind"]), int(direct["entity_id"]))
        if not _path_exists(direct_detail, item_id=int(direct["item_id"]), path_kind="direct"):
            raise RuntimeError("representative direct loot relation disappeared from entity detail")

        reference = _one(
            connection,
            """
            SELECT entity_kind, entity_id, item_id
            FROM (
                SELECT 'creature' AS entity_kind, members.creature_id AS entity_id, irl.item_id
                FROM reference_loot_creatures AS members
                JOIN item_reference_loot AS irl
                  ON irl.reference_loot_id = members.reference_loot_id
                UNION ALL
                SELECT 'gameobject', members.gameobject_id, irl.item_id
                FROM reference_loot_gameobjects AS members
                JOIN item_reference_loot AS irl
                  ON irl.reference_loot_id = members.reference_loot_id
            )
            ORDER BY entity_kind, entity_id, item_id
            LIMIT 1
            """,
        )
        reference_detail = _detail(
            connection, str(reference["entity_kind"]), int(reference["entity_id"])
        )
        if not _path_exists(
            reference_detail, item_id=int(reference["item_id"]), path_kind="reference"
        ):
            raise RuntimeError("representative reference-loot relation disappeared")

        vendor = _one(
            connection,
            """
            SELECT vendor_creature_id AS entity_id, item_id
            FROM vendor_items
            ORDER BY vendor_creature_id, item_id
            LIMIT 1
            """,
        )
        vendor_id = int(vendor["entity_id"])
        vendor_detail = _detail(connection, "creature", vendor_id)
        if not _path_exists(vendor_detail, item_id=int(vendor["item_id"]), path_kind="vendor"):
            raise RuntimeError("representative vendor relation disappeared")
        vendor_paths = [
            path
            for item in vendor_detail["roles"]["item_acquisition"]
            if item["item_id"] == int(vendor["item_id"])
            for path in item["acquisition_paths"]
            if path["path_kind"] == "vendor"
        ]
        if not vendor_paths or vendor_paths[0]["chance_percent"] is not None:
            raise RuntimeError("vendor metadata was reinterpreted as drop chance")

        direct_trainer = _one(
            connection,
            """
            SELECT recipe_id, creature_id AS entity_id
            FROM recipe_trainer_sources
            WHERE trainer_kind = 'direct' AND creature_id IS NOT NULL
            ORDER BY recipe_id, native_trainer_entry, acquisition_spell_id
            LIMIT 1
            """,
        )
        direct_trainer_id = int(direct_trainer["entity_id"])
        trainer_detail = _detail(connection, "creature", direct_trainer_id)
        if not any(
            row["recipe_id"] == int(direct_trainer["recipe_id"])
            and row["trainer_kind"] == "direct"
            for row in trainer_detail["roles"]["trainers"]
        ):
            raise RuntimeError("direct trainer semantics disappeared from entity detail")

        template_trainer = connection.execute(
            """
            SELECT recipe_id, creature_id AS entity_id
            FROM recipe_trainer_sources
            WHERE trainer_kind = 'template' AND creature_id IS NOT NULL
            ORDER BY recipe_id, native_trainer_entry, acquisition_spell_id
            LIMIT 1
            """
        ).fetchone()
        template_trainer_recipe_id: int | None = None
        template_trainer_entity_id: int | None = None
        if template_trainer is not None:
            template_trainer_recipe_id = int(template_trainer["recipe_id"])
            template_trainer_entity_id = int(template_trainer["entity_id"])
            template_detail = _detail(connection, "creature", template_trainer_entity_id)
            if not any(
                row["recipe_id"] == template_trainer_recipe_id
                and row["trainer_kind"] == "template"
                and row["trainer_template_id"] is not None
                for row in template_detail["roles"]["trainers"]
            ):
                raise RuntimeError("template-expanded trainer semantics disappeared")

        quest_samples: dict[str, tuple[int, int]] = {}
        for role, sql in (
            (
                "giver",
                "SELECT quest_id, creature_id AS entity_id FROM quest_creature_endpoints "
                "WHERE endpoint_kind = 'giver' ORDER BY quest_id, creature_id LIMIT 1",
            ),
            (
                "finisher",
                "SELECT quest_id, creature_id AS entity_id FROM quest_creature_endpoints "
                "WHERE endpoint_kind = 'finisher' ORDER BY quest_id, creature_id LIMIT 1",
            ),
            (
                "objective",
                "SELECT quest_id, creature_id AS entity_id FROM quest_creature_objectives "
                "ORDER BY quest_id, creature_id LIMIT 1",
            ),
        ):
            sample = _one(connection, sql)
            quest_id = int(sample["quest_id"])
            entity_id = int(sample["entity_id"])
            role_detail = _detail(connection, "creature", entity_id)
            if not _role_exists(role_detail, quest_id=quest_id, role=role):
                raise RuntimeError(f"representative quest {role} role disappeared")
            quest_samples[role] = (quest_id, entity_id)

        deterministic_a = world_entity_query_page_to_dict(
            query_world_entities(
                connection,
                entity_kind=located_kind,
                entity_id=located_id,
                limit=10,
            )
        )
        deterministic_b = world_entity_query_page_to_dict(
            query_world_entities(
                connection,
                entity_kind=located_kind,
                entity_id=located_id,
                limit=10,
            )
        )
        if json.dumps(deterministic_a, sort_keys=True) != json.dumps(
            deterministic_b, sort_keys=True
        ):
            raise RuntimeError("repeated representative world-entity query is not deterministic")

        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_violations:
            raise RuntimeError(f"foreign_key_check failed: {foreign_key_violations[:5]}")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"integrity_check failed: {integrity}")
    finally:
        connection.close()

    after_sha = _sha256(db_path)
    if after_sha != before_sha:
        raise RuntimeError(
            "canonical DB changed during read-only validation: "
            f"{before_sha} -> {after_sha}"
        )

    return {
        "canonical_sha256": before_sha,
        "schema_version": schema_version,
        "creature_identities": creature_count,
        "gameobject_identities": gameobject_count,
        "creature_identity_sample_id": creature_sample_id,
        "gameobject_identity_sample_id": gameobject_sample_id,
        "multi_spawn_sample_kind": multi_kind,
        "multi_spawn_sample_id": multi_id,
        "located_sample_kind": located_kind,
        "located_sample_id": located_id,
        "complete_spawn_set_sample_kind": complete_detail["entity_kind"],
        "complete_spawn_set_sample_id": complete_detail["entity_id"],
        "duplicate_spawn_set_sample_kind": duplicate_spawn_set_detail["entity_kind"],
        "duplicate_spawn_set_sample_id": duplicate_spawn_set_detail["entity_id"],
        "duplicate_spawn_set_member_count": duplicate_spawn_set_detail["spawn_set"][
            "duplicate_source_member_count"
        ],
        "unlocated_sample_kind": unlocated_detail["entity_kind"],
        "unlocated_sample_id": unlocated_detail["entity_id"],
        "vendor_sample_entity_id": vendor_id,
        "direct_trainer_sample_entity_id": direct_trainer_id,
        "template_trainer_sample_recipe_id": template_trainer_recipe_id,
        "template_trainer_sample_entity_id": template_trainer_entity_id,
        "quest_giver_sample": quest_samples["giver"],
        "quest_finisher_sample": quest_samples["finisher"],
        "quest_objective_sample": quest_samples["objective"],
        "foreign_key_check": [],
        "integrity_check": integrity,
        "canonical_db_unchanged": True,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/generated/octogamedb.sqlite3"),
    )
    parser.add_argument("--expected-sha256", default=EXPECTED_CANONICAL_SHA256)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    result = validate(args.db, expected_sha256=args.expected_sha256)
    print("P7_T05_LOCAL_VALIDATION_OK")
    for key, value in result.items():
        if isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = value
        print(f"{key}={rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

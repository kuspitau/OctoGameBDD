"""Read-only Level-2 validator for P7-T06 against the accepted canonical DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from time import perf_counter
from typing import Any

from octogamedb.zone_search import MATCH_KNOWN, inspect_zone, query_zones, zone_query_page_to_dict

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
            "accepted canonical DB has no representative row for required P7-T06 gate"
        )
    return row


def _zone_has_item_path(detail: dict[str, Any], *, item_id: int, path_kind: str) -> bool:
    return any(
        item["item_id"] == item_id
        and any(path["path_kind"] == path_kind for path in item["paths"])
        for item in detail["items"]["results"]
    )


def _zone_has_quest_role(detail: dict[str, Any], *, quest_id: int, role: str) -> bool:
    bucket = {"giver": "given", "finisher": "finished", "objective": "objectives"}[role]
    return any(row["quest_id"] == quest_id for row in detail["quests"][bucket])


def _zone_has_trainer(
    detail: dict[str, Any], *, recipe_id: int, trainer_kind: str
) -> bool:
    return any(
        row["recipe_id"] == recipe_id and row["trainer_kind"] == trainer_kind
        for row in detail["trainers"]["known"]
    )


def _recipe_known_count(detail: dict[str, Any], path: str) -> int:
    if path == "teaching_item":
        return int(detail["recipes"]["teaching_item"]["summary"]["known_match_count"])
    if path == "trainer":
        return int(detail["recipes"]["trainer"]["summary"]["known_match_count"])
    quest_role = path.removeprefix("quest_")
    return int(
        detail["recipes"]["quest_reward_spell"][quest_role]["summary"]["known_match_count"]
    )


def validate(
    db_path: Path, *, expected_sha256: str = EXPECTED_CANONICAL_SHA256
) -> dict[str, object]:
    print("[P7-T06] Hashing canonical DB...", flush=True)
    before_sha = _sha256(db_path)
    if before_sha != expected_sha256:
        raise RuntimeError(
            f"unexpected canonical SHA-256: expected {expected_sha256}, observed {before_sha}"
        )

    print("[P7-T06] SHA verified; opening DB read-only.", flush=True)
    connection = _open_readonly(db_path)
    detail_cache: dict[tuple[int, bool], dict[str, Any]] = {}

    def detail(zone_id: int, *, include_recipes: bool = False) -> dict[str, Any]:
        key = (zone_id, include_recipes)
        cached = detail_cache.get(key)
        if cached is not None:
            return cached
        label = "with recipes" if include_recipes else "without recipes"
        print(f"[P7-T06] inspect_zone({zone_id}) {label}...", flush=True)
        started = perf_counter()
        cached = inspect_zone(
            connection,
            zone_id,
            entity_limit=1000,
            recipe_limit=1000,
            include_recipes=include_recipes,
        )
        elapsed = perf_counter() - started
        print(
            f"[P7-T06] inspect_zone({zone_id}) {label} OK in {elapsed:.2f}s",
            flush=True,
        )
        detail_cache[key] = cached
        return cached

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

        print("[P7-T06] Schema verified; checking zone identity surface.", flush=True)
        zone_count = int(connection.execute("SELECT COUNT(*) FROM zones").fetchone()[0])
        if zone_count <= 0:
            raise RuntimeError("expected non-empty canonical zone identity surface")

        identity_sample = _one(
            connection,
            """
            SELECT z.zone_id, z.name, z.map_id, m.name AS map_name
            FROM zones AS z
            LEFT JOIN maps AS m ON m.map_id = z.map_id
            ORDER BY z.zone_id
            LIMIT 1
            """,
        )
        zone_id = int(identity_sample["zone_id"])
        identity_page = query_zones(connection, zone_id=zone_id, limit=1)
        if len(identity_page.results) != 1 or identity_page.results[0].match_state != MATCH_KNOWN:
            raise RuntimeError("canonical zone ID did not round-trip as one known_match")
        name = str(identity_sample["name"])
        name_page = query_zones(connection, name_contains=name, limit=1000)
        if not any(result.zone["zone_id"] == zone_id for result in name_page.results):
            raise RuntimeError("canonical zone name did not round-trip through substring search")
        if identity_sample["map_id"] is not None:
            map_page = query_zones(connection, map_id=int(identity_sample["map_id"]), limit=1000)
            if not any(result.zone["zone_id"] == zone_id for result in map_page.results):
                raise RuntimeError("canonical map ID did not retain the representative zone")
        json.dumps(zone_query_page_to_dict(identity_page), sort_keys=True)

        print("[P7-T06] Checking representative multi-spawn zone.", flush=True)
        multi_spawn = _one(
            connection,
            """
            SELECT entity_kind, entity_id, zone_id, spawn_count
            FROM (
                SELECT 'creature' AS entity_kind, creature_id AS entity_id, zone_id,
                       COUNT(*) AS spawn_count
                FROM creature_spawns
                WHERE zone_id IS NOT NULL
                GROUP BY creature_id, zone_id
                HAVING COUNT(*) >= 2
                UNION ALL
                SELECT 'gameobject', gameobject_id, zone_id, COUNT(*)
                FROM gameobject_spawns
                WHERE zone_id IS NOT NULL
                GROUP BY gameobject_id, zone_id
                HAVING COUNT(*) >= 2
            )
            ORDER BY spawn_count, entity_kind, entity_id
            LIMIT 1
            """,
        )
        multi_zone = int(multi_spawn["zone_id"])
        multi_detail = detail(multi_zone)
        multi_entities = [
            row
            for row in multi_detail["world_entities"]["results"]
            if row["entity_kind"] == str(multi_spawn["entity_kind"])
            and row["entity_id"] == int(multi_spawn["entity_id"])
        ]
        if len(multi_entities) != 1:
            raise RuntimeError("representative multi-spawn entity was not retained in zone detail")
        if len(multi_entities[0]["matching_spawns"]) != int(multi_spawn["spawn_count"]):
            raise RuntimeError("zone detail collapsed independent same-zone spawn identities")
        if any(spawn["zone_id"] != multi_zone for spawn in multi_entities[0]["matching_spawns"]):
            raise RuntimeError("zone matching_spawns leaked a spawn from another zone")

        print("[P7-T06] Checking item acquisition paths.", flush=True)
        path_samples: dict[str, tuple[int, int]] = {}
        direct = _one(
            connection,
            """
            SELECT zone_id, item_id
            FROM (
                SELECT s.zone_id, l.item_id
                FROM creature_loot AS l
                JOIN creature_spawns AS s ON s.creature_id = l.creature_id
                WHERE s.zone_id IS NOT NULL
                UNION ALL
                SELECT s.zone_id, l.item_id
                FROM gameobject_loot AS l
                JOIN gameobject_spawns AS s ON s.gameobject_id = l.gameobject_id
                WHERE s.zone_id IS NOT NULL
            )
            ORDER BY zone_id, item_id
            LIMIT 1
            """,
        )
        path_samples["direct"] = (int(direct["zone_id"]), int(direct["item_id"]))

        reference = _one(
            connection,
            """
            SELECT zone_id, item_id
            FROM (
                SELECT s.zone_id, irl.item_id
                FROM reference_loot_creatures AS members
                JOIN item_reference_loot AS irl
                  ON irl.reference_loot_id = members.reference_loot_id
                JOIN creature_spawns AS s ON s.creature_id = members.creature_id
                WHERE s.zone_id IS NOT NULL
                UNION ALL
                SELECT s.zone_id, irl.item_id
                FROM reference_loot_gameobjects AS members
                JOIN item_reference_loot AS irl
                  ON irl.reference_loot_id = members.reference_loot_id
                JOIN gameobject_spawns AS s ON s.gameobject_id = members.gameobject_id
                WHERE s.zone_id IS NOT NULL
            )
            ORDER BY zone_id, item_id
            LIMIT 1
            """,
        )
        path_samples["reference"] = (int(reference["zone_id"]), int(reference["item_id"]))

        vendor = _one(
            connection,
            """
            SELECT s.zone_id, v.item_id
            FROM vendor_items AS v
            JOIN creature_spawns AS s ON s.creature_id = v.vendor_creature_id
            WHERE s.zone_id IS NOT NULL
            ORDER BY s.zone_id, v.item_id
            LIMIT 1
            """,
        )
        path_samples["vendor"] = (int(vendor["zone_id"]), int(vendor["item_id"]))

        for path_kind, (sample_zone, item_id) in path_samples.items():
            sample_detail = detail(sample_zone)
            if not _zone_has_item_path(sample_detail, item_id=item_id, path_kind=path_kind):
                raise RuntimeError(
                    f"representative {path_kind} item acquisition path disappeared from zone detail"
                )
        vendor_detail = detail(path_samples["vendor"][0])
        vendor_paths = [
            path
            for item in vendor_detail["items"]["results"]
            if item["item_id"] == path_samples["vendor"][1]
            for path in item["paths"]
            if path["path_kind"] == "vendor"
        ]
        if not vendor_paths or any(path["chance_percent"] is not None for path in vendor_paths):
            raise RuntimeError("vendor max_count was reinterpreted as a drop probability")

        print("[P7-T06] Checking quest geography roles.", flush=True)
        quest_samples: dict[str, tuple[int, int]] = {}
        for role in ("giver", "finisher"):
            row = _one(
                connection,
                f"""
                SELECT zone_id, quest_id
                FROM (
                    SELECT s.zone_id, e.quest_id
                    FROM quest_creature_endpoints AS e
                    JOIN creature_spawns AS s ON s.creature_id = e.creature_id
                    WHERE e.endpoint_kind = '{role}' AND s.zone_id IS NOT NULL
                    UNION ALL
                    SELECT s.zone_id, e.quest_id
                    FROM quest_gameobject_endpoints AS e
                    JOIN gameobject_spawns AS s ON s.gameobject_id = e.gameobject_id
                    WHERE e.endpoint_kind = '{role}' AND s.zone_id IS NOT NULL
                )
                ORDER BY zone_id, quest_id
                LIMIT 1
                """,
            )
            quest_samples[role] = (int(row["zone_id"]), int(row["quest_id"]))
        objective = _one(
            connection,
            """
            SELECT zone_id, quest_id
            FROM (
                SELECT s.zone_id, o.quest_id
                FROM quest_creature_objectives AS o
                JOIN creature_spawns AS s ON s.creature_id = o.creature_id
                WHERE s.zone_id IS NOT NULL
                UNION ALL
                SELECT s.zone_id, o.quest_id
                FROM quest_gameobject_objectives AS o
                JOIN gameobject_spawns AS s ON s.gameobject_id = o.gameobject_id
                WHERE s.zone_id IS NOT NULL
            )
            ORDER BY zone_id, quest_id
            LIMIT 1
            """,
        )
        quest_samples["objective"] = (int(objective["zone_id"]), int(objective["quest_id"]))
        for role, (sample_zone, quest_id) in quest_samples.items():
            if not _zone_has_quest_role(detail(sample_zone), quest_id=quest_id, role=role):
                raise RuntimeError(f"representative quest {role} role disappeared from zone detail")

        print("[P7-T06] Checking trainer roles.", flush=True)
        trainer_samples: dict[str, tuple[int, int]] = {}
        for trainer_kind in ("direct", "template"):
            row = _one(
                connection,
                f"""
                SELECT s.zone_id, ts.recipe_id
                FROM recipe_trainer_sources AS ts
                JOIN creature_spawns AS s ON s.creature_id = ts.creature_id
                WHERE ts.trainer_kind = '{trainer_kind}'
                  AND ts.creature_id IS NOT NULL
                  AND s.zone_id IS NOT NULL
                ORDER BY s.zone_id, ts.recipe_id
                LIMIT 1
                """,
            )
            trainer_samples[trainer_kind] = (int(row["zone_id"]), int(row["recipe_id"]))
            if not _zone_has_trainer(
                detail(int(row["zone_id"])),
                recipe_id=int(row["recipe_id"]),
                trainer_kind=trainer_kind,
            ):
                raise RuntimeError(
                    f"representative {trainer_kind} trainer role disappeared from zone detail"
                )

        print("[P7-T06] Checking fast recipe projection.", flush=True)
        teaching_zone = _one(
            connection,
            """
            SELECT zone_id
            FROM (
                SELECT s.zone_id
                FROM recipe_teaching_items AS ti
                JOIN creature_loot AS l ON l.item_id = ti.item_id
                JOIN creature_spawns AS s ON s.creature_id = l.creature_id
                WHERE ti.item_id IS NOT NULL AND s.zone_id IS NOT NULL
                UNION ALL
                SELECT s.zone_id
                FROM recipe_teaching_items AS ti
                JOIN gameobject_loot AS l ON l.item_id = ti.item_id
                JOIN gameobject_spawns AS s ON s.gameobject_id = l.gameobject_id
                WHERE ti.item_id IS NOT NULL AND s.zone_id IS NOT NULL
                UNION ALL
                SELECT s.zone_id
                FROM recipe_teaching_items AS ti
                JOIN vendor_items AS v ON v.item_id = ti.item_id
                JOIN creature_spawns AS s ON s.creature_id = v.vendor_creature_id
                WHERE ti.item_id IS NOT NULL AND s.zone_id IS NOT NULL
            )
            ORDER BY zone_id
            LIMIT 1
            """,
        )
        teaching_zone_id = int(teaching_zone["zone_id"])
        if _recipe_known_count(detail(teaching_zone_id, include_recipes=True), "teaching_item") <= 0:
            raise RuntimeError(
                "known teaching-item recipe geography was not composed into zone detail"
            )

        trainer_zone_id = trainer_samples["direct"][0]
        if _recipe_known_count(detail(trainer_zone_id, include_recipes=True), "trainer") <= 0:
            raise RuntimeError("known trainer recipe geography was not composed into zone detail")

        quest_recipe_sample: tuple[str, int] | None = None
        for role in ("giver", "finisher", "objective"):
            sample_zone, quest_id = quest_samples[role]
            exists = connection.execute(
                "SELECT 1 FROM recipe_quest_learning_sources WHERE quest_id = ? LIMIT 1",
                (quest_id,),
            ).fetchone()
            if exists is not None:
                quest_recipe_sample = (role, sample_zone)
                break
        if quest_recipe_sample is None:
            row = _one(
                connection,
                """
                SELECT role, zone_id
                FROM (
                    SELECT 'giver' AS role, s.zone_id, qs.recipe_id
                    FROM recipe_quest_learning_sources AS qs
                    JOIN quest_creature_endpoints AS e ON e.quest_id = qs.quest_id
                    JOIN creature_spawns AS s ON s.creature_id = e.creature_id
                    WHERE e.endpoint_kind = 'giver' AND s.zone_id IS NOT NULL
                    UNION ALL
                    SELECT 'finisher', s.zone_id, qs.recipe_id
                    FROM recipe_quest_learning_sources AS qs
                    JOIN quest_creature_endpoints AS e ON e.quest_id = qs.quest_id
                    JOIN creature_spawns AS s ON s.creature_id = e.creature_id
                    WHERE e.endpoint_kind = 'finisher' AND s.zone_id IS NOT NULL
                    UNION ALL
                    SELECT 'objective', s.zone_id, qs.recipe_id
                    FROM recipe_quest_learning_sources AS qs
                    JOIN quest_creature_objectives AS o ON o.quest_id = qs.quest_id
                    JOIN creature_spawns AS s ON s.creature_id = o.creature_id
                    WHERE s.zone_id IS NOT NULL
                )
                ORDER BY role, zone_id
                LIMIT 1
                """,
            )
            quest_recipe_sample = (str(row["role"]), int(row["zone_id"]))
        quest_recipe_role, quest_recipe_zone = quest_recipe_sample
        if _recipe_known_count(
            detail(quest_recipe_zone, include_recipes=True),
            f"quest_{quest_recipe_role}",
        ) <= 0:
            raise RuntimeError(
                "known quest-learning recipe geography was not composed into zone detail"
            )

        representative_detail = detail(multi_zone)
        if representative_detail["coverage"]["state"] != "unknown":
            raise RuntimeError("zone content coverage incorrectly claims universal completeness")
        if representative_detail["coverage"]["negative_claim_authorized"] is not False:
            raise RuntimeError("P7-T06 incorrectly authorized a universal zone-content negative")

        print("[P7-T06] Running FK and integrity checks.", flush=True)
        foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = None if integrity_row is None else str(integrity_row[0])
        if foreign_key_rows:
            raise RuntimeError(f"foreign key check failed: {foreign_key_rows!r}")
        if integrity != "ok":
            raise RuntimeError(f"integrity check failed: {integrity!r}")
    finally:
        connection.close()

    after_sha = _sha256(db_path)
    if after_sha != before_sha:
        raise RuntimeError("canonical DB changed during read-only P7-T06 validation")

    return {
        "canonical_sha256": before_sha,
        "schema_version": schema_version,
        "zone_identities": zone_count,
        "identity_sample_zone_id": zone_id,
        "multi_spawn_sample_zone_id": multi_zone,
        "direct_item_sample_zone_id": path_samples["direct"][0],
        "reference_item_sample_zone_id": path_samples["reference"][0],
        "vendor_item_sample_zone_id": path_samples["vendor"][0],
        "quest_giver_sample_zone_id": quest_samples["giver"][0],
        "quest_finisher_sample_zone_id": quest_samples["finisher"][0],
        "quest_objective_sample_zone_id": quest_samples["objective"][0],
        "teaching_recipe_sample_zone_id": teaching_zone_id,
        "trainer_recipe_sample_zone_id": trainer_zone_id,
        "quest_recipe_sample_zone_id": quest_recipe_zone,
        "validated_zone_detail_count": len(detail_cache),
        "foreign_key_check": [],
        "integrity_check": "ok",
        "canonical_db_unchanged": True,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate P7-T06 zone exploration against the accepted canonical DB read-only."
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=EXPECTED_CANONICAL_SHA256)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        result = validate(args.db, expected_sha256=args.expected_sha256)
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError, TypeError, RuntimeError) as exc:
        print(f"P7_T06_LOCAL_VALIDATION_FAILED: {exc}")
        return 1

    print("P7_T06_LOCAL_VALIDATION_OK")
    for key, value in result.items():
        rendered = json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value
        print(f"{key}={rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

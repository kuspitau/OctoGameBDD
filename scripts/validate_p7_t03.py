"""Read-only Level-2 validator for P7-T03 against the accepted canonical DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from octogamedb.quest_search import (
    MATCH_KNOWN,
    quest_query_page_to_dict,
    query_quests,
    traverse_quest_progression,
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


def _located_endpoint_sample(
    connection: sqlite3.Connection, endpoint_kind: str
) -> tuple[int, int, int]:
    row = connection.execute(
        """
        SELECT e.quest_id, s.zone_id, COALESCE(s.map_id, z.map_id) AS map_id
        FROM quest_creature_endpoints AS e
        JOIN creature_spawns AS s ON s.creature_id = e.creature_id
        LEFT JOIN zones AS z ON z.zone_id = s.zone_id
        WHERE e.endpoint_kind = ? AND s.zone_id IS NOT NULL
          AND COALESCE(s.map_id, z.map_id) IS NOT NULL

        UNION ALL

        SELECT e.quest_id, s.zone_id, COALESCE(s.map_id, z.map_id) AS map_id
        FROM quest_gameobject_endpoints AS e
        JOIN gameobject_spawns AS s ON s.gameobject_id = e.gameobject_id
        LEFT JOIN zones AS z ON z.zone_id = s.zone_id
        WHERE e.endpoint_kind = ? AND s.zone_id IS NOT NULL
          AND COALESCE(s.map_id, z.map_id) IS NOT NULL

        ORDER BY 1, 2, 3
        LIMIT 1
        """,
        (endpoint_kind, endpoint_kind),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"canonical DB has no located {endpoint_kind} endpoint")
    return int(row["quest_id"]), int(row["zone_id"]), int(row["map_id"])


def _located_objective_sample(connection: sqlite3.Connection) -> tuple[int, int, int, str]:
    row = connection.execute(
        """
        SELECT o.quest_id, s.zone_id, COALESCE(s.map_id, z.map_id) AS map_id, 'U' AS subtype
        FROM quest_creature_objectives AS o
        JOIN creature_spawns AS s ON s.creature_id = o.creature_id
        LEFT JOIN zones AS z ON z.zone_id = s.zone_id
        WHERE s.zone_id IS NOT NULL AND COALESCE(s.map_id, z.map_id) IS NOT NULL

        UNION ALL

        SELECT o.quest_id, s.zone_id, COALESCE(s.map_id, z.map_id) AS map_id, 'O' AS subtype
        FROM quest_gameobject_objectives AS o
        JOIN gameobject_spawns AS s ON s.gameobject_id = o.gameobject_id
        LEFT JOIN zones AS z ON z.zone_id = s.zone_id
        WHERE s.zone_id IS NOT NULL AND COALESCE(s.map_id, z.map_id) IS NOT NULL

        ORDER BY 1, 4, 2, 3
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("canonical DB has no located creature/gameobject quest objective")
    return (
        int(row["quest_id"]),
        int(row["zone_id"]),
        int(row["map_id"]),
        str(row["subtype"]),
    )


def _known_geo_query(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    role: str,
    zone_id: int,
    map_id: int,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "quest_id": quest_id,
        f"{role}_zone_id": zone_id,
        f"{role}_map_id": map_id,
        "include_states": (MATCH_KNOWN,),
        "limit": 10,
    }
    page = query_quests(connection, **kwargs)
    if [result.quest["quest_id"] for result in page.results] != [quest_id]:
        raise RuntimeError(f"known {role} geography query did not round-trip quest {quest_id}")
    predicate = next(
        (
            predicate
            for predicate in page.results[0].predicates
            if predicate.predicate.startswith(f"{role}_geography[")
        ),
        None,
    )
    if predicate is None or predicate.state != MATCH_KNOWN:
        raise RuntimeError(f"known {role} geography was not classified as known_match")
    return page.results[0].quest


def _first_progression_sample(connection: sqlite3.Connection) -> tuple[int, int]:
    row = connection.execute(
        """
        SELECT quest_id, member_quest_id
        FROM quest_prerequisite_set_members
        ORDER BY quest_id, member_quest_id
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("canonical DB has no materialized prerequisite relation")
    return int(row["quest_id"]), int(row["member_quest_id"])


def _first_close_sample(connection: sqlite3.Connection) -> tuple[int, int]:
    row = connection.execute(
        """
        SELECT quest_id, member_quest_id
        FROM quest_close_set_members
        ORDER BY quest_id, member_quest_id
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("canonical DB has no materialized close/exclusive relation")
    return int(row["quest_id"]), int(row["member_quest_id"])


def _first_quantity_sample(connection: sqlite3.Connection, table: str) -> tuple[int, int, int]:
    row = connection.execute(
        f"SELECT quest_id, item_id, quantity FROM {table} ORDER BY quest_id, item_id LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError(f"canonical DB has no rows in {table}")
    return int(row["quest_id"]), int(row["item_id"]), int(row["quantity"])


def _first_turtle_name_sample(connection: sqlite3.Connection) -> int | None:
    row = connection.execute(
        """
        SELECT CAST(og.subject_key AS INTEGER) AS quest_id
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = 'quest' AND og.fact_key = 'name'
          AND og.fact_instance_key = '' AND ds.source_key = 'pfquest-turtle'
        ORDER BY CAST(og.subject_key AS INTEGER)
        LIMIT 1
        """
    ).fetchone()
    return None if row is None else int(row["quest_id"])


def _first_unlocated_endpoint_sample(connection: sqlite3.Connection) -> int | None:
    row = connection.execute(
        """
        SELECT e.quest_id
        FROM quest_creature_endpoints AS e
        WHERE NOT EXISTS (
            SELECT 1 FROM creature_spawns AS s WHERE s.creature_id = e.creature_id
        )
        UNION
        SELECT e.quest_id
        FROM quest_gameobject_endpoints AS e
        WHERE NOT EXISTS (
            SELECT 1 FROM gameobject_spawns AS s WHERE s.gameobject_id = e.gameobject_id
        )
        ORDER BY 1
        LIMIT 1
        """
    ).fetchone()
    return None if row is None else int(row["quest_id"])


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
        quest_count = int(connection.execute("SELECT COUNT(*) FROM quests").fetchone()[0])
        if quest_count <= 0:
            raise RuntimeError("expected non-empty canonical quest identity surface")

        giver_id, giver_zone, giver_map = _located_endpoint_sample(connection, "giver")
        giver = _known_geo_query(
            connection,
            quest_id=giver_id,
            role="giver",
            zone_id=giver_zone,
            map_id=giver_map,
        )
        if not any(endpoint["endpoint_kind"] == "giver" for endpoint in giver["endpoints"]):
            raise RuntimeError("representative giver query lost giver endpoint identity")

        finisher_id, finisher_zone, finisher_map = _located_endpoint_sample(connection, "finisher")
        finisher = _known_geo_query(
            connection,
            quest_id=finisher_id,
            role="finisher",
            zone_id=finisher_zone,
            map_id=finisher_map,
        )
        if not any(endpoint["endpoint_kind"] == "finisher" for endpoint in finisher["endpoints"]):
            raise RuntimeError("representative finisher query lost finisher endpoint identity")

        objective_id, objective_zone, objective_map, objective_subtype = _located_objective_sample(
            connection
        )
        objective = _known_geo_query(
            connection,
            quest_id=objective_id,
            role="objective",
            zone_id=objective_zone,
            map_id=objective_map,
        )
        if not any(
            row.get("source_subtype") == objective_subtype
            for row in objective["objectives"]["objectives"]
        ):
            raise RuntimeError("representative objective query lost objective subtype")

        prerequisite_quest_id, prerequisite_member_id = _first_progression_sample(connection)
        prerequisite = traverse_quest_progression(
            connection,
            prerequisite_quest_id,
            direction="prerequisite",
            max_depth=1,
            max_nodes=50,
        )
        if prerequisite is None or not any(
            edge["to_quest_id"] == prerequisite_member_id for edge in prerequisite["edges"]
        ):
            raise RuntimeError("representative prerequisite traversal lost selected member")
        if prerequisite["depth_is_chain_step"] is not False:
            raise RuntimeError("derived traversal depth was mislabeled as chain step")

        follow_up = traverse_quest_progression(
            connection,
            prerequisite_member_id,
            direction="follow_up",
            max_depth=1,
            max_nodes=50,
        )
        if follow_up is None or not any(
            edge["to_quest_id"] == prerequisite_quest_id for edge in follow_up["edges"]
        ):
            raise RuntimeError("representative reverse follow-up traversal was not derived")

        close_quest_id, close_member_id = _first_close_sample(connection)
        close_page = query_quests(connection, quest_id=close_quest_id, limit=10)
        if [result.quest["quest_id"] for result in close_page.results] != [close_quest_id]:
            raise RuntimeError("representative close-set quest query did not round-trip")
        close_set = close_page.results[0].quest["progression"]["close_set"]
        if close_set["semantics"] != "exclusive_group_member_set":
            raise RuntimeError("close set lost exclusive-group semantics")
        if close_member_id not in [member["quest_id"] for member in close_set["members"]]:
            raise RuntimeError("representative close member disappeared")
        close_traversal = traverse_quest_progression(
            connection, close_quest_id, direction="prerequisite", max_depth=1, max_nodes=50
        )
        if close_traversal is not None and close_member_id in {
            edge["to_quest_id"] for edge in close_traversal["edges"]
        }:
            prerequisite_members = {
                member["quest_id"]
                for member in close_page.results[0].quest["progression"]["prerequisite_set"][
                    "members"
                ]
            }
            if close_member_id not in prerequisite_members:
                raise RuntimeError("close-only membership leaked into prerequisite traversal")

        required_quest_id, required_item_id, required_quantity = _first_quantity_sample(
            connection, "quest_required_items"
        )
        required_page = query_quests(connection, quest_id=required_quest_id, limit=10)
        required_items = required_page.results[0].quest["item_facts"]["required_items"]
        if not any(
            item["item_id"] == required_item_id and item["quantity"] == required_quantity
            for item in required_items
        ):
            raise RuntimeError("quantity-bearing required item fact did not round-trip")

        reward_quest_id, reward_item_id, reward_quantity = _first_quantity_sample(
            connection, "quest_reward_items"
        )
        reward_page = query_quests(connection, quest_id=reward_quest_id, limit=10)
        rewards = reward_page.results[0].quest["item_facts"]["guaranteed_rewards"]
        if not any(
            item["item_id"] == reward_item_id and item["quantity"] == reward_quantity
            for item in rewards
        ):
            raise RuntimeError("quantity-bearing guaranteed reward did not round-trip")

        turtle_quest_id = _first_turtle_name_sample(connection)
        if turtle_quest_id is not None:
            turtle_page = query_quests(connection, quest_id=turtle_quest_id, limit=10)
            if (
                turtle_page.results[0].quest["identity_provenance"]["source_key"]
                != "pfquest-turtle"
            ):
                raise RuntimeError("Turtle-selected quest identity lost selected provenance")

        unlocated_quest_id = _first_unlocated_endpoint_sample(connection)
        if unlocated_quest_id is not None:
            unlocated_page = query_quests(connection, quest_id=unlocated_quest_id, limit=10)
            if not any(
                not endpoint["geography_resolved"]
                for endpoint in unlocated_page.results[0].quest["endpoints"]
            ):
                raise RuntimeError("known unlocated endpoint was not preserved explicitly")

        deterministic_a = quest_query_page_to_dict(
            query_quests(connection, quest_id=giver_id, limit=10)
        )
        deterministic_b = quest_query_page_to_dict(
            query_quests(connection, quest_id=giver_id, limit=10)
        )
        if json.dumps(deterministic_a, sort_keys=True) != json.dumps(
            deterministic_b, sort_keys=True
        ):
            raise RuntimeError("repeated representative quest query is not deterministic")

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
        "quest_identities": quest_count,
        "located_giver_sample_quest_id": giver_id,
        "located_finisher_sample_quest_id": finisher_id,
        "located_objective_sample_quest_id": objective_id,
        "prerequisite_sample_quest_id": prerequisite_quest_id,
        "prerequisite_sample_member_id": prerequisite_member_id,
        "close_sample_quest_id": close_quest_id,
        "required_item_sample_quest_id": required_quest_id,
        "reward_item_sample_quest_id": reward_quest_id,
        "turtle_selected_sample_quest_id": turtle_quest_id,
        "unlocated_endpoint_sample_quest_id": unlocated_quest_id,
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
    print("P7_T03_LOCAL_VALIDATION_OK")
    for key, value in result.items():
        if isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = value
        print(f"{key}={rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from octogamedb.zone_cli import main as zone_main
from octogamedb.zone_search import (
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    inspect_zone,
    query_zones,
    zone_query_page_to_dict,
)


def _create_zone_schema(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE maps (
            map_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            map_kind TEXT,
            parent_map_id INTEGER
        );
        CREATE TABLE zones (
            zone_id INTEGER PRIMARY KEY,
            map_id INTEGER,
            parent_zone_id INTEGER,
            name TEXT NOT NULL
        );
        CREATE TABLE data_sources (
            id INTEGER PRIMARY KEY,
            source_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            source_kind TEXT NOT NULL
        );
        CREATE TABLE observation_groups (
            id INTEGER PRIMARY KEY,
            subject_kind TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            fact_instance_key TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE source_observations (
            id INTEGER PRIMARY KEY,
            observation_group_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            source_revision TEXT NOT NULL,
            source_record_type TEXT,
            raw_identifier TEXT,
            value_json TEXT NOT NULL,
            authority_tier INTEGER
        );
        CREATE TABLE canonical_selections (
            observation_group_id INTEGER PRIMARY KEY,
            observation_id INTEGER NOT NULL,
            selection_policy TEXT,
            selection_reason TEXT NOT NULL
        );
        """
    )
    connection.executemany(
        "INSERT INTO maps(map_id, name, map_kind, parent_map_id) VALUES (?, ?, ?, ?)",
        [
            (0, "Azeroth", "continent", None),
            (1, "Kalimdor", "continent", None),
        ],
    )
    connection.executemany(
        "INSERT INTO zones(zone_id, map_id, parent_zone_id, name) VALUES (?, ?, ?, ?)",
        [
            (10, 0, None, "Elwynn Forest"),
            (11, 0, 10, "Northshire Valley"),
            (20, 1, None, "Durotar"),
            (99, None, None, "Unknown Reach"),
        ],
    )
    connection.execute(
        "INSERT INTO data_sources(id, source_key, display_name, source_kind) "
        "VALUES (1, 'fixture', 'Fixture', 'test')"
    )
    connection.execute(
        "INSERT INTO observation_groups("
        "id, subject_kind, subject_key, fact_key, fact_instance_key"
        ") VALUES (1, 'zone', '10', 'name', '')"
    )
    connection.execute(
        "INSERT INTO source_observations(id, observation_group_id, source_id, source_revision, "
        "source_record_type, raw_identifier, value_json, authority_tier) "
        "VALUES (1, 1, 1, 'r1', 'zone', '10', '\"Elwynn Forest\"', 1)"
    )
    connection.execute(
        "INSERT INTO canonical_selections("
        "observation_group_id, observation_id, selection_policy, selection_reason"
        ") VALUES (1, 1, 'fixture', 'fixture winner')"
    )
    connection.commit()


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    _create_zone_schema(connection)
    return connection


def test_zone_identity_name_map_hierarchy_and_provenance() -> None:
    connection = _connection()
    page = query_zones(connection, zone_id=11, map_id=0)
    assert page.summary.total_zone_identities == 4
    assert page.summary.known_match_count == 1
    assert len(page.results) == 1
    zone = page.results[0].zone
    assert zone["zone_id"] == 11
    assert zone["parent_zone"] == {"zone_id": 10, "name": "Elwynn Forest"}
    assert zone["map"]["map_id"] == 0
    assert zone["map"]["name"] == "Azeroth"

    named = query_zones(connection, name_contains="elwynn")
    assert [result.zone["zone_id"] for result in named.results] == [10]
    assert named.results[0].zone["provenance"]["zone_name"]["source_key"] == "fixture"

    map_named = query_zones(connection, map_name_contains="azer")
    assert [result.zone["zone_id"] for result in map_named.results] == [10, 11]


def test_missing_map_is_unknown_not_known_non_match() -> None:
    connection = _connection()
    page = query_zones(
        connection,
        map_id=0,
        include_states=(MATCH_KNOWN, NON_MATCH_KNOWN, MATCH_UNKNOWN),
    )
    states = {result.zone["zone_id"]: result.match_state for result in page.results}
    assert states[10] == MATCH_KNOWN
    assert states[20] == NON_MATCH_KNOWN
    assert states[99] == MATCH_UNKNOWN


def test_zone_sorting_is_deterministic_and_unknown_map_values_stay_last() -> None:
    connection = _connection()
    page = query_zones(
        connection,
        include_states=(MATCH_KNOWN,),
        sort_by="map_name",
        descending=True,
        limit=3,
    )
    assert [result.zone["zone_id"] for result in page.results] == [20, 11, 10]
    page = query_zones(
        connection,
        include_states=(MATCH_KNOWN,),
        sort_by="map_name",
        descending=True,
        limit=4,
    )
    assert page.results[-1].zone["zone_id"] == 99


def _world_payload() -> dict[str, object]:
    spawn_a = {
        "spawn_id": 1,
        "spawn_key": "creature:10:a",
        "zone_id": 10,
        "map_id": 0,
        "x": 10.0,
        "y": 20.0,
        "provenance": {"position": {"source_key": "world"}},
    }
    spawn_b = {
        "spawn_id": 2,
        "spawn_key": "creature:10:b",
        "zone_id": 10,
        "map_id": 0,
        "x": 30.0,
        "y": 40.0,
        "provenance": {"position": {"source_key": "world"}},
    }
    spawn_other = {
        "spawn_id": 3,
        "spawn_key": "creature:10:c",
        "zone_id": 20,
        "map_id": 1,
        "x": 50.0,
        "y": 60.0,
        "provenance": {"position": {"source_key": "world"}},
    }
    go_spawn = {
        "spawn_id": 4,
        "spawn_key": "gameobject:20:a",
        "zone_id": 10,
        "map_id": 0,
        "x": 15.0,
        "y": 25.0,
        "provenance": {"position": {"source_key": "world"}},
    }
    creature = {
        "entity_kind": "creature",
        "entity_id": 10,
        "name": "Role Creature",
        "template": {"level_min": 10, "level_max": 10},
        "template_provenance": {"name": {"source_key": "world"}},
        "world_presence": {"selected_value": True},
        "spawns": [spawn_a, spawn_b, spawn_other],
        "spawn_set": {"declared": True, "is_complete_for_canonical_view": True},
        "roles": {
            "item_acquisition": [
                {
                    "item_id": 100,
                    "item_name": "Three-path Item",
                    "acquisition_paths": [
                        {
                            "path_kind": "direct",
                            "chance_percent": 25.0,
                            "reference_loot_id": None,
                            "vendor_max_count": None,
                            "relation_provenance": {"source_key": "loot"},
                            "reference_membership_provenance": None,
                        },
                        {
                            "path_kind": "reference",
                            "chance_percent": 5.0,
                            "reference_loot_id": 77,
                            "vendor_max_count": None,
                            "relation_provenance": {"source_key": "loot"},
                            "reference_membership_provenance": {"source_key": "loot"},
                        },
                        {
                            "path_kind": "vendor",
                            "chance_percent": None,
                            "reference_loot_id": None,
                            "vendor_max_count": 3,
                            "relation_provenance": {"source_key": "vendor"},
                            "reference_membership_provenance": None,
                        },
                    ],
                }
            ],
            "quests": [
                {
                    "quest_id": 200,
                    "quest_name": "Given Here",
                    "quest_resolved": True,
                    "role": "giver",
                    "objective_kind": None,
                    "relation_materialized": True,
                    "relation_resolution_reason": None,
                    "provenance": {"source_key": "quest"},
                    "quest_detail_owner": "P7-T03",
                },
                {
                    "quest_id": 201,
                    "quest_name": "Finished Here",
                    "quest_resolved": True,
                    "role": "finisher",
                    "objective_kind": None,
                    "relation_materialized": True,
                    "relation_resolution_reason": None,
                    "provenance": {"source_key": "quest"},
                    "quest_detail_owner": "P7-T03",
                },
                {
                    "quest_id": 202,
                    "quest_name": "Kill Here",
                    "quest_resolved": True,
                    "role": "objective",
                    "objective_kind": "creature",
                    "relation_materialized": True,
                    "relation_resolution_reason": None,
                    "provenance": {"source_key": "quest"},
                    "quest_detail_owner": "P7-T03",
                },
            ],
            "trainers": [
                {
                    "recipe_id": 300,
                    "recipe_name": "Known Recipe",
                    "trainer_kind": "direct",
                    "native_trainer_entry": 10,
                    "creature_id": 10,
                    "resolved": True,
                    "trainer_template_id": None,
                    "provenance": {"source_key": "trainer"},
                },
                {
                    "recipe_id": 301,
                    "recipe_name": "Unresolved Recipe",
                    "trainer_kind": "template",
                    "native_trainer_entry": 10,
                    "creature_id": None,
                    "resolved": False,
                    "trainer_template_id": 900,
                    "provenance": {"source_key": "trainer"},
                },
            ],
        },
    }
    gameobject = {
        "entity_kind": "gameobject",
        "entity_id": 20,
        "name": "Objective Object",
        "template": {"object_type": "chest"},
        "template_provenance": {"name": {"source_key": "world"}},
        "world_presence": {"selected_value": True},
        "spawns": [go_spawn],
        "spawn_set": {"declared": False, "is_complete_for_canonical_view": False},
        "roles": {
            "item_acquisition": [],
            "quests": [
                {
                    "quest_id": 203,
                    "quest_name": "Use Object",
                    "quest_resolved": True,
                    "role": "objective",
                    "objective_kind": "gameobject",
                    "relation_materialized": True,
                    "relation_resolution_reason": None,
                    "provenance": {"source_key": "quest"},
                    "quest_detail_owner": "P7-T03",
                }
            ],
            "trainers": [],
        },
    }
    return {
        "summary": {
            "total_entity_identities": 3,
            "total_creature_identities": 2,
            "total_gameobject_identities": 1,
            "known_match_count": 2,
            "known_non_match_count": 0,
            "unknown_count": 1,
            "returned_count": 2,
            "limit": 1000,
        },
        "results": [
            {"match_state": MATCH_KNOWN, "predicates": [], "entity": creature},
            {"match_state": MATCH_KNOWN, "predicates": [], "entity": gameobject},
        ],
    }


def test_zone_detail_composes_independent_world_item_quest_vendor_and_trainer_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import octogamedb.zone_search as zone_search

    connection = _connection()
    world_payload = _world_payload()
    monkeypatch.setattr(zone_search, "query_world_entities", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        zone_search,
        "world_entity_query_page_to_dict",
        lambda page: world_payload,
    )
    monkeypatch.setattr(
        zone_search,
        "_recipe_projection",
        lambda *args, **kwargs: {
            "included": True,
            "teaching_item": {
                "summary": {
                    "total_recipe_identities": 10,
                    "known_match_count": 1,
                    "known_non_match_count": 0,
                    "unknown_count": 9,
                    "returned_count": 1,
                    "limit": kwargs["recipe_limit"],
                },
                "results": [],
            },
            "trainer": {
                "summary": {
                    "total_recipe_identities": 10,
                    "known_match_count": 1,
                    "known_non_match_count": 0,
                    "unknown_count": 9,
                    "returned_count": 1,
                    "limit": kwargs["recipe_limit"],
                },
                "results": [],
            },
            "quest_reward_spell": {
                role: {
                    "summary": {
                        "total_recipe_identities": 10,
                        "known_match_count": 1,
                        "known_non_match_count": 0,
                        "unknown_count": 9,
                        "returned_count": 1,
                        "limit": kwargs["recipe_limit"],
                    },
                    "results": [],
                }
                for role in ("giver", "finisher", "objective")
            },
        },
    )

    detail = inspect_zone(connection, 10, entity_limit=1000, recipe_limit=50)

    entities = detail["world_entities"]["results"]
    assert len(entities) == 2
    assert len(entities[0]["matching_spawns"]) == 2
    assert all(spawn["zone_id"] == 10 for spawn in entities[0]["matching_spawns"])
    assert entities[0]["all_materialized_spawn_count"] == 3

    item = detail["items"]["results"][0]
    assert [path["path_kind"] for path in item["paths"]] == ["direct", "reference", "vendor"]
    assert item["paths"][0]["chance_percent"] == 25.0
    assert item["paths"][1]["reference_loot_id"] == 77
    assert item["paths"][2]["vendor_max_count"] == 3
    assert item["paths"][2]["chance_percent"] is None

    assert [row["quest_id"] for row in detail["quests"]["given"]] == [200]
    assert [row["quest_id"] for row in detail["quests"]["finished"]] == [201]
    assert [row["quest_id"] for row in detail["quests"]["objectives"]] == [202, 203]

    assert detail["vendors"][0]["creature_id"] == 10
    assert detail["vendors"][0]["items"][0]["paths"][0]["vendor_max_count"] == 3
    assert [row["recipe_id"] for row in detail["trainers"]["known"]] == [300]
    assert [row["recipe_id"] for row in detail["trainers"]["unknown_relations"]] == [301]
    assert detail["trainers"]["unknown_relations"][0]["geography_state"] == MATCH_UNKNOWN

    assert detail["recipes"]["teaching_item"]["summary"]["known_match_count"] == 1
    assert detail["coverage"]["state"] == MATCH_UNKNOWN
    assert detail["coverage"]["world_entity_unknown_geography_count"] == 1
    assert detail["coverage"]["unresolved_trainer_relation_count"] == 1

def test_zone_detail_reports_entity_projection_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    import octogamedb.zone_search as zone_search

    connection = _connection()
    payload = _world_payload()
    payload["summary"]["known_match_count"] = 3
    monkeypatch.setattr(zone_search, "query_world_entities", lambda *args, **kwargs: object())
    monkeypatch.setattr(zone_search, "world_entity_query_page_to_dict", lambda page: payload)

    detail = inspect_zone(
        connection,
        10,
        entity_limit=2,
        recipe_limit=10,
        include_recipes=False,
    )
    assert detail["world_entities"]["truncated_known_matches"] is True
    assert detail["coverage"]["world_entity_projection_truncated"] is True
    assert detail["coverage"]["negative_claim_authorized"] is False
    assert detail["recipes"]["included"] is False

def test_zone_query_json_contract_is_json_serializable() -> None:
    connection = _connection()
    payload = zone_query_page_to_dict(query_zones(connection, name_contains="forest"))
    encoded = json.dumps(payload, sort_keys=True)
    assert '"zone_id": 10' in encoded


def test_zone_cli_search_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "zone.sqlite3"
    connection = sqlite3.connect(db_path)
    _create_zone_schema(connection)
    connection.close()
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert zone_main(["--db", str(db_path), "--zone-id", "10", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["query"]["results"][0]["zone"]["zone_id"] == 10
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before

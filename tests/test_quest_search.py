from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from octogamedb import quest_cli, quest_search
from octogamedb.quest_search import (
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    query_quests,
    quest_query_page_to_dict,
    traverse_quest_progression,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE quests (
            quest_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            quest_level INTEGER,
            minimum_level INTEGER,
            race_mask INTEGER,
            class_mask INTEGER
        )
        """
    )
    connection.executemany(
        "INSERT INTO quests VALUES (?, ?, ?, ?, ?, ?)",
        (
            (1, "Alpha Expedition", 20, 15, 178, 64),
            (2, "Beta Missing Level", None, None, 0, 0),
            (3, "Gamma Follow-up", 22, 18, 0, 0),
            (4, "Delta Branch", 24, 20, 0, 0),
            (5, "Close Alternative", 19, 14, 0, 0),
        ),
    )
    return connection


def _detail(
    quest_id: int,
    *,
    giver: list[dict] | None = None,
    finisher: list[dict] | None = None,
    objectives: list[dict] | None = None,
    prerequisite_ids: list[int] | None = None,
    unresolved_prerequisites: list[dict] | None = None,
    prerequisite_complete: bool = True,
    follow_ups: list[int] | None = None,
    close_ids: list[int] | None = None,
) -> dict:
    names = {
        1: "Alpha Expedition",
        2: "Beta Missing Level",
        3: "Gamma Follow-up",
        4: "Delta Branch",
        5: "Close Alternative",
    }
    levels = {1: (20, 15), 2: (None, None), 3: (22, 18), 4: (24, 20), 5: (19, 14)}
    prerequisite_ids = prerequisite_ids or []
    unresolved_prerequisites = unresolved_prerequisites or []
    unresolved_ids = {entry["quest_id"] for entry in unresolved_prerequisites}
    materialized_ids = [
        member_id for member_id in prerequisite_ids if member_id not in unresolved_ids
    ]
    endpoints = []
    for endpoint_kind, rows in (("giver", giver or []), ("finisher", finisher or [])):
        for index, location in enumerate(rows, start=1):
            endpoints.append(
                {
                    "endpoint_kind": endpoint_kind,
                    "entity_type": "creature" if endpoint_kind == "giver" else "gameobject",
                    "entity_id": quest_id * 100 + index,
                    "entity_name": f"{endpoint_kind}-{quest_id}-{index}",
                    "resolved": True,
                    "unresolved_reason": None,
                    "locations": [] if location is None else [location],
                    "geography_resolved": location is not None,
                    "geography_unresolved_reason": (
                        None if location is not None else "no_canonical_spawns"
                    ),
                    "selection": {"source_key": "fixture"},
                }
            )
    return {
        "quest_id": quest_id,
        "name": names[quest_id],
        "identity_provenance": {"source_key": "fixture"},
        "endpoint_set": {
            "declared": True,
            "selected_member_count": len(endpoints),
            "materialized_selected_member_count": len(endpoints),
            "is_complete": True,
            "unresolved_members": [],
            "provenance": {"source_key": "fixture"},
        },
        "endpoints": endpoints,
        "progression": {
            "quest_level": levels[quest_id][0],
            "minimum_level": levels[quest_id][1],
            "race_mask": 178 if quest_id == 1 else 0,
            "class_mask": 64 if quest_id == 1 else 0,
            "prerequisite_set": {
                "semantics": "any_of",
                "declared": bool(prerequisite_ids),
                "selected_member_count": len(prerequisite_ids),
                "materialized_member_count": len(materialized_ids),
                "is_complete": prerequisite_complete,
                "members": [
                    {
                        "quest_id": member_id,
                        "name": names.get(member_id),
                        "selected_by_complete_set": True,
                        "selection": {"source_key": "fixture"},
                    }
                    for member_id in materialized_ids
                ],
                "selected_member_ids": prerequisite_ids,
                "selected_materialized_member_count": len(materialized_ids),
                "unresolved_members": unresolved_prerequisites,
            },
            "follow_ups": [
                {"quest_id": member_id, "name": names[member_id]}
                for member_id in (follow_ups or [])
            ],
            "close_set": {
                "semantics": "exclusive_group_member_set",
                "declared": bool(close_ids),
                "selected_member_count": len(close_ids or []),
                "materialized_member_count": len(close_ids or []),
                "is_complete": True,
                "members": [
                    {"quest_id": member_id, "name": names[member_id]}
                    for member_id in (close_ids or [])
                ],
                "selected_member_ids": close_ids or [],
                "selected_materialized_member_count": len(close_ids or []),
                "unresolved_members": [],
            },
            "provenance": {"quest_level": {"source_key": "fixture"}},
        },
        "objectives": {
            "declared": bool(objectives),
            "selected_member_count": len(objectives or []),
            "materialized_member_count": len(objectives or []),
            "is_complete": True,
            "objectives": objectives or [],
            "provenance": {"source_key": "fixture"},
        },
        "item_facts": {
            "required_items": [
                {
                    "item_id": 700,
                    "item_name": "Required Item",
                    "resolved": True,
                    "quantity": 4,
                    "value_status": "known",
                }
            ],
            "required_sources": [
                {
                    "item_id": 701,
                    "item_name": "Source Item",
                    "resolved": True,
                    "raw_source_count": 1,
                    "value_status": "known",
                }
            ],
            "provided_item": {
                "item_id": 702,
                "quantity": 2 if quest_id == 3 else None,
                "quantity_status": "known" if quest_id == 3 else "unknown",
            },
            "guaranteed_rewards": [
                {
                    "item_id": 703,
                    "item_name": "Guaranteed Reward",
                    "resolved": True,
                    "quantity": 1,
                    "value_status": "known",
                }
            ],
            "choice_rewards": {
                "semantics": "choose_one",
                "items": [{"item_id": 704}, {"item_id": 705}],
            },
            "objective_membership": {
                "item_ids": [700, 706],
                "objective_only_item_ids": [706],
                "equivalence_assumed": False,
            },
        },
    }


def _details() -> dict[int, dict]:
    return {
        1: _detail(
            1,
            giver=[{"zone_id": 10, "map_id": 1}],
            finisher=[{"zone_id": 20, "map_id": 2}],
            objectives=[
                {
                    "source_subtype": "U",
                    "target_kind": "creature",
                    "target_id": 800,
                    "resolved": True,
                    "locations": [{"zone_id": 30, "map_id": 3}],
                    "provenance": {"source_key": "fixture"},
                },
                {
                    "source_subtype": "O",
                    "target_kind": "gameobject",
                    "target_id": 801,
                    "resolved": True,
                    "locations": [{"zone_id": 34, "map_id": 3}],
                    "provenance": {"source_key": "fixture"},
                },
                {
                    "source_subtype": "I",
                    "target_kind": "item",
                    "target_id": 706,
                    "resolved": True,
                    "geography_origin": "none",
                    "geography_resolved": None,
                    "provenance": {"source_key": "fixture"},
                },
                {
                    "source_subtype": "U",
                    "target_kind": "creature",
                    "target_id": 9998,
                    "resolved": False,
                    "unresolved_reason": "missing_creature_identity",
                    "locations": [],
                    "provenance": {"source_key": "fixture"},
                },
                {
                    "source_subtype": "IR",
                    "target_kind": "item",
                    "target_id": 701,
                    "resolved": True,
                    "item_use_targets": {
                        "targets": [
                            {
                                "target_kind": "gameobject",
                                "target_id": 900,
                                "locations": [{"zone_id": 31, "map_id": 3}],
                            }
                        ]
                    },
                },
                {
                    "source_subtype": "A",
                    "target_kind": "area_trigger",
                    "target_id": 45,
                    "resolved": True,
                    "area_trigger": {"locations": [{"zone_id": 32, "map_id": 3}]},
                },
                {
                    "source_subtype": "Z",
                    "target_kind": "zone",
                    "target_id": 33,
                    "resolved": True,
                    "zone": {
                        "zone_id": 33,
                        "zone_name": "Direct Zone",
                        "map_id": 3,
                        "map_name": "Map",
                    },
                },
            ],
            prerequisite_ids=[2, 999],
            unresolved_prerequisites=[
                {
                    "quest_id": 999,
                    "name": None,
                    "reason": "missing_quest_identity",
                    "selection": {"source_key": "fixture"},
                }
            ],
            prerequisite_complete=False,
            follow_ups=[3, 4],
            close_ids=[1, 5],
        ),
        2: _detail(2, giver=[None]),
        3: _detail(3, prerequisite_ids=[1], follow_ups=[1]),
        4: _detail(4),
        5: _detail(5),
    }


@pytest.fixture
def query_context(monkeypatch):
    connection = _connection()
    details = _details()

    def fake_detail(_connection, quest_id):
        value = details.get(quest_id)
        return None if value is None else json.loads(json.dumps(value))

    monkeypatch.setattr(quest_search, "_quest_detail", fake_detail)
    yield connection, details
    connection.close()


def test_id_title_level_filters_and_raw_masks(query_context):
    connection, _ = query_context
    page = query_quests(
        connection,
        title_contains="alpha",
        min_quest_level=20,
        max_minimum_level=15,
        limit=10,
    )
    assert [result.quest["quest_id"] for result in page.results] == [1]
    assert page.results[0].quest["progression"]["race_mask"] == 178
    assert page.results[0].quest["progression"]["class_mask"] == 64

    unknown = query_quests(
        connection,
        quest_id=2,
        min_quest_level=1,
        include_states=(MATCH_UNKNOWN,),
        limit=10,
    )
    assert [result.quest["quest_id"] for result in unknown.results] == [2]
    assert unknown.results[0].match_state == MATCH_UNKNOWN

    non_match = query_quests(
        connection,
        quest_id=1,
        min_quest_level=30,
        include_states=(NON_MATCH_KNOWN,),
        limit=10,
    )
    assert 1 in [result.quest["quest_id"] for result in non_match.results]
    quest_one = next(result for result in non_match.results if result.quest["quest_id"] == 1)
    assert quest_one.match_state == NON_MATCH_KNOWN


def test_relation_specific_geography_and_conservative_unknown(query_context):
    connection, _ = query_context
    giver = query_quests(connection, quest_id=1, giver_zone_id=10, giver_map_id=1)
    assert [result.quest["quest_id"] for result in giver.results] == [1]

    wrong_role = query_quests(
        connection,
        quest_id=1,
        finisher_zone_id=10,
        include_states=(MATCH_UNKNOWN,),
    )
    assert [result.quest["quest_id"] for result in wrong_role.results] == [1]
    assert wrong_role.results[0].predicates[-1].reason == (
        "no_known_matching_finisher_location_negative_not_proven"
    )

    unlocated = query_quests(
        connection,
        quest_id=2,
        giver_zone_id=10,
        include_states=(MATCH_UNKNOWN,),
    )
    assert [result.quest["quest_id"] for result in unlocated.results] == [2]


def test_objective_geography_supports_multiple_source_subtypes(query_context):
    connection, _ = query_context
    for zone_id in (30, 31, 32, 33, 34):
        page = query_quests(connection, quest_id=1, objective_zone_id=zone_id, objective_map_id=3)
        assert [result.quest["quest_id"] for result in page.results] == [1]

    endpoint_only = query_quests(
        connection,
        quest_id=1,
        objective_zone_id=10,
        include_states=(MATCH_UNKNOWN,),
    )
    assert [result.quest["quest_id"] for result in endpoint_only.results] == [1]


def test_search_preserves_item_fact_distinctions_and_provenance(query_context):
    connection, _ = query_context
    result = query_quests(connection, quest_id=1).results[0].quest
    assert result["identity_provenance"]["source_key"] == "fixture"
    assert isinstance(result["item_facts"]["required_items"], list)
    assert result["item_facts"]["required_items"][0]["quantity"] == 4
    assert isinstance(result["item_facts"]["required_sources"], list)
    assert result["item_facts"]["required_sources"][0]["item_id"] == 701
    assert isinstance(result["item_facts"]["guaranteed_rewards"], list)
    assert result["item_facts"]["guaranteed_rewards"][0]["quantity"] == 1
    assert result["item_facts"]["provided_item"]["quantity_status"] == "unknown"
    known_provided = query_quests(connection, quest_id=3).results[0].quest
    assert known_provided["item_facts"]["provided_item"]["quantity"] == 2
    assert known_provided["item_facts"]["provided_item"]["quantity_status"] == "known"
    unresolved_objectives = [
        objective
        for objective in result["objectives"]["objectives"]
        if objective.get("resolved") is False
    ]
    assert unresolved_objectives[0]["target_id"] == 9998
    assert result["item_facts"]["choice_rewards"]["semantics"] == "choose_one"
    assert result["item_facts"]["objective_membership"]["objective_only_item_ids"] == [706]
    assert result["item_facts"]["objective_membership"]["equivalence_assumed"] is False


def test_prerequisite_traversal_keeps_any_of_unresolved_and_close_separate(query_context):
    connection, _ = query_context
    traversal = traverse_quest_progression(
        connection, 1, direction="prerequisite", max_depth=5, max_nodes=20
    )
    assert traversal is not None
    assert traversal["depth_is_chain_step"] is False
    assert traversal["close_sets_traversed"] is False
    assert traversal["unresolved_target_ids"] == [999]
    assert traversal["incomplete_quest_ids"] == [1]
    assert traversal["ambiguous"] is True
    assert {(edge["to_quest_id"], edge["relation_semantics"]) for edge in traversal["edges"]} >= {
        (2, "any_of_prerequisite_member"),
        (999, "any_of_prerequisite_member"),
    }
    assert 5 not in {edge["to_quest_id"] for edge in traversal["edges"]}


def test_follow_up_traversal_is_reverse_derived_branching_and_cycle_safe(query_context):
    connection, _ = query_context
    traversal = traverse_quest_progression(
        connection, 1, direction="follow_up", max_depth=5, max_nodes=20
    )
    assert traversal is not None
    assert traversal["ambiguous_quest_ids"] == [1]
    assert traversal["cycle_edge_count"] == 1
    assert any(edge["cycle"] and edge["to_quest_id"] == 1 for edge in traversal["edges"])
    assert all(
        edge["relation_semantics"] == "derived_reverse_of_any_of_prerequisite_member"
        for edge in traversal["edges"]
    )


def test_traversal_node_bound_is_explicit(query_context):
    connection, _ = query_context
    traversal = traverse_quest_progression(
        connection, 1, direction="follow_up", max_depth=5, max_nodes=2
    )
    assert traversal is not None
    assert len(traversal["nodes"]) == 2
    assert traversal["truncated"] is True
    assert traversal["ambiguous"] is True
    json.dumps(traversal, sort_keys=True)


def test_deterministic_ordering_limit_and_json(query_context):
    connection, _ = query_context
    first = query_quests(connection, sort_by="name", limit=3)
    second = query_quests(connection, sort_by="name", limit=3)
    assert quest_query_page_to_dict(first) == quest_query_page_to_dict(second)
    assert first.summary.total_quest_identities == 5
    assert first.summary.returned_count == 3
    json.dumps(quest_query_page_to_dict(first), sort_keys=True)


def _evidence_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
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
            value_json TEXT NOT NULL
        );
        CREATE TABLE canonical_selections (
            observation_group_id INTEGER PRIMARY KEY,
            observation_id INTEGER NOT NULL,
            selection_policy TEXT
        );
        CREATE TABLE maps (map_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE zones (zone_id INTEGER PRIMARY KEY, map_id INTEGER, name TEXT NOT NULL);
        CREATE TABLE creatures (creature_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE gameobjects (gameobject_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE creature_spawns (
            spawn_id INTEGER PRIMARY KEY,
            creature_id INTEGER NOT NULL,
            map_id INTEGER,
            zone_id INTEGER,
            coordinate_space TEXT NOT NULL,
            x REAL, y REAL, z REAL
        );
        CREATE TABLE gameobject_spawns (
            spawn_id INTEGER PRIMARY KEY,
            gameobject_id INTEGER NOT NULL,
            map_id INTEGER,
            zone_id INTEGER,
            coordinate_space TEXT NOT NULL,
            x REAL, y REAL, z REAL
        );
        """
    )
    connection.execute(
        "INSERT INTO data_sources VALUES (1, 'pfquest-turtle', 'Turtle', 'fixture')"
    )


def _selected(
    connection: sqlite3.Connection,
    *,
    group_id: int,
    observation_id: int,
    quest_id: int,
    fact_key: str,
    instance: str,
    value: object,
) -> None:
    connection.execute(
        "INSERT INTO observation_groups VALUES (?, 'quest', ?, ?, ?)",
        (group_id, str(quest_id), fact_key, instance),
    )
    connection.execute(
        "INSERT INTO source_observations VALUES (?, ?, 1, 'fixture-v1', ?)",
        (observation_id, group_id, json.dumps(value, sort_keys=True)),
    )
    connection.execute(
        "INSERT INTO canonical_selections VALUES (?, ?, 'fixture-policy')",
        (group_id, observation_id),
    )


def test_enrichment_surfaces_selected_unresolved_endpoint_and_progression(monkeypatch):
    connection = _connection()
    _evidence_schema(connection)
    base = _detail(1, prerequisite_ids=[2], prerequisite_complete=False)
    base["endpoints"] = []
    base["progression"]["prerequisite_set"]["selected_member_count"] = 2
    base["progression"]["prerequisite_set"]["materialized_member_count"] = 1

    monkeypatch.setattr(
        quest_search,
        "quest_by_id",
        lambda _connection, quest_id: base if quest_id == 1 else None,
    )
    _selected(
        connection,
        group_id=1,
        observation_id=1,
        quest_id=1,
        fact_key="endpoint",
        instance="giver:creature:9999",
        value={
            "target": {"kind": "creature", "key": 9999},
            "attributes": {"endpoint_kind": "giver"},
        },
    )
    _selected(
        connection,
        group_id=2,
        observation_id=2,
        quest_id=1,
        fact_key="quest_endpoint_set",
        instance="",
        value=[{"endpoint_kind": "giver", "target_kind": "creature", "target_id": 9999}],
    )
    _selected(
        connection,
        group_id=3,
        observation_id=3,
        quest_id=1,
        fact_key="quest_prerequisite_set",
        instance="",
        value=[2, 999],
    )
    _selected(
        connection,
        group_id=4,
        observation_id=4,
        quest_id=1,
        fact_key="prerequisite",
        instance="2",
        value={"target": {"kind": "quest", "key": 2}, "attributes": {"requirement_mode": "any_of"}},
    )
    _selected(
        connection,
        group_id=5,
        observation_id=5,
        quest_id=1,
        fact_key="prerequisite",
        instance="999",
        value={
            "target": {"kind": "quest", "key": 999},
            "attributes": {"requirement_mode": "any_of"},
        },
    )
    _selected(
        connection,
        group_id=6,
        observation_id=6,
        quest_id=1,
        fact_key="name",
        instance="",
        value="Alpha Expedition",
    )

    detail = quest_search._quest_detail(connection, 1)
    assert detail is not None
    endpoint = detail["endpoints"][0]
    assert endpoint["entity_id"] == 9999
    assert endpoint["resolved"] is False
    assert endpoint["unresolved_reason"] == "missing_creature_identity"
    assert endpoint["selection"]["source_key"] == "pfquest-turtle"
    assert detail["endpoint_set"]["is_complete"] is False

    prerequisite = detail["progression"]["prerequisite_set"]
    assert prerequisite["selected_member_ids"] == [2, 999]
    assert prerequisite["selected_materialized_member_count"] == 1
    assert [member["quest_id"] for member in prerequisite["unresolved_members"]] == [999]
    assert prerequisite["unresolved_members"][0]["reason"] == "missing_quest_identity"
    connection.close()


def test_cli_database_open_is_read_only(tmp_path: Path):
    db_path = tmp_path / "readonly.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE marker(value INTEGER)")
    connection.commit()
    connection.close()

    readonly = quest_cli._open_readonly_database(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute("INSERT INTO marker(value) VALUES (1)")
    finally:
        readonly.close()


def test_cli_json_surface(monkeypatch, capsys):
    connection = _connection()
    details = _details()
    monkeypatch.setattr(
        quest_search,
        "_quest_detail",
        lambda _connection, quest_id: json.loads(json.dumps(details[quest_id])),
    )
    page = query_quests(connection, quest_id=1)
    monkeypatch.setattr(quest_cli, "_search", lambda args: page)
    assert quest_cli.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["quest"]["quest_id"] == 1
    assert payload["results"][0]["match_state"] == MATCH_KNOWN
    connection.close()

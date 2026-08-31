from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from octogamedb.world_entity_cli import main as world_entity_main
from octogamedb.world_entity_search import (
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    QUERY_STATES,
    query_world_entities,
    world_entity_query_page_to_dict,
)


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY);
        CREATE TABLE maps (map_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE zones (zone_id INTEGER PRIMARY KEY, map_id INTEGER, name TEXT NOT NULL);
        CREATE TABLE creatures (
            creature_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            level_min INTEGER,
            level_max INTEGER,
            faction TEXT,
            classification TEXT,
            creature_type TEXT,
            npc_flags INTEGER
        );
        CREATE TABLE gameobjects (
            gameobject_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            object_type TEXT
        );
        CREATE TABLE creature_spawns (
            spawn_id INTEGER PRIMARY KEY,
            spawn_key TEXT UNIQUE NOT NULL,
            creature_id INTEGER NOT NULL,
            map_id INTEGER,
            zone_id INTEGER,
            coordinate_space TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            z REAL,
            orientation REAL,
            respawn_seconds INTEGER
        );
        CREATE TABLE gameobject_spawns (
            spawn_id INTEGER PRIMARY KEY,
            spawn_key TEXT UNIQUE NOT NULL,
            gameobject_id INTEGER NOT NULL,
            map_id INTEGER,
            zone_id INTEGER,
            coordinate_space TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            z REAL,
            orientation REAL,
            respawn_seconds INTEGER
        );
        CREATE TABLE items (item_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE creature_loot (
            creature_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            chance_percent REAL NOT NULL,
            PRIMARY KEY (creature_id, item_id)
        );
        CREATE TABLE gameobject_loot (
            gameobject_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            chance_percent REAL NOT NULL,
            PRIMARY KEY (gameobject_id, item_id)
        );
        CREATE TABLE item_reference_loot (
            item_id INTEGER NOT NULL,
            reference_loot_id INTEGER NOT NULL,
            chance_percent REAL NOT NULL,
            PRIMARY KEY (item_id, reference_loot_id)
        );
        CREATE TABLE reference_loot_creatures (
            reference_loot_id INTEGER NOT NULL,
            creature_id INTEGER NOT NULL,
            PRIMARY KEY (reference_loot_id, creature_id)
        );
        CREATE TABLE reference_loot_gameobjects (
            reference_loot_id INTEGER NOT NULL,
            gameobject_id INTEGER NOT NULL,
            PRIMARY KEY (reference_loot_id, gameobject_id)
        );
        CREATE TABLE vendor_items (
            vendor_creature_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            PRIMARY KEY (vendor_creature_id, item_id)
        );
        CREATE TABLE quests (quest_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE quest_creature_endpoints (
            quest_id INTEGER NOT NULL,
            endpoint_kind TEXT NOT NULL,
            creature_id INTEGER NOT NULL,
            PRIMARY KEY (quest_id, endpoint_kind, creature_id)
        );
        CREATE TABLE quest_gameobject_endpoints (
            quest_id INTEGER NOT NULL,
            endpoint_kind TEXT NOT NULL,
            gameobject_id INTEGER NOT NULL,
            PRIMARY KEY (quest_id, endpoint_kind, gameobject_id)
        );
        CREATE TABLE quest_creature_objectives (
            quest_id INTEGER NOT NULL,
            creature_id INTEGER NOT NULL,
            PRIMARY KEY (quest_id, creature_id)
        );
        CREATE TABLE quest_gameobject_objectives (
            quest_id INTEGER NOT NULL,
            gameobject_id INTEGER NOT NULL,
            PRIMARY KEY (quest_id, gameobject_id)
        );
        CREATE TABLE spells (
            spell_id INTEGER PRIMARY KEY,
            name TEXT,
            rank_text TEXT
        );
        CREATE TABLE skill_lines (skill_line_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE recipes (
            recipe_id INTEGER PRIMARY KEY,
            crafting_spell_id INTEGER NOT NULL
        );
        CREATE TABLE recipe_trainer_sources (
            recipe_id INTEGER NOT NULL,
            trainer_kind TEXT NOT NULL,
            native_trainer_entry INTEGER NOT NULL,
            creature_id INTEGER,
            trainer_template_id INTEGER,
            acquisition_spell_id INTEGER NOT NULL,
            learning_proof_kind TEXT NOT NULL,
            learn_effect_index INTEGER,
            server_learn_active INTEGER,
            spell_cost INTEGER NOT NULL,
            required_skill_line_id INTEGER,
            required_skill_value INTEGER NOT NULL,
            required_character_level INTEGER NOT NULL,
            PRIMARY KEY (recipe_id, trainer_kind, native_trainer_entry, acquisition_spell_id)
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


def _seed(connection: sqlite3.Connection) -> None:
    connection.execute("INSERT INTO schema_migrations(version) VALUES (14)")
    connection.executemany(
        "INSERT INTO maps(map_id, name) VALUES (?, ?)",
        ((1, "Eastern"), (2, "Western")),
    )
    connection.executemany(
        "INSERT INTO zones(zone_id, map_id, name) VALUES (?, ?, ?)",
        ((10, 1, "Green Vale"), (20, 2, "Red Vale"), (30, None, "Unknown Map Zone")),
    )
    connection.executemany(
        """
        INSERT INTO creatures(
            creature_id, name, level_min, level_max, faction,
            classification, creature_type, npc_flags
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (100, "Alpha Wolf", 10, 12, "H", "normal", "Beast", 0),
            (101, "Vendor Trainer", 20, 20, "A", "normal", "Humanoid", 3),
            (102, "Known Empty", 5, 5, None, None, None, None),
            (103, "Unknown Wanderer", 5, 5, None, None, None, None),
            (104, "Protected Scout", 8, 8, None, None, None, None),
            (105, "Mapless Scout", 8, 8, None, None, None, None),
        ),
    )
    connection.executemany(
        "INSERT INTO gameobjects(gameobject_id, name, object_type) VALUES (?, ?, ?)",
        ((200, "Ancient Cache", "chest"), (201, "Unlocated Cache", "chest")),
    )
    connection.executemany(
        """
        INSERT INTO creature_spawns(
            spawn_id, spawn_key, creature_id, map_id, zone_id,
            coordinate_space, x, y, z, orientation, respawn_seconds
        ) VALUES (?, ?, ?, ?, ?, 'zone_percent', ?, ?, NULL, NULL, ?)
        """,
        (
            (1, "creature:100:a", 100, None, 10, 10.0, 20.0, 60),
            (2, "creature:100:b", 100, None, 20, 30.0, 40.0, 120),
            (3, "creature:101:a", 101, None, 10, 50.0, 60.0, 300),
            (4, "creature:104:managed", 104, None, 10, 15.0, 15.0, 60),
            (5, "creature:104:protected", 104, None, 20, 25.0, 25.0, 60),
            (6, "creature:105:a", 105, None, 30, 35.0, 35.0, 60),
        ),
    )
    connection.execute(
        """
        INSERT INTO gameobject_spawns(
            spawn_id, spawn_key, gameobject_id, map_id, zone_id,
            coordinate_space, x, y, z, orientation, respawn_seconds
        ) VALUES (20, 'gameobject:200:a', 200, NULL, 20,
                  'zone_percent', 70, 80, NULL, NULL, 600)
        """
    )
    connection.executemany(
        "INSERT INTO items(item_id, name) VALUES (?, ?)",
        ((1, "Wolf Fang"), (2, "Reference Relic"), (3, "Trainer Supply")),
    )
    connection.execute(
        "INSERT INTO creature_loot(creature_id, item_id, chance_percent) VALUES (100, 1, 12.5)"
    )
    connection.execute(
        "INSERT INTO gameobject_loot(gameobject_id, item_id, chance_percent) VALUES (200, 1, 25.0)"
    )
    connection.execute(
        "INSERT INTO item_reference_loot(item_id, reference_loot_id, chance_percent) "
        "VALUES (2, 9001, 7.5)"
    )
    connection.execute(
        "INSERT INTO reference_loot_creatures(reference_loot_id, creature_id) VALUES (9001, 100)"
    )
    connection.execute(
        "INSERT INTO reference_loot_gameobjects(reference_loot_id, gameobject_id) "
        "VALUES (9001, 200)"
    )
    connection.execute(
        "INSERT INTO vendor_items(vendor_creature_id, item_id) VALUES (101, 3)"
    )

    connection.executemany(
        "INSERT INTO quests(quest_id, name) VALUES (?, ?)",
        (
            (500, "Wolf Giver"),
            (501, "Wolf Finisher"),
            (502, "Wolf Objective"),
            (503, "Cache Objective"),
        ),
    )
    connection.execute(
        "INSERT INTO quest_creature_endpoints(quest_id, endpoint_kind, creature_id) "
        "VALUES (500, 'giver', 100)"
    )
    connection.execute(
        "INSERT INTO quest_creature_endpoints(quest_id, endpoint_kind, creature_id) "
        "VALUES (501, 'finisher', 100)"
    )
    connection.execute(
        "INSERT INTO quest_creature_objectives(quest_id, creature_id) VALUES (502, 100)"
    )
    connection.execute(
        "INSERT INTO quest_gameobject_objectives(quest_id, gameobject_id) VALUES (503, 200)"
    )

    connection.executemany(
        "INSERT INTO spells(spell_id, name, rank_text) VALUES (?, ?, NULL)",
        (
            (700, "Direct Recipe"),
            (701, "Template Recipe"),
            (702, "Unresolved Recipe"),
            (1700, "Learn Direct"),
            (1701, "Learn Template"),
            (1702, "Learn Unresolved"),
        ),
    )
    connection.executemany(
        "INSERT INTO recipes(recipe_id, crafting_spell_id) VALUES (?, ?)",
        ((700, 700), (701, 701), (702, 702)),
    )
    connection.execute("INSERT INTO skill_lines(skill_line_id, name) VALUES (164, 'Blacksmithing')")
    connection.executemany(
        """
        INSERT INTO recipe_trainer_sources(
            recipe_id, trainer_kind, native_trainer_entry, creature_id,
            trainer_template_id, acquisition_spell_id, learning_proof_kind,
            learn_effect_index, server_learn_active, spell_cost,
            required_skill_line_id, required_skill_value, required_character_level
        ) VALUES (?, ?, 101, ?, ?, ?, 'octo_dbc_learn_spell', 0, 1, ?, 164, ?, ?)
        """,
        (
            (700, "direct", 101, None, 1700, 100, 50, 20),
            (701, "template", 101, 77, 1701, 200, 75, 25),
            (702, "direct", None, None, 1702, 300, 100, 30),
        ),
    )

    connection.executemany(
        "INSERT INTO data_sources(id, source_key, display_name, source_kind) VALUES (?, ?, ?, ?)",
        (
            (1, "pfquest-turtle", "Turtle", "fixture"),
            (2, "external-world", "External", "fixture"),
            (3, "octo-dbc", "Octo DBC", "fixture"),
        ),
    )
    next_id = 1

    def observe(
        subject_kind: str,
        subject_key: int | str,
        fact_key: str,
        value: object,
        *,
        instance_key: str = "",
        source_id: int = 1,
        record_type: str = "fixture",
    ) -> None:
        nonlocal next_id
        observation_id = next_id
        next_id += 1
        connection.execute(
            """
            INSERT INTO observation_groups(
                id, subject_kind, subject_key, fact_key, fact_instance_key
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (observation_id, subject_kind, str(subject_key), fact_key, instance_key),
        )
        connection.execute(
            """
            INSERT INTO source_observations(
                id, observation_group_id, source_id, source_revision,
                source_record_type, raw_identifier, value_json, authority_tier
            ) VALUES (?, ?, ?, 'fixture-r1', ?, ?, ?, 1)
            """,
            (
                observation_id,
                observation_id,
                source_id,
                record_type,
                instance_key or str(subject_key),
                json.dumps(value, sort_keys=True),
            ),
        )
        connection.execute(
            """
            INSERT INTO canonical_selections(
                observation_group_id, observation_id, selection_policy, selection_reason
            ) VALUES (?, ?, 'fixture-selection', 'Fixture selected evidence.')
            """,
            (observation_id, observation_id),
        )

    for creature_id in (100, 101, 102, 103, 104, 105):
        name = connection.execute(
            "SELECT name FROM creatures WHERE creature_id = ?", (creature_id,)
        ).fetchone()[0]
        observe("creature", creature_id, "name", name)
        observe("creature", creature_id, "world_presence", True)
    for gameobject_id in (200, 201):
        name = connection.execute(
            "SELECT name FROM gameobjects WHERE gameobject_id = ?", (gameobject_id,)
        ).fetchone()[0]
        observe("gameobject", gameobject_id, "name", name)
        observe("gameobject", gameobject_id, "world_presence", True)

    def set_payload(*spawn_keys: str) -> list[dict[str, object]]:
        return [{"spawn_key": key} for key in spawn_keys]

    observe("creature", 100, "spawn_set", set_payload("creature:100:a", "creature:100:b"))
    observe(
        "creature",
        101,
        "spawn_set",
        set_payload("creature:101:a", "creature:101:a"),
    )
    observe("creature", 102, "spawn_set", set_payload())
    observe("creature", 104, "spawn_set", set_payload("creature:104:managed"))
    observe("creature", 105, "spawn_set", set_payload("creature:105:a"))
    observe("gameobject", 200, "spawn_set", set_payload("gameobject:200:a"))

    for kind, spawn_key, source_id in (
        ("creature", "creature:100:a", 1),
        ("creature", "creature:100:b", 1),
        ("creature", "creature:101:a", 1),
        ("creature", "creature:104:managed", 1),
        ("creature", "creature:104:protected", 2),
        ("creature", "creature:105:a", 1),
        ("gameobject", "gameobject:200:a", 1),
    ):
        observe(
            f"{kind}_spawn",
            spawn_key,
            "position",
            {"spawn_key": spawn_key},
            source_id=source_id,
            record_type="spawn",
        )

    observe(
        "item",
        1,
        "loot_source",
        {"target": {"kind": "creature", "key": 100}},
        instance_key="creature:100",
    )
    observe(
        "item",
        1,
        "loot_source",
        {"target": {"kind": "gameobject", "key": 200}},
        instance_key="gameobject:200",
    )
    observe(
        "item",
        2,
        "loot_reference",
        {"target": {"kind": "loot_reference", "key": 9001}},
        instance_key="reference:9001",
    )
    observe(
        "loot_reference",
        9001,
        "loot_source_member",
        {"target": {"kind": "creature", "key": 100}},
        instance_key="creature:100",
    )
    observe(
        "loot_reference",
        9001,
        "loot_source_member",
        {"target": {"kind": "gameobject", "key": 200}},
        instance_key="gameobject:200",
    )
    observe(
        "item",
        3,
        "vendor_source",
        {"target": {"kind": "creature", "key": 101}, "attributes": {"max_count": 2}},
        instance_key="creature:101",
    )

    for quest_id, role in ((500, "giver"), (501, "finisher")):
        observe(
            "quest",
            quest_id,
            "endpoint",
            {
                "target": {"kind": "creature", "key": 100},
                "attributes": {"endpoint_kind": role},
            },
            instance_key=f"{role}:creature:100",
        )
    observe(
        "quest",
        599,
        "endpoint",
        {
            "target": {"kind": "creature", "key": 100},
            "attributes": {"endpoint_kind": "giver"},
        },
        instance_key="giver:creature:100",
    )
    observe(
        "quest",
        502,
        "objective_creature",
        {
            "target": {"kind": "creature", "key": 100},
            "attributes": {"source_subtype": "U"},
        },
        instance_key="100",
    )
    observe(
        "quest",
        503,
        "objective_gameobject",
        {
            "target": {"kind": "gameobject", "key": 200},
            "attributes": {"source_subtype": "O"},
        },
        instance_key="200",
    )

    for recipe_id, kind, template_id, spell_id in (
        (700, "direct", None, 1700),
        (701, "template", 77, 1701),
        (702, "direct", None, 1702),
    ):
        observe(
            "recipe",
            recipe_id,
            "trainer_source",
            {
                "target": {"kind": "creature", "key": 101},
                "attributes": {
                    "trainer_kind": kind,
                    "trainer_template_id": template_id,
                    "acquisition_spell_id": spell_id,
                },
            },
            instance_key=(
                f"{kind}:creature:101:template:{template_id or 0}:spell:{spell_id}"
            ),
            source_id=3,
        )
    connection.commit()


def _memory_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    _create_schema(connection)
    _seed(connection)
    return connection


def _file_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        _create_schema(connection)
        _seed(connection)
    finally:
        connection.close()


def _result(page, kind: str, entity_id: int):
    return next(
        result
        for result in page.results
        if result.entity["entity_kind"] == kind and result.entity["entity_id"] == entity_id
    )


def test_creature_and_gameobject_identity_name_queries():
    connection = _memory_connection()
    try:
        creature = query_world_entities(
            connection,
            entity_kind="creature",
            entity_id=100,
            name_contains="wolf",
        )
        gameobject = query_world_entities(connection, name_contains="cache", sort_by="name")
    finally:
        connection.close()

    assert [result.entity["entity_id"] for result in creature.results] == [100]
    assert creature.results[0].match_state == MATCH_KNOWN
    assert [result.entity["entity_id"] for result in gameobject.results] == [200, 201]
    assert all(result.entity["entity_kind"] == "gameobject" for result in gameobject.results)


def test_multiple_spawns_remain_independent_with_selected_provenance():
    connection = _memory_connection()
    try:
        result = query_world_entities(
            connection, entity_kind="creature", entity_id=100
        ).results[0]
    finally:
        connection.close()

    assert [spawn["spawn_key"] for spawn in result.entity["spawns"]] == [
        "creature:100:a",
        "creature:100:b",
    ]
    assert [spawn["zone_id"] for spawn in result.entity["spawns"]] == [10, 20]
    assert result.entity["spawns"][0]["provenance"]["position"]["source_key"] == "pfquest-turtle"
    assert result.entity["spawn_set"]["is_complete_for_canonical_view"] is True
    assert result.entity["spawn_set"]["provenance"]["selection_policy"] == "fixture-selection"


def test_duplicate_source_spawn_members_are_deduplicated_only_for_coverage_identity():
    connection = _memory_connection()
    try:
        positive = query_world_entities(
            connection, entity_kind="creature", entity_id=101, zone_id=10
        )
        negative = query_world_entities(
            connection,
            entity_kind="creature",
            entity_id=101,
            zone_id=999,
            include_states=QUERY_STATES,
        )
    finally:
        connection.close()

    assert positive.results[0].match_state == MATCH_KNOWN
    result = _result(negative, "creature", 101)
    assert result.match_state == NON_MATCH_KNOWN
    coverage = result.entity["spawn_set"]
    assert coverage["selected_member_count"] == 2
    assert coverage["selected_distinct_member_count"] == 1
    assert coverage["duplicate_source_member_count"] == 1
    assert coverage["duplicate_source_spawn_keys"] == ["creature:101:a"]
    assert coverage["materialized_selected_member_count"] == 1
    assert coverage["is_complete_for_canonical_view"] is True


def test_geography_positive_complete_negative_and_conservative_unknown():
    connection = _memory_connection()
    try:
        positive = query_world_entities(
            connection, entity_kind="creature", entity_id=100, zone_id=10
        )
        complete_negative = query_world_entities(
            connection,
            entity_kind="creature",
            entity_id=100,
            zone_id=999,
            include_states=QUERY_STATES,
        )
        no_complete_set = query_world_entities(
            connection,
            entity_kind="creature",
            entity_id=103,
            zone_id=10,
            include_states=QUERY_STATES,
        )
        protected_extra = query_world_entities(
            connection,
            entity_kind="creature",
            entity_id=104,
            zone_id=999,
            include_states=QUERY_STATES,
        )
        unresolved_map = query_world_entities(
            connection,
            entity_kind="creature",
            entity_id=105,
            map_id=1,
            include_states=QUERY_STATES,
        )
        selected_empty = query_world_entities(
            connection,
            entity_kind="creature",
            entity_id=102,
            zone_id=10,
            include_states=QUERY_STATES,
        )
    finally:
        connection.close()

    assert positive.results[0].match_state == MATCH_KNOWN
    assert _result(complete_negative, "creature", 100).match_state == NON_MATCH_KNOWN
    assert _result(no_complete_set, "creature", 103).match_state == MATCH_UNKNOWN
    protected = _result(protected_extra, "creature", 104)
    assert protected.match_state == MATCH_UNKNOWN
    assert protected.entity["spawn_set"]["extra_materialized_spawns"] == [
        "creature:104:protected"
    ]
    assert _result(unresolved_map, "creature", 105).match_state == MATCH_UNKNOWN
    assert _result(selected_empty, "creature", 102).match_state == NON_MATCH_KNOWN


def test_direct_reference_and_vendor_item_roles_preserve_path_semantics():
    connection = _memory_connection()
    try:
        wolf = query_world_entities(
            connection, entity_kind="creature", entity_id=100
        ).results[0].entity
        vendor = query_world_entities(
            connection, entity_kind="creature", entity_id=101
        ).results[0].entity
    finally:
        connection.close()

    wolf_items = {item["item_id"]: item for item in wolf["roles"]["item_acquisition"]}
    direct = wolf_items[1]["acquisition_paths"][0]
    reference = wolf_items[2]["acquisition_paths"][0]
    assert direct["path_kind"] == "direct"
    assert direct["chance_percent"] == 12.5
    assert reference["path_kind"] == "reference"
    assert reference["reference_loot_id"] == 9001
    assert reference["chance_percent"] == 7.5
    assert reference["reference_membership_provenance"] is not None

    vendor_item = vendor["roles"]["item_acquisition"][0]
    vendor_path = vendor_item["acquisition_paths"][0]
    assert vendor_path["path_kind"] == "vendor"
    assert vendor_path["chance_percent"] is None
    assert vendor_path["vendor_max_count"] == 2
    assert vendor["roles"]["summary"]["is_vendor"] is True


def test_quest_roles_are_separate_and_selected_unmaterialized_relation_is_visible():
    connection = _memory_connection()
    try:
        wolf = query_world_entities(
            connection, entity_kind="creature", entity_id=100
        ).results[0].entity
        cache = query_world_entities(
            connection, entity_kind="gameobject", entity_id=200
        ).results[0].entity
    finally:
        connection.close()

    roles = {(row["quest_id"], row["role"]): row for row in wolf["roles"]["quests"]}
    assert (500, "giver") in roles
    assert (501, "finisher") in roles
    assert (502, "objective") in roles
    assert roles[(500, "giver")]["relation_materialized"] is True
    assert roles[(599, "giver")]["quest_resolved"] is False
    assert roles[(599, "giver")]["relation_materialized"] is False
    assert roles[(599, "giver")]["provenance"] is not None

    cache_roles = cache["roles"]["quests"]
    assert [(row["quest_id"], row["role"], row["objective_kind"]) for row in cache_roles] == [
        (503, "objective", "gameobject")
    ]


def test_trainer_direct_template_and_unresolved_rows_remain_distinct():
    connection = _memory_connection()
    try:
        entity = query_world_entities(
            connection, entity_kind="creature", entity_id=101
        ).results[0].entity
    finally:
        connection.close()

    trainers = entity["roles"]["trainers"]
    assert [(row["recipe_id"], row["trainer_kind"]) for row in trainers] == [
        (700, "direct"),
        (701, "template"),
        (702, "direct"),
    ]
    assert trainers[0]["trainer_template_id"] is None
    assert trainers[1]["trainer_template_id"] == 77
    assert trainers[2]["resolved"] is False
    assert trainers[2]["native_trainer_entry"] == 101
    assert all(row["recipe_detail_owner"] == "P7-T04" for row in trainers)
    assert entity["roles"]["summary"]["is_trainer"] is True


def test_unlocated_entity_stays_visible_without_fabricated_spawn():
    connection = _memory_connection()
    try:
        entity = query_world_entities(
            connection, entity_kind="gameobject", entity_id=201
        ).results[0].entity
    finally:
        connection.close()

    assert entity["spawns"] == []
    assert entity["spawn_set"]["declared"] is False
    assert entity["world_presence"]["selected_value"] is True


def test_sort_limit_and_json_are_deterministic():
    connection = _memory_connection()
    try:
        first = query_world_entities(connection, sort_by="name", limit=3)
        second = query_world_entities(connection, sort_by="name", limit=3)
    finally:
        connection.close()

    first_payload = world_entity_query_page_to_dict(first)
    second_payload = world_entity_query_page_to_dict(second)
    assert first_payload == second_payload
    assert first.summary.returned_count == 3
    assert [result.entity["name"] for result in first.results] == [
        "Alpha Wolf",
        "Ancient Cache",
        "Known Empty",
    ]
    json.dumps(first_payload, sort_keys=True)


def test_cli_opens_database_read_only_and_preserves_bytes(tmp_path: Path, capsys):
    db_path = tmp_path / "world.sqlite3"
    _file_database(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert world_entity_main(
        ["--db", str(db_path), "--kind", "creature", "--entity-id", "100", "--json"]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert output["results"][0]["entity"]["entity_id"] == 100
    assert before == after

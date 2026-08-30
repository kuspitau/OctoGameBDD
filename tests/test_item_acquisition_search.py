from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from octogamedb.item_acquisition_cli import main as item_acquisition_main
from octogamedb.item_acquisition_search import (
    ACQUISITION_NOT_FILTERED,
    item_acquisition_page_to_dict,
    query_item_acquisitions,
)
from octogamedb.item_search import MATCH_KNOWN, MATCH_UNKNOWN, NON_MATCH_KNOWN, QUERY_STATES


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY);
        CREATE TABLE items (item_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE item_templates (
            item_id INTEGER PRIMARY KEY,
            class_id INTEGER NOT NULL,
            subclass_id INTEGER NOT NULL,
            quality INTEGER NOT NULL,
            inventory_type INTEGER NOT NULL,
            item_level INTEGER NOT NULL,
            required_level INTEGER NOT NULL,
            allowable_class_mask INTEGER NOT NULL,
            allowable_race_mask INTEGER NOT NULL,
            required_skill_id INTEGER NOT NULL,
            required_skill_rank INTEGER NOT NULL,
            required_spell_id INTEGER NOT NULL,
            required_reputation_faction_id INTEGER NOT NULL,
            required_reputation_rank INTEGER NOT NULL,
            armor INTEGER NOT NULL,
            holy_resistance INTEGER NOT NULL,
            fire_resistance INTEGER NOT NULL,
            nature_resistance INTEGER NOT NULL,
            frost_resistance INTEGER NOT NULL,
            shadow_resistance INTEGER NOT NULL,
            arcane_resistance INTEGER NOT NULL,
            max_durability INTEGER NOT NULL
        );
        CREATE TABLE item_stat_modifiers (
            item_id INTEGER NOT NULL,
            slot_index INTEGER NOT NULL,
            stat_type INTEGER NOT NULL,
            stat_value INTEGER NOT NULL,
            PRIMARY KEY (item_id, slot_index)
        );

        CREATE TABLE maps (map_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE zones (
            zone_id INTEGER PRIMARY KEY,
            map_id INTEGER,
            name TEXT NOT NULL
        );
        CREATE TABLE creatures (creature_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE gameobjects (gameobject_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE creature_spawns (
            spawn_key TEXT PRIMARY KEY,
            creature_id INTEGER NOT NULL,
            zone_id INTEGER,
            map_id INTEGER,
            coordinate_space TEXT NOT NULL,
            x REAL,
            y REAL,
            z REAL,
            orientation REAL,
            respawn_seconds INTEGER
        );
        CREATE TABLE gameobject_spawns (
            spawn_key TEXT PRIMARY KEY,
            gameobject_id INTEGER NOT NULL,
            zone_id INTEGER,
            map_id INTEGER,
            coordinate_space TEXT NOT NULL,
            x REAL,
            y REAL,
            z REAL,
            orientation REAL,
            respawn_seconds INTEGER
        );
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
            max_count INTEGER NOT NULL,
            PRIMARY KEY (vendor_creature_id, item_id)
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
            value_json TEXT NOT NULL
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
        "INSERT INTO items(item_id, name) VALUES (?, ?)",
        (
            (1, "Known Relic"),
            (2, "Wrong Quality"),
            (3, "Unknown Template"),
            (4, "Unlocated Vendor Item"),
            (5, "No Known Source"),
        ),
    )
    template_rows = (
        (1, 4, 2, 3, 5, 40, 30, 120, 80),
        (2, 4, 2, 2, 5, 40, 30, 120, 80),
        (4, 4, 2, 3, 5, 35, 25, 80, 60),
        (5, 4, 2, 3, 5, 30, 20, 60, 40),
    )
    connection.executemany(
        """
        INSERT INTO item_templates(
            item_id, class_id, subclass_id, quality, inventory_type,
            item_level, required_level,
            allowable_class_mask, allowable_race_mask,
            required_skill_id, required_skill_rank, required_spell_id,
            required_reputation_faction_id, required_reputation_rank,
            armor, holy_resistance, fire_resistance, nature_resistance,
            frost_resistance, shadow_resistance, arcane_resistance,
            max_durability
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, -1, -1, 0, 0, 0, 0, 0, ?, 0, 0, 0, 0, 0, 0, ?)
        """,
        template_rows,
    )
    connection.executemany(
        "INSERT INTO item_stat_modifiers(item_id, slot_index, stat_type, stat_value) "
        "VALUES (?, ?, ?, ?)",
        ((1, 0, 3, 12), (1, 1, 7, 8), (2, 0, 3, 12)),
    )

    connection.executemany(
        "INSERT INTO maps(map_id, name) VALUES (?, ?)",
        ((1, "Map A"), (2, "Map B")),
    )
    connection.executemany(
        "INSERT INTO zones(zone_id, map_id, name) VALUES (?, ?, ?)",
        ((10, 1, "Zone A"), (20, 2, "Zone B")),
    )
    connection.executemany(
        "INSERT INTO creatures(creature_id, name) VALUES (?, ?)",
        ((100, "Wolf"), (101, "Vendor"), (102, "Unlocated Vendor")),
    )
    connection.execute("INSERT INTO gameobjects(gameobject_id, name) VALUES (200, 'Chest')")
    connection.executemany(
        """
        INSERT INTO creature_spawns(
            spawn_key, creature_id, zone_id, map_id, coordinate_space, x, y
        ) VALUES (?, ?, ?, NULL, 'zone_percent', ?, ?)
        """,
        (("creature-100-a", 100, 10, 40.0, 50.0), ("creature-101-a", 101, 10, 30.0, 60.0)),
    )
    connection.execute(
        """
        INSERT INTO gameobject_spawns(
            spawn_key, gameobject_id, zone_id, map_id, coordinate_space, x, y
        ) VALUES ('gameobject-200-a', 200, 20, NULL, 'zone_percent', 70, 80)
        """
    )

    connection.executemany(
        "INSERT INTO creature_loot(creature_id, item_id, chance_percent) VALUES (?, ?, ?)",
        ((100, 1, 12.5), (100, 2, 20.0), (100, 3, 15.0)),
    )
    connection.execute(
        "INSERT INTO gameobject_loot(gameobject_id, item_id, chance_percent) VALUES (200, 1, 25.0)"
    )
    connection.execute(
        "INSERT INTO item_reference_loot(item_id, reference_loot_id, chance_percent) "
        "VALUES (1, 9001, 7.5)"
    )
    connection.execute(
        "INSERT INTO reference_loot_creatures(reference_loot_id, creature_id) VALUES (9001, 100)"
    )
    connection.execute(
        "INSERT INTO reference_loot_gameobjects(reference_loot_id, gameobject_id) "
        "VALUES (9001, 200)"
    )
    connection.executemany(
        "INSERT INTO vendor_items(vendor_creature_id, item_id, max_count) VALUES (?, ?, ?)",
        ((101, 1, 0), (102, 4, 2)),
    )

    connection.executemany(
        "INSERT INTO data_sources(id, source_key, display_name, source_kind) VALUES (?, ?, ?, ?)",
        ((1, "pfquest", "pfQuest", "fixture"), (2, "world-fixture", "World", "fixture")),
    )
    next_id = 1

    def observe(
        subject_kind: str,
        subject_key: str,
        fact_key: str,
        fact_instance_key: str,
        value: object,
        *,
        source_id: int = 1,
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
            (observation_id, subject_kind, subject_key, fact_key, fact_instance_key),
        )
        connection.execute(
            """
            INSERT INTO source_observations(
                id, observation_group_id, source_id, source_revision, value_json
            ) VALUES (?, ?, ?, 'fixture-revision', ?)
            """,
            (observation_id, observation_id, source_id, json.dumps(value, sort_keys=True)),
        )
        connection.execute(
            """
            INSERT INTO canonical_selections(
                observation_group_id, observation_id, selection_policy, selection_reason
            ) VALUES (?, ?, 'fixture', 'Fixture selection.')
            """,
            (observation_id, observation_id),
        )

    for item_id, creature_id in ((1, 100), (2, 100), (3, 100)):
        observe(
            "item",
            str(item_id),
            "loot_source",
            f"creature:{creature_id}",
            {"target": {"kind": "creature", "key": creature_id}},
        )
    observe(
        "item",
        "1",
        "loot_source",
        "gameobject:200",
        {"target": {"kind": "gameobject", "key": 200}},
    )
    observe(
        "item",
        "1",
        "loot_reference",
        "reference:9001",
        {"target": {"kind": "loot_reference", "key": 9001}},
    )
    observe(
        "loot_reference",
        "9001",
        "loot_source_member",
        "creature:100",
        {"target": {"kind": "creature", "key": 100}},
    )
    observe(
        "loot_reference",
        "9001",
        "loot_source_member",
        "gameobject:200",
        {"target": {"kind": "gameobject", "key": 200}},
    )
    for item_id, vendor_id, max_count in ((1, 101, 0), (4, 102, 2)):
        observe(
            "item",
            str(item_id),
            "vendor_source",
            f"creature:{vendor_id}",
            {
                "target": {"kind": "creature", "key": vendor_id},
                "attributes": {"max_count": max_count},
            },
        )
    for subject_kind, spawn_key in (
        ("creature_spawn", "creature-100-a"),
        ("creature_spawn", "creature-101-a"),
        ("gameobject_spawn", "gameobject-200-a"),
    ):
        observe(subject_kind, spawn_key, "position", "", {"fixture": True}, source_id=2)
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


def test_unfiltered_composition_preserves_direct_reference_vendor_paths():
    connection = _memory_connection()
    try:
        page = query_item_acquisitions(connection, item_id=1)
    finally:
        connection.close()

    assert page.summary.acquisition_filter_active is False
    assert len(page.results) == 1
    result = page.results[0]
    assert result.acquisition_filter.state == ACQUISITION_NOT_FILTERED
    assert len(result.sources) == 3

    wolf = next(source for source in result.sources if source["source_id"] == 100)
    assert [path["path_kind"] for path in wolf["acquisition_paths"]] == ["direct", "reference"]
    assert [path["chance_percent"] for path in wolf["acquisition_paths"]] == [12.5, 7.5]
    assert wolf["chance_percent"] is None

    vendor = next(source for source in result.sources if source["source_id"] == 101)
    vendor_path = vendor["acquisition_paths"][0]
    assert vendor_path["path_kind"] == "vendor"
    assert vendor_path["chance_percent"] is None
    assert vendor_path["vendor_max_count"] == 0


def test_combined_query_uses_positive_acquisition_evidence_and_conservative_unknown():
    connection = _memory_connection()
    try:
        page = query_item_acquisitions(
            connection,
            quality=3,
            path_kinds=("direct",),
            min_drop_chance=10,
            zone_id=10,
            include_states=QUERY_STATES,
            sort_by="item_id",
        )
    finally:
        connection.close()

    states = {result.item.item_id: result.combined_match_state for result in page.results}
    assert states == {
        1: MATCH_KNOWN,
        2: NON_MATCH_KNOWN,
        3: MATCH_UNKNOWN,
        4: MATCH_UNKNOWN,
        5: MATCH_UNKNOWN,
    }
    assert page.summary.known_match_count == 1
    assert page.summary.known_non_match_count == 1
    assert page.summary.unknown_count == 3
    assert page.results[0].acquisition_filter.reason == "known_matching_acquisition_path"
    assert page.results[3].acquisition_filter.reason == "no_known_matching_path_negative_not_proven"


def test_drop_chance_is_path_level_and_vendor_max_count_is_not_chance():
    connection = _memory_connection()
    try:
        vendor_match = query_item_acquisitions(
            connection,
            item_id=4,
            path_kinds=("vendor",),
        )
        vendor_with_drop_filter = query_item_acquisitions(
            connection,
            item_id=4,
            path_kinds=("vendor",),
            min_drop_chance=1,
            include_states=(MATCH_UNKNOWN,),
        )
    finally:
        connection.close()

    assert vendor_match.results[0].combined_match_state == MATCH_KNOWN
    source = vendor_match.results[0].matching_sources[0]
    assert source["zone_id"] is None
    assert source["acquisition_paths"][0]["vendor_max_count"] == 2
    assert vendor_with_drop_filter.results[0].combined_match_state == MATCH_UNKNOWN
    assert vendor_with_drop_filter.results[0].matching_sources == ()


def test_zone_map_and_source_filters_match_one_concrete_source_path_pair():
    connection = _memory_connection()
    try:
        page = query_item_acquisitions(
            connection,
            item_id=1,
            source_kinds=("gameobject",),
            path_kinds=("direct",),
            min_drop_chance=20,
            zone_id=20,
            map_id=2,
        )
    finally:
        connection.close()

    result = page.results[0]
    assert result.combined_match_state == MATCH_KNOWN
    assert len(result.matching_sources) == 1
    source = result.matching_sources[0]
    assert source["source_kind"] == "gameobject"
    assert source["source_id"] == 200
    assert source["zone_id"] == 20
    assert source["map_id"] == 2
    assert [path["path_kind"] for path in source["acquisition_paths"]] == ["direct"]
    assert source["chance_percent"] == 25.0


def test_unlocated_source_is_known_acquisition_but_unknown_for_geography_filter():
    connection = _memory_connection()
    try:
        vendor = query_item_acquisitions(connection, item_id=4, path_kinds=("vendor",))
        located = query_item_acquisitions(
            connection,
            item_id=4,
            path_kinds=("vendor",),
            zone_id=10,
            include_states=(MATCH_UNKNOWN,),
        )
    finally:
        connection.close()

    assert vendor.results[0].combined_match_state == MATCH_KNOWN
    assert vendor.results[0].matching_sources[0]["zone_id"] is None
    assert located.results[0].combined_match_state == MATCH_UNKNOWN
    assert (
        located.results[0].acquisition_filter.reason
        == "no_known_matching_path_negative_not_proven"
    )


def test_acquisition_and_location_provenance_are_preserved():
    connection = _memory_connection()
    try:
        page = query_item_acquisitions(
            connection,
            item_id=1,
            path_kinds=("reference",),
            source_kinds=("creature",),
        )
    finally:
        connection.close()

    source = page.results[0].matching_sources[0]
    path = source["acquisition_paths"][0]
    assert path["relation_source"] == {
        "source_key": "pfquest",
        "source_revision": "fixture-revision",
    }
    assert path["reference_membership_source"] == {
        "source_key": "pfquest",
        "source_revision": "fixture-revision",
    }
    assert source["location_source"] == {
        "source_key": "world-fixture",
        "source_revision": "fixture-revision",
    }


def test_default_positive_filter_returns_only_known_matches_with_deterministic_limit():
    connection = _memory_connection()
    try:
        page = query_item_acquisitions(
            connection,
            quality=3,
            path_kinds=("direct",),
            source_kinds=("creature",),
            sort_by="item_id",
            limit=1,
        )
    finally:
        connection.close()

    assert page.summary.known_match_count == 1
    assert page.summary.returned_count == 1
    assert [result.item.item_id for result in page.results] == [1]


def test_json_contract_keeps_p7_item_shape_and_auditable_source_paths():
    connection = _memory_connection()
    try:
        page = query_item_acquisitions(
            connection,
            item_id=1,
            path_kinds=("direct",),
            zone_id=10,
        )
        payload = item_acquisition_page_to_dict(page)
    finally:
        connection.close()

    result = payload["results"][0]
    assert result["item"]["item_id"] == 1
    assert result["item"]["template"]["quality"] == 3
    assert result["combined_match_state"] == MATCH_KNOWN
    assert result["acquisition_filter"]["state"] == MATCH_KNOWN
    assert result["matching_sources"][0]["acquisition_paths"][0]["relation_source"][
        "source_key"
    ] == "pfquest"


def test_validation_rejects_invalid_acquisition_filters():
    connection = _memory_connection()
    try:
        with pytest.raises(ValueError, match="between 0 and 100"):
            query_item_acquisitions(connection, min_drop_chance=101)
        with pytest.raises(ValueError, match="between 0 and 100"):
            query_item_acquisitions(connection, min_drop_chance=float("nan"))
        with pytest.raises(ValueError, match="unsupported path kind"):
            query_item_acquisitions(connection, path_kinds=("craft",))
        with pytest.raises(TypeError, match="sequence"):
            query_item_acquisitions(connection, source_kinds="creature")
    finally:
        connection.close()


def test_cli_json_is_read_only(tmp_path, capsys):
    db_path = tmp_path / "items.sqlite3"
    _file_database(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert (
        item_acquisition_main(
            [
                "--db",
                str(db_path),
                "--item-id",
                "1",
                "--path-kind",
                "direct",
                "--zone-id",
                "10",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert before == after
    assert payload["results"][0]["item"]["item_id"] == 1
    assert payload["results"][0]["combined_match_state"] == MATCH_KNOWN


def test_level2_validator_core_is_read_only_on_synthetic_database(tmp_path):
    db_path = tmp_path / "canonical.sqlite3"
    _file_database(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    validator_path = Path(__file__).parents[1] / "scripts" / "validate_p7_t02.py"
    spec = importlib.util.spec_from_file_location("validate_p7_t02", validator_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.validate(db_path, expected_sha256=before)

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert result["schema_version"] == 14
    assert result["item_identities"] == 5
    assert result["materialized_acquisition_items"] == 4
    assert result["canonical_db_unchanged"] is True
    assert result["foreign_key_check"] == []
    assert result["integrity_check"] == "ok"
    assert before == after

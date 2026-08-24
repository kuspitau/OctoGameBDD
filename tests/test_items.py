from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from octogamedb.__main__ import main
from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_items import (
    IMPORTER_VERSION,
    PfQuestItemImportError,
    compute_pfquest_items_revision,
    import_pfquest_items,
    load_pfquest_item_slice,
)
from octogamedb.importers.pfquest_world import PfQuestParseError
from octogamedb.items import find_item_sources

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "pfquest" / "items_slice"


def _seed_world(
    connection: sqlite3.Connection,
    *,
    omit_creature: int | None = None,
    omit_gameobject: int | None = None,
) -> None:
    connection.execute("INSERT INTO maps(map_id, name) VALUES (1, 'Test Map')")
    connection.execute("INSERT INTO zones(zone_id, map_id, name) VALUES (10, 1, 'Test Zone')")
    for creature_id, name in (
        (2001, "Test Wolf"),
        (2002, "Test Boar"),
        (2003, "Test Bear"),
    ):
        if creature_id != omit_creature:
            connection.execute(
                "INSERT INTO creatures(creature_id, name) VALUES (?, ?)",
                (creature_id, name),
            )
    if omit_gameobject != 3001:
        connection.execute(
            "INSERT INTO gameobjects(gameobject_id, name) VALUES (3001, 'Test Chest')"
        )

    for spawn_key, creature_id, x, y in (
        ("creature-2001-a", 2001, 40.0, 50.0),
        ("creature-2003-a", 2003, 45.0, 55.0),
    ):
        if creature_id != omit_creature:
            connection.execute(
                """
                INSERT INTO creature_spawns(
                    spawn_key, creature_id, zone_id, coordinate_space, x, y
                )
                VALUES (?, ?, 10, 'zone_percent', ?, ?)
                """,
                (spawn_key, creature_id, x, y),
            )
    if omit_gameobject != 3001:
        connection.execute(
            """
            INSERT INTO gameobject_spawns(
                spawn_key, gameobject_id, zone_id, coordinate_space, x, y
            )
            VALUES ('gameobject-3001-a', 3001, 10, 'zone_percent', 60, 70)
            """
        )

    connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind)
        VALUES ('world-fixture', 'World Fixture', 'test')
        """
    )
    source_id = int(
        connection.execute(
            "SELECT id FROM data_sources WHERE source_key = 'world-fixture'"
        ).fetchone()[0]
    )
    batch_id = int(
        connection.execute(
            """
            INSERT INTO import_batches(source_id, source_revision, status)
            VALUES (?, 'world-1', 'running')
            """,
            (source_id,),
        ).lastrowid
    )
    positions = []
    if omit_creature != 2001:
        positions.append(("creature_spawn", "creature-2001-a", 40.0, 50.0))
    if omit_creature != 2003:
        positions.append(("creature_spawn", "creature-2003-a", 45.0, 55.0))
    if omit_gameobject != 3001:
        positions.append(("gameobject_spawn", "gameobject-3001-a", 60.0, 70.0))
    for subject_kind, spawn_key, x, y in positions:
        observation_id = record_scalar_observation(
            connection,
            subject_kind=subject_kind,
            subject_key=spawn_key,
            fact_key="position",
            import_batch_id=batch_id,
            value={
                "coordinate_space": "zone_percent",
                "zone_id": 10,
                "x": x,
                "y": y,
            },
            source_record_type="spawn",
            raw_identifier=spawn_key,
        )
        group_id = int(
            connection.execute(
                "SELECT observation_group_id FROM source_observations WHERE id = ?",
                (observation_id,),
            ).fetchone()[0]
        )
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy="fixture",
            selection_reason="Fixture world position.",
        )
    connection.execute(
        """
        UPDATE import_batches
        SET status = 'succeeded', finished_at = '2026-08-24T00:00:00Z'
        WHERE id = ?
        """,
        (batch_id,),
    )


def test_pfquest_item_fixture_parses_direct_and_reference_relations():
    slice_data = load_pfquest_item_slice(FIXTURE_ROOT)

    assert slice_data.rows_read == 4
    assert slice_data.rows_skipped == 1
    assert [item.item_id for item in slice_data.items] == [1001, 1002, 1004]
    first = slice_data.items[0]
    assert first.creature_loot == ((2001, 12.5),)
    assert first.gameobject_loot == ((3001, 25.0),)
    assert first.reference_loot == ((9001, 7.5),)
    assert first.vendor_count == 1
    assert slice_data.missing_reference_ids == ()
    assert len(slice_data.reference_loot) == 1
    reference = slice_data.reference_loot[0]
    assert reference.reference_loot_id == 9001
    assert reference.creature_memberships == ((2001, 1.0), (2003, 1.0))
    assert reference.gameobject_memberships == ((3002, 1.0),)
    assert dict(slice_data.creature_names) == {
        2001: "Test Wolf",
        2002: "Test Boar",
        2003: "Test Bear",
    }
    assert dict(slice_data.gameobject_names) == {
        3001: "Test Chest",
        3002: "Reference Cache",
    }


def test_pfquest_item_revision_is_content_deterministic(tmp_path):
    root = tmp_path / "pfquest"
    shutil.copytree(FIXTURE_ROOT, root)

    first = compute_pfquest_items_revision(root)
    second = compute_pfquest_items_revision(root)
    assert first == second

    items_path = root / "db" / "items.lua"
    items_path.write_text(
        items_path.read_text(encoding="utf-8") + "\n-- changed\n", encoding="utf-8"
    )
    assert compute_pfquest_items_revision(root) != first

    shutil.copytree(FIXTURE_ROOT, root, dirs_exist_ok=True)
    refloot_path = root / "db" / "refloot.lua"
    refloot_path.write_text(
        refloot_path.read_text(encoding="utf-8") + "\n-- changed reference input\n",
        encoding="utf-8",
    )
    assert compute_pfquest_items_revision(root) != first


def test_pfquest_item_parser_rejects_out_of_range_reference_chance(tmp_path):
    root = tmp_path / "pfquest"
    shutil.copytree(FIXTURE_ROOT, root)
    items_path = root / "db" / "items.lua"
    text = items_path.read_text(encoding="utf-8").replace("[9001] = 7.5", "[9001] = 125")
    items_path.write_text(text, encoding="utf-8")

    with pytest.raises(PfQuestParseError, match="between 0 and 100"):
        load_pfquest_item_slice(root)


def test_pfquest_item_parser_rejects_nested_reference_shape(tmp_path):
    root = tmp_path / "pfquest"
    shutil.copytree(FIXTURE_ROOT, root)
    refloot_path = root / "db" / "refloot.lua"
    text = refloot_path.read_text(encoding="utf-8").replace(
        '["O"] = {\n      [3002] = 1,\n    },',
        '["O"] = {\n      [3002] = 1,\n    },\n    ["R"] = {\n      [9001] = 1,\n    },',
    )
    refloot_path.write_text(text, encoding="utf-8")

    with pytest.raises(PfQuestParseError, match="one-level"):
        load_pfquest_item_slice(root)


def test_missing_reference_definition_is_preserved_and_reported(tmp_path):
    root = tmp_path / "pfquest"
    shutil.copytree(FIXTURE_ROOT, root)
    items_path = root / "db" / "items.lua"
    items_path.write_text(
        items_path.read_text(encoding="utf-8").replace("[9001] = 7.5", "[9999] = 7.5"),
        encoding="utf-8",
    )
    revision = compute_pfquest_items_revision(root)
    db_path = tmp_path / "missing-reference.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_world(connection)
        summary = import_pfquest_items(connection, source_root=root, source_revision=revision)
        assert summary.warning_count == 1
        assert summary.details["unresolved_reference_loot"] == [
            {"reference_loot_id": 9999, "reason": "missing_refloot_definition"}
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM item_reference_loot WHERE reference_loot_id = 9999"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM loot_references WHERE reference_loot_id = 9999"
        ).fetchone()[0] == 1
        sources = find_item_sources(connection, 1001)[0]["sources"]
        assert {source["source_id"] for source in sources} == {2001, 3001}
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_pfquest_item_import_is_idempotent_and_preserves_reference_provenance(tmp_path):
    db_path = tmp_path / "items.sqlite3"
    revision = compute_pfquest_items_revision(FIXTURE_ROOT)

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_world(connection)
        first = import_pfquest_items(
            connection,
            source_root=FIXTURE_ROOT,
            source_revision=revision,
        )
        second = import_pfquest_items(
            connection,
            source_root=FIXTURE_ROOT,
            source_revision=revision,
        )

        assert first.rows_read == 4
        assert first.rows_accepted == 3
        assert first.rows_skipped == 1
        assert first.rows_inserted == 12
        assert first.rows_updated == 0
        assert first.warning_count == 0
        assert first.details["creature_loot_links"] == 2
        assert first.details["gameobject_loot_links"] == 1
        assert first.details["reference_loot_links"] == 1
        assert first.details["resolved_reference_loot_links"] == 1
        assert first.details["reference_loot_definitions"] == 1
        assert first.details["reference_creature_memberships"] == 2
        assert first.details["reference_gameobject_memberships"] == 1
        assert first.details["deferred_vendor_links"] == 1
        assert first.details["relation_only_gameobject_templates"] == 1
        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert second.warning_count == 0
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM creature_loot").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM gameobject_loot").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM loot_references").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM item_reference_loot").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM reference_loot_creatures").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM reference_loot_gameobjects").fetchone()[0] == 1

        item_reference_observations = connection.execute(
            """
            SELECT COUNT(*)
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'item'
              AND og.subject_key = '1001'
              AND og.fact_key = 'loot_reference'
              AND og.fact_instance_key = 'reference:9001'
              AND ds.source_key = 'pfquest'
            """
        ).fetchone()[0]
        assert item_reference_observations == 1

        member_observations = connection.execute(
            """
            SELECT COUNT(*)
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'loot_reference'
              AND og.subject_key = '9001'
              AND og.fact_key = 'loot_source_member'
              AND ds.source_key = 'pfquest'
            """
        ).fetchone()[0]
        assert member_observations == 3
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_item_source_query_resolves_reference_geography_and_deduplicates_overlap(tmp_path):
    db_path = tmp_path / "query.sqlite3"
    revision = compute_pfquest_items_revision(FIXTURE_ROOT)

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_world(connection)
        import_pfquest_items(connection, source_root=FIXTURE_ROOT, source_revision=revision)
        result = find_item_sources(connection, 1001)

    assert len(result) == 1
    assert result[0]["item_name"] == "Test Relic"
    assert len(result[0]["sources"]) == 4

    wolf = next(
        source
        for source in result[0]["sources"]
        if source["source_kind"] == "creature" and source["source_id"] == 2001
    )
    assert wolf["zone_id"] == 10
    assert wolf["map_id"] == 1
    assert wolf["chance_percent"] is None
    assert [path["path_kind"] for path in wolf["acquisition_paths"]] == ["direct", "reference"]
    assert [path["chance_percent"] for path in wolf["acquisition_paths"]] == [12.5, 7.5]
    assert wolf["acquisition_paths"][0]["relation_source"]["source_key"] == "pfquest"
    assert wolf["acquisition_paths"][1]["relation_source"]["source_key"] == "pfquest"
    assert (
        wolf["acquisition_paths"][1]["reference_membership_source"]["source_key"] == "pfquest"
    )
    assert wolf["location_source"]["source_key"] == "world-fixture"

    bear = next(
        source
        for source in result[0]["sources"]
        if source["source_kind"] == "creature" and source["source_id"] == 2003
    )
    assert bear["chance_percent"] == 7.5
    assert bear["zone_name"] == "Test Zone"
    assert bear["map_name"] == "Test Map"
    assert bear["acquisition_paths"] == [
        {
            "path_kind": "reference",
            "chance_percent": 7.5,
            "reference_loot_id": 9001,
            "relation_source": bear["acquisition_paths"][0]["relation_source"],
            "reference_membership_source": bear["acquisition_paths"][0][
                "reference_membership_source"
            ],
        }
    ]

    reference_cache = next(
        source
        for source in result[0]["sources"]
        if source["source_kind"] == "gameobject" and source["source_id"] == 3002
    )
    assert reference_cache["source_name"] == "Reference Cache"
    assert reference_cache["spawn_key"] is None
    assert reference_cache["zone_id"] is None
    assert reference_cache["location_source"] is None
    assert reference_cache["acquisition_paths"][0]["path_kind"] == "reference"


def test_pfquest_item_import_materializes_named_relation_only_templates(tmp_path):
    db_path = tmp_path / "relation-only.sqlite3"
    revision = compute_pfquest_items_revision(FIXTURE_ROOT)

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_world(connection, omit_creature=2002, omit_gameobject=3001)
        summary = import_pfquest_items(
            connection,
            source_root=FIXTURE_ROOT,
            source_revision=revision,
        )

        assert summary.details["relation_only_creature_templates"] == 1
        # direct 3001 and reference-only 3002 both gain identity anchors, never spawns
        assert summary.details["relation_only_gameobject_templates"] == 2
        assert connection.execute(
            "SELECT name FROM creatures WHERE creature_id = 2002"
        ).fetchone()[0] == "Test Boar"
        assert connection.execute(
            "SELECT name FROM gameobjects WHERE gameobject_id = 3001"
        ).fetchone()[0] == "Test Chest"
        assert connection.execute(
            "SELECT name FROM gameobjects WHERE gameobject_id = 3002"
        ).fetchone()[0] == "Reference Cache"
        assert connection.execute(
            "SELECT COUNT(*) FROM creature_spawns WHERE creature_id = 2002"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM gameobject_spawns WHERE gameobject_id IN (3001, 3002)"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_reference_member_without_identity_is_reported_but_provenance_is_kept(tmp_path):
    root = tmp_path / "pfquest"
    shutil.copytree(FIXTURE_ROOT, root)
    units_path = root / "db" / "enUS" / "units.lua"
    units_path.write_text(
        units_path.read_text(encoding="utf-8").replace('  [2003] = "Test Bear",\n', ""),
        encoding="utf-8",
    )
    revision = compute_pfquest_items_revision(root)
    db_path = tmp_path / "missing-ref-identity.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_world(connection, omit_creature=2003)
        summary = import_pfquest_items(connection, source_root=root, source_revision=revision)
        assert {
            "reference_loot_id": 9001,
            "source_kind": "creature",
            "source_id": 2003,
            "reason": "missing_source_identity",
        } in summary.details["unresolved_reference_loot"]
        assert connection.execute(
            "SELECT COUNT(*) FROM reference_loot_creatures WHERE creature_id = 2003"
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM observation_groups
            WHERE subject_kind = 'loot_reference'
              AND subject_key = '9001'
              AND fact_key = 'loot_source_member'
              AND fact_instance_key = 'creature:2003'
            """
        ).fetchone()[0] == 1


def test_pfquest_item_import_fails_closed_when_direct_relation_target_has_no_name(tmp_path):
    root = tmp_path / "pfquest"
    shutil.copytree(FIXTURE_ROOT, root)
    units_path = root / "db" / "enUS" / "units.lua"
    units_path.write_text(
        units_path.read_text(encoding="utf-8").replace('  [2002] = "Test Boar",\n', ""),
        encoding="utf-8",
    )
    revision = compute_pfquest_items_revision(root)
    db_path = tmp_path / "missing-identity.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_world(connection, omit_creature=2002)
        with pytest.raises(PfQuestItemImportError, match=r"missing creature IDs=\[2002\]"):
            import_pfquest_items(
                connection,
                source_root=root,
                source_revision=revision,
            )
        batch = connection.execute(
            """
            SELECT status, error_count, details_json
            FROM import_batches
            WHERE importer_version = ?
            """,
            (IMPORTER_VERSION,),
        ).fetchone()
        assert batch["status"] == "failed"
        assert batch["error_count"] == 1
        assert "2002" in batch["details_json"]
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


def test_item_cli_import_and_query_json(tmp_path, capsys):
    db_path = tmp_path / "cli.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_world(connection)

    assert (
        main(
            [
                "import-pfquest-items",
                str(FIXTURE_ROOT),
                "--db",
                str(db_path),
                "--json",
            ]
        )
        == 0
    )
    imported = json.loads(capsys.readouterr().out)
    assert imported["status"] == "succeeded"
    assert imported["details"]["reference_loot_links"] == 1
    assert imported["details"]["unresolved_reference_loot"] == []

    assert main(["item-sources", "1001", "--db", str(db_path), "--json"]) == 0
    queried = json.loads(capsys.readouterr().out)
    assert queried[0]["item_id"] == 1001
    assert len(queried[0]["sources"]) == 4
    assert any(
        path["path_kind"] == "reference"
        for source in queried[0]["sources"]
        for path in source["acquisition_paths"]
    )

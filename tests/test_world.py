from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_world import (
    PfQuestParseError,
    import_pfquest_world_slice,
    load_pfquest_world_slice,
    parse_pfquest_assignment,
)
from octogamedb.world import find_world_locations

_FIXTURE = Path(__file__).parent / "fixtures" / "pfquest" / "world_slice"
_REVISION = "104f35678ca39ab1fb78b655f815cc7016f5e0c8"


def test_pfquest_source_shaped_fixture_parses():
    world = load_pfquest_world_slice(_FIXTURE)

    assert [(zone.zone_id, zone.name) for zone in world.zones] == [
        (9, "Northshire Valley"),
        (12, "Elwynn Forest"),
    ]
    assert world.zones[0].coordinate_frame == {
        "coordinate_context_id": 12,
        "width": 17.47,
        "height": 27.69,
        "origin_x": 51.15,
        "origin_y": 42.29,
    }

    assert len(world.creatures) == 1
    creature = world.creatures[0]
    assert creature.creature_id == 6
    assert creature.name == "Kobold Vermin"
    assert (creature.level_min, creature.level_max, creature.faction) == (1, 2, "H")
    creature_spawns = [
        (spawn.x, spawn.y, spawn.zone_id, spawn.respawn_seconds)
        for spawn in creature.spawns
    ]
    assert creature_spawns == [
        (48.5, 52.25, 12, 300),
        (49.75, 53.0, 12, 300),
    ]

    assert len(world.gameobjects) == 1
    gameobject = world.gameobjects[0]
    assert gameobject.gameobject_id == 32
    assert gameobject.name == "Sunken Chest"
    gameobject_spawns = [
        (spawn.x, spawn.y, spawn.zone_id, spawn.respawn_seconds)
        for spawn in gameobject.spawns
    ]
    assert gameobject_spawns == [(42.0, 61.5, 12, 600)]


def test_pfquest_lua_subset_supports_comments_escapes_and_keyed_tables():
    parsed = parse_pfquest_assignment(
        """
        -- comment before the assignment
        pfDB["units"]["data"] = {
          [7] = {
            ["lvl"] = "3-4",
            ["coords"] = { [1] = { 1.25, 2.5, 12, 0 }, },
            ["note"] = "Captain\\'s test",
          },
        }
        """,
        domain="units",
        table_name="data",
    )

    assert parsed[7]["lvl"] == "3-4"
    assert parsed[7]["coords"][1][3] == 12
    assert parsed[7]["note"] == "Captain's test"


def test_pfquest_parser_rejects_out_of_range_zone_percent(tmp_path):
    source = tmp_path / "pfquest"
    for relative in (
        "db/enUS/zones.lua",
        "db/enUS/units.lua",
        "db/enUS/objects.lua",
        "db/zones.lua",
        "db/objects.lua",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)

    (source / "db/zones.lua").write_text(
        'pfDB["zones"]["data"] = {}',
        encoding="utf-8",
    )
    (source / "db/enUS/zones.lua").write_text(
        'pfDB["zones"]["enUS"] = { [12] = "Elwynn Forest" }',
        encoding="utf-8",
    )
    (source / "db/units.lua").write_text(
        'pfDB["units"]["data"] = { [6] = { ["coords"] = { [1] = { 101, 50, 12, 30 } } } }',
        encoding="utf-8",
    )
    (source / "db/enUS/units.lua").write_text(
        'pfDB["units"]["enUS"] = { [6] = "Kobold Vermin" }',
        encoding="utf-8",
    )
    (source / "db/objects.lua").write_text(
        'pfDB["objects"]["data"] = {}',
        encoding="utf-8",
    )
    (source / "db/enUS/objects.lua").write_text(
        'pfDB["objects"]["enUS"] = {}',
        encoding="utf-8",
    )

    with pytest.raises(PfQuestParseError, match="outside zone-percent bounds"):
        load_pfquest_world_slice(source)


def test_world_schema_enforces_coordinate_semantics(tmp_path):
    db_path = tmp_path / "world.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO zones(zone_id, name) VALUES (12, 'Elwynn Forest')"
        )
        connection.execute(
            "INSERT INTO creatures(creature_id, name) VALUES (6, 'Kobold Vermin')"
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO creature_spawns(
                    spawn_key, creature_id, zone_id, coordinate_space, x, y
                )
                VALUES ('bad', 6, 12, 'zone_percent', 120, 50)
                """
            )


def test_pfquest_world_slice_import_is_idempotent_and_traceable(tmp_path):
    db_path = tmp_path / "world.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)

        first = import_pfquest_world_slice(
            connection,
            source_root=_FIXTURE,
            source_revision=_REVISION,
        )
        second = import_pfquest_world_slice(
            connection,
            source_root=_FIXTURE,
            source_revision=_REVISION,
        )

        assert first.status == "succeeded"
        assert first.rows_read == 4
        assert first.rows_accepted == 4
        assert first.rows_inserted == 7
        assert first.rows_updated == 0
        assert first.details == {
            "canonical_rows_inserted_or_updated": 7,
            "creature_spawns": 2,
            "gameobject_spawns": 1,
            "zones": 2,
            "creatures": 1,
            "gameobjects": 1,
        }

        assert second.rows_inserted == 0
        assert second.rows_updated == 0

        assert connection.execute("SELECT COUNT(*) FROM zones").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM creatures").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM creature_spawns").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM gameobjects").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM gameobject_spawns").fetchone()[0] == 1

        observations = connection.execute(
            """
            SELECT COUNT(*)
            FROM source_observations AS so
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE ds.source_key = 'pfquest'
              AND so.source_revision = ?
            """,
            (_REVISION,),
        ).fetchone()[0]
        assert observations > 0

        batch_links = connection.execute(
            """
            SELECT COUNT(DISTINCT oib.import_batch_id)
            FROM observation_import_batches AS oib
            JOIN source_observations AS so ON so.id = oib.observation_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE ds.source_key = 'pfquest'
              AND so.source_revision = ?
            """,
            (_REVISION,),
        ).fetchone()[0]
        assert batch_links == 2


def test_pfquest_import_preserves_an_existing_explicit_canonical_selection(tmp_path):
    db_path = tmp_path / "selection.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        source = connection.execute(
            """
            INSERT INTO data_sources(source_key, display_name, source_kind)
            VALUES ('authoritative-fixture', 'Authoritative Fixture', 'fixture')
            """
        )
        batch = connection.execute(
            """
            INSERT INTO import_batches(
                source_id, source_revision, status, finished_at, rows_read, rows_accepted
            )
            VALUES (?, 'authoritative-rev', 'succeeded', '2026-08-24T00:00:00Z', 1, 1)
            """,
            (int(source.lastrowid),),
        )
        winner = record_scalar_observation(
            connection,
            subject_kind="zone",
            subject_key=12,
            fact_key="name",
            import_batch_id=int(batch.lastrowid),
            value="Canonical Elwynn",
            source_record_type="zone",
            raw_identifier=12,
        )
        group_id = int(
            connection.execute(
                "SELECT observation_group_id FROM source_observations WHERE id = ?",
                (winner,),
            ).fetchone()[0]
        )
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=winner,
            selection_policy="fixture-authority",
            selection_reason="Exercise preservation of a prior explicit selection.",
        )

        import_pfquest_world_slice(
            connection,
            source_root=_FIXTURE,
            source_revision=_REVISION,
        )

        assert connection.execute(
            "SELECT name FROM zones WHERE zone_id = 12"
        ).fetchone()[0] == "Canonical Elwynn"
        selection = connection.execute(
            """
            SELECT observation_id, selection_policy
            FROM canonical_selections
            WHERE observation_group_id = ?
            """,
            (group_id,),
        ).fetchone()
        assert selection["observation_id"] == winner
        assert selection["selection_policy"] == "fixture-authority"


def test_where_query_returns_zone_and_selected_position_source(tmp_path):
    db_path = tmp_path / "world.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        import_pfquest_world_slice(
            connection,
            source_root=_FIXTURE,
            source_revision=_REVISION,
        )

        creature_locations = find_world_locations(connection, "kobold")
        assert len(creature_locations) == 2
        assert {entry["zone_name"] for entry in creature_locations} == {"Elwynn Forest"}
        assert {entry["coordinate_space"] for entry in creature_locations} == {"zone_percent"}
        assert all(
            entry["sources"] == [{"source_key": "pfquest", "source_revision": _REVISION}]
            for entry in creature_locations
        )

        object_locations = find_world_locations(connection, "sunken")
        assert object_locations == [
            {
                "entity_kind": "gameobject",
                "entity_id": 32,
                "name": "Sunken Chest",
                "spawn_key": "gameobject:32:zone_percent:12:42.000000:61.500000",
                "coordinate_space": "zone_percent",
                "x": 42.0,
                "y": 61.5,
                "z": None,
                "orientation": None,
                "respawn_seconds": 600,
                "zone_id": 12,
                "zone_name": "Elwynn Forest",
                "map_id": None,
                "map_name": None,
                "sources": [{"source_key": "pfquest", "source_revision": _REVISION}],
            }
        ]

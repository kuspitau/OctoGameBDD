from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.octo_dbc_world import (
    SELECTION_POLICY,
    DbcParseError,
    compute_octodbc_world_revision,
    import_octodbc_world,
    load_octodbc_world_slice,
)
from octogamedb.world import find_world_locations

_FIXTURE = Path(__file__).parent / "fixtures" / "octo_dbc" / "world_slice"



def _copy_fixture_with_unnamed_area(source_root: Path, target_root: Path) -> None:
    target_root.mkdir()
    (target_root / "Map.dbc").write_bytes((source_root / "Map.dbc").read_bytes())

    source = (source_root / "AreaTable.dbc").read_bytes()
    magic, record_count, field_count, record_size, string_size = struct.unpack_from(
        "<4sIIII", source, 0
    )
    records_start = 20
    strings_start = records_start + record_count * record_size
    records = bytearray(source[records_start:strings_start])
    strings = source[strings_start:]

    unnamed = [0] * field_count
    unnamed[0] = 3884
    records.extend(struct.pack("<" + "I" * field_count, *unnamed))
    header = struct.pack(
        "<4sIIII",
        magic,
        record_count + 1,
        field_count,
        record_size,
        string_size,
    )
    (target_root / "AreaTable.dbc").write_bytes(header + records + strings)


def test_octodbc_source_shaped_fixture_parses_map_and_area_hierarchy():
    world = load_octodbc_world_slice(_FIXTURE)

    assert [(row.map_id, row.name, row.map_kind) for row in world.maps] == [
        (0, "Eastern Kingdoms", "common"),
        (1, "Kalimdor", "common"),
    ]
    assert [
        (row.zone_id, row.map_id, row.parent_zone_id, row.name)
        for row in world.areas
    ] == [
        (9, 0, 12, "Northshire Valley"),
        (12, 0, None, "Elwynn Forest"),
        (14, 1, None, "Durotar"),
    ]
    assert world.areas[0].area_level == 5
    assert world.areas[0].faction_group_mask == 2


def test_octodbc_revision_is_deterministic_for_exact_dbc_pair(tmp_path):
    first = compute_octodbc_world_revision(_FIXTURE)
    second = compute_octodbc_world_revision(_FIXTURE)
    assert first == second
    assert first.startswith("sha256:")

    copied = tmp_path / "dbc"
    copied.mkdir()
    for name in ("Map.dbc", "AreaTable.dbc"):
        (copied / name).write_bytes((_FIXTURE / name).read_bytes())
    data = bytearray((copied / "Map.dbc").read_bytes())
    data[-2] ^= 1
    (copied / "Map.dbc").write_bytes(data)
    assert compute_octodbc_world_revision(copied) != first


def test_octodbc_parser_rejects_non_wdbc_file(tmp_path):
    source = tmp_path / "dbc"
    source.mkdir()
    (source / "Map.dbc").write_bytes(b"NOPE" + b"\0" * 64)
    (source / "AreaTable.dbc").write_bytes((_FIXTURE / "AreaTable.dbc").read_bytes())

    with pytest.raises(DbcParseError, match="expected WDBC magic"):
        load_octodbc_world_slice(source)


def test_octodbc_world_import_is_idempotent_and_traceable(tmp_path):
    db_path = tmp_path / "world.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        first = import_octodbc_world(connection, source_root=_FIXTURE)
        second = import_octodbc_world(connection, source_root=_FIXTURE)

        assert first.status == "succeeded"
        assert first.rows_read == 5
        assert first.rows_accepted == 5
        assert first.rows_inserted == 5
        assert first.rows_updated == 0
        assert first.details == {
            "canonical_rows_inserted_or_updated": 5,
            "maps": 2,
            "zones": 3,
            "hierarchy_links": 1,
            "revision_method": "sha256(Map.dbc,AreaTable.dbc)",
        }
        assert second.rows_inserted == 0
        assert second.rows_updated == 0

        assert [tuple(row) for row in connection.execute(
            "SELECT map_id, name, map_kind FROM maps ORDER BY map_id"
        )] == [
            (0, "Eastern Kingdoms", "common"),
            (1, "Kalimdor", "common"),
        ]
        assert [tuple(row) for row in connection.execute(
            "SELECT zone_id, map_id, parent_zone_id, name FROM zones ORDER BY zone_id"
        )] == [
            (9, 0, 12, "Northshire Valley"),
            (12, 0, None, "Elwynn Forest"),
            (14, 1, None, "Durotar"),
        ]

        observations = connection.execute(
            """
            SELECT COUNT(*)
            FROM source_observations AS so
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE ds.source_key = 'octo-client-dbc'
            """
        ).fetchone()[0]
        assert observations > 0
        batch_links = connection.execute(
            """
            SELECT COUNT(DISTINCT oib.import_batch_id)
            FROM observation_import_batches AS oib
            JOIN source_observations AS so ON so.id = oib.observation_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE ds.source_key = 'octo-client-dbc'
            """
        ).fetchone()[0]
        assert batch_links == 2


def test_octodbc_geography_policy_supersedes_prior_selection_without_losing_evidence(tmp_path):
    db_path = tmp_path / "selection.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        source = connection.execute(
            """
            INSERT INTO data_sources(source_key, display_name, source_kind)
            VALUES ('fallback-fixture', 'Fallback Fixture', 'fixture')
            """
        )
        batch = connection.execute(
            """
            INSERT INTO import_batches(
                source_id, source_revision, status, finished_at, rows_read, rows_accepted
            ) VALUES (?, 'fallback-r1', 'succeeded', '2026-08-24T00:00:00Z', 1, 1)
            """,
            (int(source.lastrowid),),
        )
        old_observation = record_scalar_observation(
            connection,
            subject_kind="zone",
            subject_key=12,
            fact_key="name",
            import_batch_id=int(batch.lastrowid),
            value="Fallback Elwynn",
            source_record_type="fixture",
            raw_identifier=12,
        )
        group_id = int(connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id = ?",
            (old_observation,),
        ).fetchone()[0])
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=old_observation,
            selection_policy="fallback",
            selection_reason="Seed a lower-authority selection for the policy test.",
        )
        connection.execute(
            "INSERT INTO zones(zone_id, name) VALUES (12, 'Fallback Elwynn')"
        )

        import_octodbc_world(connection, source_root=_FIXTURE)

        assert connection.execute(
            "SELECT name, map_id, parent_zone_id FROM zones WHERE zone_id = 12"
        ).fetchone()[:] == ("Elwynn Forest", 0, None)
        selection = connection.execute(
            """
            SELECT ds.source_key, cs.selection_policy, so.value_json
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            JOIN source_observations AS so ON so.id = cs.observation_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'zone'
              AND og.subject_key = '12'
              AND og.fact_key = 'name'
            """
        ).fetchone()
        assert selection["source_key"] == "octo-client-dbc"
        assert selection["selection_policy"] == SELECTION_POLICY
        assert json.loads(selection["value_json"]) == "Elwynn Forest"
        assert connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE observation_group_id = ?",
            (group_id,),
        ).fetchone()[0] == 2


def test_world_location_derives_map_from_canonical_zone_without_changing_coordinate_space(tmp_path):
    db_path = tmp_path / "location.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        import_octodbc_world(connection, source_root=_FIXTURE)
        connection.execute(
            "INSERT INTO creatures(creature_id, name) VALUES (6, 'Kobold Vermin')"
        )
        connection.execute(
            """
            INSERT INTO creature_spawns(
                spawn_key, creature_id, zone_id, coordinate_space, x, y, respawn_seconds
            ) VALUES ('fixture-spawn', 6, 12, 'zone_percent', 48.5, 52.25, 300)
            """
        )

        result = find_world_locations(connection, "kobold")
        assert len(result) == 1
        assert result[0]["zone_id"] == 12
        assert result[0]["zone_name"] == "Elwynn Forest"
        assert result[0]["map_id"] == 0
        assert result[0]["map_name"] == "Eastern Kingdoms"
        assert result[0]["coordinate_space"] == "zone_percent"



def test_octodbc_import_skips_unreferenced_unnamed_area(tmp_path):
    source = tmp_path / "dbc"
    _copy_fixture_with_unnamed_area(_FIXTURE, source)

    with connect_database(tmp_path / "unnamed.sqlite3") as connection:
        apply_migrations(connection)
        summary = import_octodbc_world(connection, source_root=source)

        assert summary.rows_read == 6
        assert summary.rows_accepted == 5
        assert summary.rows_skipped == 1
        assert summary.warning_count == 1
        assert summary.details["zones"] == 3
        assert summary.details["skipped_unnamed_area_ids"] == [3884]
        assert connection.execute(
            "SELECT COUNT(*) FROM zones WHERE zone_id = 3884"
        ).fetchone()[0] == 0

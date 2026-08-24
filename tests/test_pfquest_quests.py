from __future__ import annotations

from pathlib import Path

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_quests import (
    compute_pfquest_quests_revision,
    import_pfquest_quests,
    load_pfquest_quest_slice,
)
from octogamedb.quests import quest_by_id

_FIXTURE = Path(__file__).parent / "fixtures" / "pfquest" / "quests_slice"


def _seed_world(connection) -> None:
    connection.execute("INSERT INTO maps(map_id, name) VALUES (1, 'Test Map')")
    connection.execute("INSERT INTO zones(zone_id, map_id, name) VALUES (2, 1, 'Test Zone')")
    for creature_id in (10, 11, 12):
        connection.execute(
            "INSERT INTO creatures(creature_id, name) VALUES (?, ?)",
            (creature_id, f"Creature {creature_id}"),
        )
    for gameobject_id in (20, 21):
        connection.execute(
            "INSERT INTO gameobjects(gameobject_id, name) VALUES (?, ?)",
            (gameobject_id, f"Object {gameobject_id}"),
        )
    connection.execute(
        """
        INSERT INTO creature_spawns(
            spawn_key, creature_id, zone_id, coordinate_space, x, y
        ) VALUES ('creature:10:test', 10, 2, 'zone_percent', 40, 60)
        """
    )
    connection.execute(
        """
        INSERT INTO gameobject_spawns(
            spawn_key, gameobject_id, zone_id, coordinate_space, x, y
        ) VALUES ('gameobject:20:test', 20, 2, 'zone_percent', 25, 75)
        """
    )


def test_load_pfquest_quest_slice_parses_bounded_endpoints():
    slice_data = load_pfquest_quest_slice(_FIXTURE)

    assert slice_data.rows_read == 7
    assert slice_data.rows_skipped == 1
    assert slice_data.missing_enus_name_ids == (106,)
    assert [quest.quest_id for quest in slice_data.quests] == [
        100, 101, 102, 103, 104, 105
    ]

    quest = slice_data.quests[0]
    assert quest.name == "A Multi Endpoint Quest"
    assert [
        (endpoint.endpoint_kind, endpoint.target_kind, endpoint.target_id)
        for endpoint in quest.endpoints
    ] == [
        ("finisher", "creature", 12),
        ("finisher", "gameobject", 21),
        ("giver", "creature", 10),
        ("giver", "creature", 11),
        ("giver", "gameobject", 20),
    ]

    # pfQuest also supports item-started quests via start.I. P3-T01 deliberately does not
    # reinterpret those items as creature/game-object endpoint identities.
    item_started = next(quest for quest in slice_data.quests if quest.quest_id == 104)
    assert item_started.endpoints == ()
    assert slice_data.quests[-1].quest_id == 105
    assert slice_data.quests[-1].name == "Locale Only"
    assert slice_data.quests[-1].endpoints == ()


def test_pfquest_quest_revision_is_content_derived(tmp_path):
    copied = tmp_path / "pfquest"
    for source in (_FIXTURE / "db" / "quests.lua", _FIXTURE / "db" / "enUS" / "quests.lua"):
        relative = source.relative_to(_FIXTURE)
        target = copied / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    first = compute_pfquest_quests_revision(copied)
    second = compute_pfquest_quests_revision(copied)
    assert first == second
    assert first.startswith("sha256:")

    locale_path = copied / "db" / "enUS" / "quests.lua"
    locale_path.write_text(
        locale_path.read_text(encoding="utf-8").replace(
            "Item Starter Deferred", "Changed Title"
        ),
        encoding="utf-8",
    )
    assert compute_pfquest_quests_revision(copied) != first


def test_import_is_idempotent_traceable_and_query_derives_world_geography(tmp_path):
    db_path = tmp_path / "quests.sqlite3"
    revision = compute_pfquest_quests_revision(_FIXTURE)

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_world(connection)

        first = import_pfquest_quests(
            connection, source_root=_FIXTURE, source_revision=revision
        )
        second = import_pfquest_quests(
            connection, source_root=_FIXTURE, source_revision=revision
        )

        assert first.rows_read == 7
        assert first.rows_accepted == 6
        assert first.rows_skipped == 1
        assert first.rows_inserted == 13
        assert first.rows_updated == 0
        assert first.warning_count == 2
        assert first.details["creature_endpoints"] == 4
        assert first.details["gameobject_endpoints"] == 3
        assert first.details["missing_enus_name_ids"] == [106]
        assert first.details["unresolved_endpoints"] == [
            {
                "quest_id": 103,
                "endpoint_kind": "giver",
                "target_kind": "creature",
                "target_id": 999,
                "reason": "missing_p1_target",
            }
        ]
        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        result = quest_by_id(connection, 100)
        assert result is not None
        assert result["quest_id"] == 100
        assert result["name"] == "A Multi Endpoint Quest"
        assert [
            (endpoint["endpoint_kind"], endpoint["entity_type"], endpoint["entity_id"])
            for endpoint in result["endpoints"]
        ] == [
            ("finisher", "creature", 12),
            ("finisher", "gameobject", 21),
            ("giver", "creature", 10),
            ("giver", "creature", 11),
            ("giver", "gameobject", 20),
        ]

        creature_location = next(
            endpoint for endpoint in result["endpoints"] if endpoint["entity_id"] == 10
        )["locations"]
        assert creature_location == [
            {
                "spawn_id": 1,
                "map_id": 1,
                "map_name": "Test Map",
                "zone_id": 2,
                "zone_name": "Test Zone",
                "coordinate_space": "zone_percent",
                "x": 40.0,
                "y": 60.0,
                "z": None,
            }
        ]
        object_location = next(
            endpoint
            for endpoint in result["endpoints"]
            if endpoint["entity_type"] == "gameobject" and endpoint["entity_id"] == 20
        )["locations"]
        assert object_location == [
            {
                "spawn_id": 1,
                "map_id": 1,
                "map_name": "Test Map",
                "zone_id": 2,
                "zone_name": "Test Zone",
                "coordinate_space": "zone_percent",
                "x": 25.0,
                "y": 75.0,
                "z": None,
            }
        ]
        assert quest_by_id(connection, 999999) is None

        endpoint_groups = connection.execute(
            """
            SELECT COUNT(*)
            FROM observation_groups
            WHERE subject_kind = 'quest' AND fact_key = 'endpoint'
            """
        ).fetchone()[0]
        assert endpoint_groups == 8

        batch_links = connection.execute(
            """
            SELECT COUNT(DISTINCT oib.import_batch_id)
            FROM observation_import_batches AS oib
            JOIN source_observations AS so ON so.id = oib.observation_id
            JOIN observation_groups AS og ON og.id = so.observation_group_id
            WHERE og.subject_kind = 'quest'
              AND og.subject_key = '100'
              AND og.fact_key = 'endpoint'
              AND so.source_revision = ?
            """,
            (revision,),
        ).fetchone()[0]
        assert batch_links == 2


def test_existing_manual_name_selection_is_preserved(tmp_path):
    db_path = tmp_path / "selection.sqlite3"
    revision = compute_pfquest_quests_revision(_FIXTURE)

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _seed_world(connection)

        source_id = connection.execute(
            """
            INSERT INTO data_sources(source_key, display_name, source_kind)
            VALUES ('curated-quest-test', 'Curated quest test', 'test')
            """
        ).lastrowid
        batch_id = connection.execute(
            """
            INSERT INTO import_batches(
                source_id, source_revision, status, importer_version, rows_read
            )
            VALUES (?, 'curated-rev', 'running', 'test/1', 1)
            """,
            (source_id,),
        ).lastrowid
        observation_id = record_scalar_observation(
            connection,
            subject_kind="quest",
            subject_key=100,
            fact_key="name",
            import_batch_id=batch_id,
            value="Curated Quest Name",
            source_record_type="manual_test",
            raw_identifier="100",
        )
        group_id = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=observation_id,
            selection_policy="manual-test",
            selection_reason="Exercise canonical-selection preservation in P3-T01.",
        )

        import_pfquest_quests(connection, source_root=_FIXTURE, source_revision=revision)

        assert connection.execute(
            "SELECT name FROM quests WHERE quest_id = 100"
        ).fetchone()[0] == "Curated Quest Name"
        values = connection.execute(
            """
            SELECT so.value_json
            FROM source_observations AS so
            JOIN observation_groups AS og ON og.id = so.observation_group_id
            WHERE og.subject_kind = 'quest'
              AND og.subject_key = '100'
              AND og.fact_key = 'name'
            ORDER BY so.id
            """
        ).fetchall()
        assert [row[0] for row in values] == [
            '"Curated Quest Name"',
            '"A Multi Endpoint Quest"',
        ]

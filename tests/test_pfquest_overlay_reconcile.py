from __future__ import annotations

from pathlib import Path

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_overlay_reconcile import (
    PFQUEST_OCTO_SOURCE_KEY,
    PFQUEST_TURTLE_SOURCE_KEY,
    SPAWN_SET_FACT,
    TURTLE_SELECTION_POLICY,
    WORLD_PRESENCE_FACT,
    compute_pfquest_overlay_revision,
    compute_pfquest_world_revision,
    reconcile_pfquest_world_slices,
)
from octogamedb.importers.pfquest_world import (
    PFQUEST_SOURCE_KEY,
    PfQuestCreature,
    PfQuestGameObject,
    PfQuestSpawn,
    PfQuestWorldSlice,
    PfQuestZone,
)

_BASE_REVISION = "base-r1"


def _spawn(x: float, y: float, respawn: int = 300) -> PfQuestSpawn:
    return PfQuestSpawn(x=x, y=y, zone_id=12, respawn_seconds=respawn)


def _base_world() -> PfQuestWorldSlice:
    return PfQuestWorldSlice(
        zones=(PfQuestZone(12, "Elwynn Forest"),),
        creatures=(
            PfQuestCreature(
                6,
                "Kobold Vermin",
                1,
                2,
                "H",
                (_spawn(48.5, 52.25), _spawn(49.75, 53.0)),
            ),
        ),
        gameobjects=(
            PfQuestGameObject(32, "Sunken Chest", None, (_spawn(42.0, 61.5, 600),)),
        ),
    )


def _turtle_world() -> PfQuestWorldSlice:
    return PfQuestWorldSlice(
        zones=(PfQuestZone(12, "Elwynn Turtle"),),
        creatures=(
            PfQuestCreature(6, "Kobold Worker", 2, 3, "A", (_spawn(55.0, 56.0, 120),)),
            PfQuestCreature(7, "Overlay Scout", 4, 4, "A", (_spawn(40.0, 41.0, 60),)),
        ),
        gameobjects=(
            PfQuestGameObject(33, "Overlay Cache", "A", (_spawn(30.0, 31.0, 90),)),
        ),
    )


def _spawn_key(kind: str, entity_id: int, spawn: PfQuestSpawn) -> str:
    return (
        f"{kind}:{entity_id}:zone_percent:{spawn.zone_id}:"
        f"{spawn.x:.6f}:{spawn.y:.6f}"
    )


def _seed_scalar(
    connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    value,
    record_type: str,
) -> None:
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=record_type,
        raw_identifier=subject_key,
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
        selection_policy="first-observation",
        selection_reason="Test baseline equivalent to the P1-T01 default selection.",
    )


def _seed_base_import(connection, world: PfQuestWorldSlice) -> None:
    source = connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind)
        VALUES (?, 'pfQuest', 'lua-addon')
        """,
        (PFQUEST_SOURCE_KEY,),
    )
    batch = connection.execute(
        """
        INSERT INTO import_batches(
            source_id, source_revision, status, finished_at, rows_read, rows_accepted
        )
        VALUES (?, ?, 'succeeded', '2026-08-24T00:00:00Z', 3, 3)
        """,
        (int(source.lastrowid), _BASE_REVISION),
    )
    batch_id = int(batch.lastrowid)

    for zone in world.zones:
        _seed_scalar(
            connection,
            batch_id=batch_id,
            subject_kind="zone",
            subject_key=zone.zone_id,
            fact_key="name",
            value=zone.name,
            record_type="zone",
        )
        connection.execute(
            "INSERT INTO zones(zone_id, name) VALUES (?, ?)", (zone.zone_id, zone.name)
        )

    for creature in world.creatures:
        for fact_key, value in (
            ("name", creature.name),
            ("level_min", creature.level_min),
            ("level_max", creature.level_max),
            ("faction", creature.faction),
        ):
            _seed_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="creature",
                subject_key=creature.creature_id,
                fact_key=fact_key,
                value=value,
                record_type="unit",
            )
        connection.execute(
            """
            INSERT INTO creatures(creature_id, name, level_min, level_max, faction)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                creature.creature_id,
                creature.name,
                creature.level_min,
                creature.level_max,
                creature.faction,
            ),
        )
        for spawn in creature.spawns:
            key = _spawn_key("creature", creature.creature_id, spawn)
            _seed_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="creature_spawn",
                subject_key=key,
                fact_key="position",
                value={
                    "coordinate_space": "zone_percent",
                    "zone_id": spawn.zone_id,
                    "x": spawn.x,
                    "y": spawn.y,
                },
                record_type="unit_spawn",
            )
            connection.execute(
                """
                INSERT INTO creature_spawns(
                    spawn_key, creature_id, zone_id, coordinate_space, x, y, respawn_seconds
                ) VALUES (?, ?, ?, 'zone_percent', ?, ?, ?)
                """,
                (
                    key,
                    creature.creature_id,
                    spawn.zone_id,
                    spawn.x,
                    spawn.y,
                    spawn.respawn_seconds,
                ),
            )

    for gameobject in world.gameobjects:
        _seed_scalar(
            connection,
            batch_id=batch_id,
            subject_kind="gameobject",
            subject_key=gameobject.gameobject_id,
            fact_key="name",
            value=gameobject.name,
            record_type="object",
        )
        connection.execute(
            "INSERT INTO gameobjects(gameobject_id, name) VALUES (?, ?)",
            (gameobject.gameobject_id, gameobject.name),
        )
        for spawn in gameobject.spawns:
            key = _spawn_key("gameobject", gameobject.gameobject_id, spawn)
            _seed_scalar(
                connection,
                batch_id=batch_id,
                subject_kind="gameobject_spawn",
                subject_key=key,
                fact_key="position",
                value={
                    "coordinate_space": "zone_percent",
                    "zone_id": spawn.zone_id,
                    "x": spawn.x,
                    "y": spawn.y,
                },
                record_type="object_spawn",
            )
            connection.execute(
                """
                INSERT INTO gameobject_spawns(
                    spawn_key, gameobject_id, zone_id, coordinate_space, x, y,
                    respawn_seconds
                ) VALUES (?, ?, ?, 'zone_percent', ?, ?, ?)
                """,
                (
                    key,
                    gameobject.gameobject_id,
                    spawn.zone_id,
                    spawn.x,
                    spawn.y,
                    spawn.respawn_seconds,
                ),
            )


def test_turtle_reconcile_replaces_spawn_sets_and_preserves_old_evidence(tmp_path):
    base = _base_world()
    turtle = _turtle_world()

    with connect_database(tmp_path / "world.sqlite3") as connection:
        apply_migrations(connection)
        _seed_base_import(connection, base)
        old_creature_spawn_key = _spawn_key("creature", 6, base.creatures[0].spawns[0])
        old_object_spawn_key = _spawn_key("gameobject", 32, base.gameobjects[0].spawns[0])

        first = reconcile_pfquest_world_slices(
            connection,
            base_world=base,
            overlay_world=turtle,
            pfquest_revision=_BASE_REVISION,
            overlay_revision="turtle-r1",
            overlay_kind="turtle",
            overlay_source_path=Path("fixture/turtle"),
        )

        assert first.source_key == PFQUEST_TURTLE_SOURCE_KEY
        assert connection.execute(
            "SELECT name FROM zones WHERE zone_id = 12"
        ).fetchone()[0] == "Elwynn Turtle"
        assert connection.execute(
            "SELECT name, level_min, level_max, faction FROM creatures WHERE creature_id = 6"
        ).fetchone()[:] == ("Kobold Worker", 2, 3, "A")
        assert connection.execute(
            "SELECT COUNT(*) FROM creature_spawns WHERE creature_id = 6"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM gameobjects WHERE gameobject_id = 32"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM gameobject_spawns WHERE gameobject_id = 32"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM gameobjects WHERE gameobject_id = 33"
        ).fetchone()[0] == 1

        assert first.details["stale_creature_spawns_deleted"] == 2
        assert first.details["stale_gameobject_spawns_deleted"] == 1
        assert first.details["canonical_templates_deleted"] == 1

        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'creature_spawn'
              AND og.subject_key = ?
              AND og.fact_key = 'position'
              AND ds.source_key = ?
            """,
            (old_creature_spawn_key, PFQUEST_SOURCE_KEY),
        ).fetchone()[0] == 1
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'gameobject_spawn'
              AND og.subject_key = ?
              AND og.fact_key = 'position'
              AND ds.source_key = ?
            """,
            (old_object_spawn_key, PFQUEST_SOURCE_KEY),
        ).fetchone()[0] == 1

        spawn_set = connection.execute(
            """
            SELECT ds.source_key, cs.selection_policy
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            JOIN source_observations AS so ON so.id = cs.observation_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'creature'
              AND og.subject_key = '6'
              AND og.fact_key = ?
            """,
            (SPAWN_SET_FACT,),
        ).fetchone()
        assert spawn_set["source_key"] == PFQUEST_TURTLE_SOURCE_KEY
        assert spawn_set["selection_policy"] == TURTLE_SELECTION_POLICY

        second = reconcile_pfquest_world_slices(
            connection,
            base_world=base,
            overlay_world=turtle,
            pfquest_revision=_BASE_REVISION,
            overlay_revision="turtle-r1",
            overlay_kind="turtle",
            overlay_source_path=Path("fixture/turtle"),
        )
        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert second.details["stale_creature_spawns_deleted"] == 0
        assert second.details["stale_gameobject_spawns_deleted"] == 0
        assert second.details["canonical_templates_deleted"] == 0


def test_turtle_negative_presence_does_not_delete_externally_supported_template(tmp_path):
    base = _base_world()
    turtle_without_creature = PfQuestWorldSlice(
        zones=base.zones,
        creatures=(),
        gameobjects=base.gameobjects,
    )

    with connect_database(tmp_path / "protected.sqlite3") as connection:
        apply_migrations(connection)
        _seed_base_import(connection, base)

        external_source = connection.execute(
            """
            INSERT INTO data_sources(source_key, display_name, source_kind)
            VALUES ('authoritative-fixture', 'Authoritative Fixture', 'fixture')
            """
        )
        external_batch = connection.execute(
            """
            INSERT INTO import_batches(
                source_id, source_revision, status, finished_at, rows_read, rows_accepted
            ) VALUES (?, 'external-r1', 'succeeded', '2026-08-24T00:00:00Z', 1, 1)
            """,
            (int(external_source.lastrowid),),
        )
        observation_id = record_scalar_observation(
            connection,
            subject_kind="creature",
            subject_key=6,
            fact_key="name",
            import_batch_id=int(external_batch.lastrowid),
            value="Authoritative Kobold",
            source_record_type="fixture",
            raw_identifier=6,
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
            selection_policy="fixture-authority",
            selection_reason="Protect an explicitly selected non-pfQuest fact.",
        )
        connection.execute(
            "UPDATE creatures SET name = 'Authoritative Kobold' WHERE creature_id = 6"
        )

        external_spawn_key = "external:creature:6:spawn"
        external_position = record_scalar_observation(
            connection,
            subject_kind="creature_spawn",
            subject_key=external_spawn_key,
            fact_key="position",
            import_batch_id=int(external_batch.lastrowid),
            value={
                "coordinate_space": "zone_percent",
                "zone_id": 12,
                "x": 75.0,
                "y": 75.0,
            },
            source_record_type="fixture_spawn",
            raw_identifier="external-spawn",
        )
        external_spawn_group = int(
            connection.execute(
                "SELECT observation_group_id FROM source_observations WHERE id = ?",
                (external_position,),
            ).fetchone()[0]
        )
        select_canonical_observation(
            connection,
            observation_group_id=external_spawn_group,
            observation_id=external_position,
            selection_policy="fixture-authority",
            selection_reason="Protect a non-pfQuest spawn during managed-set cleanup.",
        )
        connection.execute(
            """
            INSERT INTO creature_spawns(
                spawn_key, creature_id, zone_id, coordinate_space, x, y
            ) VALUES (?, 6, 12, 'zone_percent', 75, 75)
            """,
            (external_spawn_key,),
        )

        summary = reconcile_pfquest_world_slices(
            connection,
            base_world=base,
            overlay_world=turtle_without_creature,
            pfquest_revision=_BASE_REVISION,
            overlay_revision="turtle-r2",
            overlay_kind="turtle",
            overlay_source_path=Path("fixture/turtle"),
        )

        assert connection.execute(
            "SELECT name FROM creatures WHERE creature_id = 6"
        ).fetchone()[0] == "Authoritative Kobold"
        assert connection.execute(
            "SELECT COUNT(*) FROM creature_spawns WHERE creature_id = 6"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM creature_spawns WHERE spawn_key = ?",
            (external_spawn_key,),
        ).fetchone()[0] == 1
        assert summary.details["stale_creature_spawns_deleted"] == 2
        assert summary.details["canonical_templates_deleted"] == 0

        presence = connection.execute(
            """
            SELECT ds.source_key, so.value_json
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            JOIN source_observations AS so ON so.id = cs.observation_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'creature'
              AND og.subject_key = '6'
              AND og.fact_key = ?
            """,
            (WORLD_PRESENCE_FACT,),
        ).fetchone()
        assert presence["source_key"] == PFQUEST_SOURCE_KEY
        assert presence["value_json"] == "true"
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'creature'
              AND og.subject_key = '6'
              AND og.fact_key = ?
              AND ds.source_key = ?
              AND so.value_json = 'false'
            """,
            (WORLD_PRESENCE_FACT, PFQUEST_TURTLE_SOURCE_KEY),
        ).fetchone()[0] == 1


def test_octo_overlay_is_recorded_as_comparison_evidence_only(tmp_path):
    base = _base_world()
    octo = PfQuestWorldSlice(
        zones=(PfQuestZone(12, "Elwynn Octo"),),
        creatures=(PfQuestCreature(6, "Octo Kobold", 5, 5, "A", (_spawn(60.0, 60.0),)),),
        gameobjects=base.gameobjects,
    )

    with connect_database(tmp_path / "octo.sqlite3") as connection:
        apply_migrations(connection)
        _seed_base_import(connection, base)

        summary = reconcile_pfquest_world_slices(
            connection,
            base_world=base,
            overlay_world=octo,
            pfquest_revision=_BASE_REVISION,
            overlay_revision="octo-r1",
            overlay_kind="octo",
            overlay_source_path=Path("fixture/octo"),
        )

        assert summary.source_key == PFQUEST_OCTO_SOURCE_KEY
        assert summary.details["comparison_only"] is True
        assert summary.rows_inserted == 0
        assert summary.rows_updated == 0
        assert connection.execute(
            "SELECT name FROM creatures WHERE creature_id = 6"
        ).fetchone()[0] == "Kobold Vermin"
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind = 'creature'
              AND og.subject_key = '6'
              AND og.fact_key = 'name'
              AND ds.source_key = ?
            """,
            (PFQUEST_OCTO_SOURCE_KEY,),
        ).fetchone()[0] == 1


def test_content_revisions_are_deterministic_and_change_with_inputs(tmp_path):
    base = tmp_path / "pfquest"
    base_files = (
        "db/zones.lua",
        "db/enUS/zones.lua",
        "db/units.lua",
        "db/enUS/units.lua",
        "db/objects.lua",
        "db/enUS/objects.lua",
    )
    for index, relative in enumerate(base_files):
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture-{index}\n", encoding="utf-8")

    first = compute_pfquest_world_revision(base)
    assert compute_pfquest_world_revision(base) == first
    (base / "db/units.lua").write_text("changed\n", encoding="utf-8")
    assert compute_pfquest_world_revision(base) != first

    overlay = tmp_path / "turtle"
    path = overlay / "db/units-turtle.lua"
    path.parent.mkdir(parents=True)
    path.write_text("overlay\n", encoding="utf-8")
    overlay_first = compute_pfquest_overlay_revision(overlay)
    assert compute_pfquest_overlay_revision(overlay) == overlay_first
    (overlay / "overwrites.lua").write_text("-- changed\n", encoding="utf-8")
    assert compute_pfquest_overlay_revision(overlay) != overlay_first

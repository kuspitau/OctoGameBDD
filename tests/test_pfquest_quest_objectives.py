from __future__ import annotations

import shutil
from pathlib import Path

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.pfquest_quest_objectives import (
    OBJECTIVE_FACTS,
    OBJECTIVE_SUBTYPES,
    QUEST_SET_FACT,
    TURTLE_SELECTION_POLICY,
    compute_pfquest_quest_objectives_revision,
    compute_pfquest_turtle_quest_objectives_revision,
    parse_area_trigger,
    parse_item_use_targets,
    parse_quest_objectives,
    reconcile_pfquest_turtle_quest_objectives,
)
from octogamedb.importers.pfquest_quest_overlay_reconcile import (
    compute_pfquest_turtle_quests_revision,
    reconcile_pfquest_turtle_quests,
)
from octogamedb.importers.pfquest_quest_progression import (
    reconcile_pfquest_turtle_quest_progression,
)
from octogamedb.importers.pfquest_quests import (
    compute_pfquest_quests_revision,
    import_pfquest_quests,
)
from octogamedb.quest_objectives import quest_objectives_by_id
from octogamedb.quests import quest_by_id

ROOT = Path(__file__).parent / "fixtures"
BASE_FIXTURE = ROOT / "pfquest" / "quests_slice"
TURTLE_FIXTURE = ROOT / "pfquest_turtle" / "quests_slice"

BASE_DATA = '''pfDB["quests"]["data"] = {
  [100] = {
    ["lvl"] = 12,
    ["start"] = { ["U"] = { 10 } }, ["end"] = { ["O"] = { 20 } },
    ["obj"] = {
      ["U"] = { 10, 10 }, ["O"] = { 20 }, ["I"] = { 700 }, ["IR"] = { 701 },
      ["A"] = { 45 }, ["Z"] = { 85 },
    },
  },
  [101] = { ["lvl"] = 9, ["obj"] = { ["U"] = { 10 } } },
  [102] = { ["lvl"] = 11, ["start"] = { ["O"] = { 20 } } },
  [103] = {
    ["lvl"] = 8,
    ["obj"] = {
      ["U"] = { 999 }, ["I"] = { 7999 }, ["IR"] = { 702 },
      ["A"] = { 999 }, ["Z"] = { 9999 },
    },
  },
  [104] = { ["obj"] = {} },
}
'''

TURTLE_DATA = '''pfDB["quests"]["data-turtle"] = {
  [100] = {
    ["lvl"] = 20,
    ["start"] = { ["U"] = { 11 } }, ["end"] = { ["O"] = { 21 } },
    ["obj"] = {
      ["U"] = { 11 }, ["O"] = { 21 }, ["I"] = { 700 }, ["IR"] = { 701 },
      ["A"] = { 45, 60 }, ["Z"] = { 40 },
    },
  },
  [101] = "_",
  [102] = { ["lvl"] = 11, ["start"] = { ["O"] = { 20 } } },
}
'''

BASE_ITEMREQ = '''pfDB["quests-itemreq"]["data"] = {
  [701] = { [10] = "1234", [-20] = 0 },
}
'''

TURTLE_ITEMREQ = '''pfDB["quests-itemreq"]["data-turtle"] = {
  [701] = { [-21] = "555" },
}
'''

BASE_AREA = '''pfDB["areatrigger"]["data"] = {
  [45] = { ["coords"] = { [1] = { 84.8, 30.3, 85 } } },
}
'''

TURTLE_AREA = '''pfDB["areatrigger"]["data-turtle"] = {
  [45] = { ["coords"] = { [1] = { 25.0, 50.0, 40 } } },
  [60] = { ["coords"] = {} },
}
'''


def _copy_objective_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "pfquest"
    turtle = tmp_path / "pfquest-turtle"
    shutil.copytree(BASE_FIXTURE, base)
    shutil.copytree(TURTLE_FIXTURE, turtle)
    (base / "db" / "quests.lua").write_text(BASE_DATA, encoding="utf-8")
    (base / "db" / "quests-itemreq.lua").write_text(BASE_ITEMREQ, encoding="utf-8")
    (base / "db" / "areatrigger.lua").write_text(BASE_AREA, encoding="utf-8")
    (turtle / "db" / "quests-turtle.lua").write_text(TURTLE_DATA, encoding="utf-8")
    (turtle / "db" / "quests-itemreq-turtle.lua").write_text(
        TURTLE_ITEMREQ, encoding="utf-8"
    )
    (turtle / "db" / "areatrigger-turtle.lua").write_text(TURTLE_AREA, encoding="utf-8")

    data_xml = (turtle / "init" / "data-turtle.xml").read_text(encoding="utf-8")
    data_xml = data_xml.replace(
        "</Ui>",
        '<Include file="..\\db\\quests-itemreq-turtle.lua"/>'
        '<Include file="..\\db\\areatrigger-turtle.lua"/></Ui>',
    )
    (turtle / "init" / "data-turtle.xml").write_text(data_xml, encoding="utf-8")
    patchtable = (turtle / "patchtable.lua").read_text(encoding="utf-8")
    patchtable = patchtable.replace(
        'local dbs = { "quests" }',
        'local dbs = { "quests", "quests-itemreq", "areatrigger" }',
    )
    (turtle / "patchtable.lua").write_text(patchtable, encoding="utf-8")
    return base, turtle


def _seed_world(connection) -> None:
    connection.execute("INSERT INTO maps(map_id, name) VALUES (1, 'Azeroth')")
    for zone_id, name in ((40, "Westfall"), (85, "Tirisfal Glades")):
        connection.execute(
            "INSERT INTO zones(zone_id, map_id, name) VALUES (?, 1, ?)", (zone_id, name)
        )
    for creature_id in (10, 11):
        connection.execute(
            "INSERT INTO creatures(creature_id, name) VALUES (?, ?)",
            (creature_id, f"Creature {creature_id}"),
        )
    for gameobject_id in (20, 21):
        connection.execute(
            "INSERT INTO gameobjects(gameobject_id, name) VALUES (?, ?)",
            (gameobject_id, f"Object {gameobject_id}"),
        )
    for item_id in (700, 701):
        connection.execute(
            "INSERT INTO items(item_id, name) VALUES (?, ?)", (item_id, f"Item {item_id}")
        )
    connection.execute(
        """
        INSERT INTO creature_spawns(
            spawn_key, creature_id, zone_id, coordinate_space, x, y
        ) VALUES ('test:creature:10', 10, 85, 'zone_percent', 10.0, 20.0)
        """
    )
    connection.execute(
        """
        INSERT INTO gameobject_spawns(
            spawn_key, gameobject_id, zone_id, coordinate_space, x, y
        ) VALUES ('test:gameobject:20', 20, 85, 'zone_percent', 30.0, 40.0)
        """
    )
    connection.execute(
        """
        INSERT INTO gameobject_spawns(
            spawn_key, gameobject_id, zone_id, coordinate_space, x, y
        ) VALUES ('test:gameobject:21', 21, 40, 'zone_percent', 50.0, 60.0)
        """
    )


def _prepare(connection, base: Path, turtle: Path) -> None:
    apply_migrations(connection)
    _seed_world(connection)
    base_identity_revision = compute_pfquest_quests_revision(base)
    turtle_identity_revision = compute_pfquest_turtle_quests_revision(turtle)
    import_pfquest_quests(
        connection, source_root=base, source_revision=base_identity_revision
    )
    reconcile_pfquest_turtle_quests(
        connection,
        pfquest_root=base,
        pfquest_turtle_root=turtle,
        pfquest_revision=base_identity_revision,
        turtle_revision=turtle_identity_revision,
    )
    reconcile_pfquest_turtle_quest_progression(
        connection, pfquest_root=base, pfquest_turtle_root=turtle
    )


def test_source_parsers_preserve_objective_semantics():
    parsed = parse_quest_objectives(
        {"obj": {"U": {1: 10, 2: 10, 3: 11}, "IR": {}, "A": {1: 45}}},
        quest_id=100,
    )
    assert parsed.obj_present is True
    assert parsed.source_lists["O"] is None
    assert parsed.source_lists["IR"] == ()
    assert parsed.members["U"] == (10, 11)
    assert parsed.duplicates["U"] == (10,)

    item_use = parse_item_use_targets({-20: 0, 10: "1234"}, item_id=701)
    assert [(row.target_kind, row.target_id, row.spell_id) for row in item_use.targets] == [
        ("gameobject", 20, 0),
        ("creature", 10, 1234),
    ]

    empty_area = parse_area_trigger({"coords": {}}, area_trigger_id=60)
    assert empty_area.entry_present is True
    assert empty_area.coords_present is True
    assert empty_area.locations == ()


def test_objective_reconcile_is_queryable_geographic_and_idempotent(tmp_path):
    base, turtle = _copy_objective_fixtures(tmp_path)
    with connect_database(tmp_path / "objectives.sqlite3") as connection:
        _prepare(connection, base, turtle)
        first = reconcile_pfquest_turtle_quest_objectives(
            connection, pfquest_root=base, pfquest_turtle_root=turtle
        )
        second = reconcile_pfquest_turtle_quest_objectives(
            connection, pfquest_root=base, pfquest_turtle_root=turtle
        )

        assert first.status == "succeeded"
        assert first.details["changed_effective_objective_quest_ids"] == [100, 101]
        assert first.details["changed_effective_itemreq_ids"] == [701]
        assert first.details["changed_effective_area_trigger_ids"] == [45, 60]
        assert {
            (row["source_key"], row["quest_id"], row["subtype"], row["duplicate_target_id"])
            for row in first.details["duplicate_source_objective_members"]
        } == {("pfquest", 100, "U", 10)}

        unresolved = first.details["unresolved_objective_materialization"]
        assert any(
            row.get("quest_id") == 103
            and row.get("subtype") == "U"
            and row.get("reason") == "missing_creature_identity"
            for row in unresolved
        )
        assert any(
            row.get("quest_id") == 103
            and row.get("subtype") == "A"
            and row.get("reason") == "missing_area_trigger_identity"
            for row in unresolved
        )
        # Turtle deletes quest 101 from the data table but its inherited enUS title remains.
        # P3-T02 therefore keeps the quest identity while the effective data/objective view becomes
        # empty; a data-entry deletion must not be reinterpreted as missing quest identity.
        assert not any(
            row.get("quest_id") == 101 and row.get("reason") == "missing_quest_identity"
            for row in unresolved
        )
        deleted_data_view = quest_objectives_by_id(connection, 101)
        assert deleted_data_view is not None
        assert deleted_data_view["declared"] is False
        assert deleted_data_view["selected_member_count"] == 0
        assert deleted_data_view["objectives"] == []

        view = quest_objectives_by_id(connection, 100)
        assert view is not None
        full_quest = quest_by_id(connection, 100)
        assert full_quest is not None
        assert full_quest["objectives"] == view
        assert view["declared"] is True
        assert view["selected_member_count"] == 7
        assert view["is_complete"] is True
        assert view["provenance"]["selection_policy"] == TURTLE_SELECTION_POLICY
        by_kind = {
            (row["source_subtype"], row["target_id"]): row for row in view["objectives"]
        }

        creature = by_kind[("U", 11)]
        assert creature["resolved"] is True
        assert creature["geography_origin"] == "derived_from_creature_spawns"
        assert creature["geography_resolved"] is False
        assert creature["geography_unresolved_reason"] == "no_canonical_spawns"

        gameobject = by_kind[("O", 21)]
        assert gameobject["geography_resolved"] is True
        assert gameobject["locations"][0]["zone_id"] == 40

        area = by_kind[("A", 45)]
        assert area["geography_origin"] == "source_backed_area_trigger_coordinates"
        assert area["area_trigger"]["locations"][0]["zone_id"] == 40
        assert area["area_trigger"]["locations"][0]["x"] == 25.0

        empty_area = by_kind[("A", 60)]
        assert empty_area["area_trigger"]["coords_present"] is True
        assert empty_area["area_trigger"]["selected_location_count"] == 0
        assert empty_area["area_trigger"]["is_complete"] is True

        zone = by_kind[("Z", 40)]
        assert zone["zone"]["zone_id"] == 40
        assert zone["geography_origin"] == "direct_zone_objective_context"

        item_use = by_kind[("IR", 701)]["item_use_targets"]
        assert item_use["declared"] is True
        assert item_use["is_complete"] is True
        assert [(row["target_kind"], row["target_id"], row["spell_id"]) for row in item_use["targets"]] == [
            ("gameobject", 21, 555)
        ]
        assert item_use["targets"][0]["locations"][0]["zone_id"] == 40

        empty_view = quest_objectives_by_id(connection, 104)
        assert empty_view is not None
        assert empty_view["declared"] is True
        assert empty_view["selected_member_count"] == 0
        assert all(empty_view["source_lists"][subtype] is None for subtype in OBJECTIVE_SUBTYPES)

        absent_view = quest_objectives_by_id(connection, 102)
        assert absent_view is not None
        assert absent_view["declared"] is False

        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert second.details["canonical_objective_rows_deleted"] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def _create_curated_batch(connection) -> int:
    source_id = connection.execute(
        "INSERT INTO data_sources(source_key, display_name, source_kind) "
        "VALUES ('curated-p3t04', 'Curated', 'test')"
    ).lastrowid
    return connection.execute(
        """
        INSERT INTO import_batches(source_id, source_revision, status, importer_version, rows_read)
        VALUES (?, 'curated-v1', 'running', 'test/1', 2)
        """,
        (source_id,),
    ).lastrowid


def test_custom_complete_set_and_primitive_selection_are_preserved(tmp_path):
    base, turtle = _copy_objective_fixtures(tmp_path)
    with connect_database(tmp_path / "protected.sqlite3") as connection:
        _prepare(connection, base, turtle)
        reconcile_pfquest_turtle_quest_objectives(
            connection, pfquest_root=base, pfquest_turtle_root=turtle
        )
        batch_id = _create_curated_batch(connection)

        subtypes = {subtype: None for subtype in OBJECTIVE_SUBTYPES}
        subtypes["U"] = [10]
        set_observation = record_scalar_observation(
            connection,
            subject_kind="quest",
            subject_key=100,
            fact_key=QUEST_SET_FACT,
            import_batch_id=batch_id,
            value={
                "obj_present": True,
                "subtype_presence": {subtype: subtype == "U" for subtype in OBJECTIVE_SUBTYPES},
                "subtypes": subtypes,
            },
            source_record_type="curated",
            raw_identifier="100:obj",
        )
        set_group = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id = ?",
            (set_observation,),
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=set_group,
            observation_id=set_observation,
            selection_policy="manual-test",
            selection_reason="Protect curated objective set.",
        )

        fact_key = OBJECTIVE_FACTS["U"][0]
        relation_observation = record_relation_observation(
            connection,
            subject_kind="quest",
            subject_key=100,
            fact_key=fact_key,
            import_batch_id=batch_id,
            target_kind="creature",
            target_key=10,
            relation_instance_key="10",
            attributes={"source_subtype": "U"},
            source_record_type="curated",
            raw_identifier="100:obj:U:10",
        )
        relation_group = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id = ?",
            (relation_observation,),
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=relation_group,
            observation_id=relation_observation,
            selection_policy="manual-test",
            selection_reason="Protect curated objective member.",
        )

        reconcile_pfquest_turtle_quest_objectives(
            connection, pfquest_root=base, pfquest_turtle_root=turtle
        )
        view = quest_objectives_by_id(connection, 100)
        assert view is not None
        full_quest = quest_by_id(connection, 100)
        assert full_quest is not None
        assert full_quest["objectives"] == view
        assert [(row["source_subtype"], row["target_id"]) for row in view["objectives"]] == [
            ("U", 10)
        ]
        assert view["provenance"]["selection_policy"] == "manual-test"
        assert view["objectives"][0]["provenance"]["selection_policy"] == "manual-test"


def test_objective_revisions_are_content_derived(tmp_path):
    base, turtle = _copy_objective_fixtures(tmp_path)
    base_revision = compute_pfquest_quest_objectives_revision(base)
    turtle_revision = compute_pfquest_turtle_quest_objectives_revision(turtle)
    assert base_revision.startswith("sha256:")
    assert turtle_revision.startswith("sha256:")

    itemreq = base / "db" / "quests-itemreq.lua"
    itemreq.write_text(itemreq.read_text(encoding="utf-8") + "\n-- revision marker\n", encoding="utf-8")
    assert compute_pfquest_quest_objectives_revision(base) != base_revision

    area = turtle / "db" / "areatrigger-turtle.lua"
    area.write_text(area.read_text(encoding="utf-8") + "\n-- revision marker\n", encoding="utf-8")
    assert compute_pfquest_turtle_quest_objectives_revision(turtle) != turtle_revision

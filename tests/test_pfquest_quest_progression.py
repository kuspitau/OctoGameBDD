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
from octogamedb.importers.pfquest_quest_overlay_reconcile import (
    compute_pfquest_turtle_quests_revision,
    reconcile_pfquest_turtle_quests,
)
from octogamedb.importers.pfquest_quest_progression import (
    PREREQUISITE_RELATION_FACT,
    PREREQUISITE_SET_FACT,
    QUEST_LEVEL_FACT,
    TURTLE_SELECTION_POLICY,
    compute_pfquest_quest_progression_revision,
    compute_pfquest_turtle_quest_progression_revision,
    parse_quest_progression,
    reconcile_pfquest_turtle_quest_progression,
)
from octogamedb.importers.pfquest_quests import (
    compute_pfquest_quests_revision,
    import_pfquest_quests,
)
from octogamedb.quests import quest_by_id

ROOT = Path(__file__).parent / "fixtures"
BASE_FIXTURE = ROOT / "pfquest" / "quests_slice"
TURTLE_FIXTURE = ROOT / "pfquest_turtle" / "quests_slice"

BASE_DATA = '''pfDB["quests"]["data"] = {
  [100] = {
    ["lvl"] = 12, ["min"] = 8, ["race"] = 178, ["class"] = 64,
    ["pre"] = { 102 }, ["close"] = { 100, 103 },
    ["start"] = { ["U"] = { 10, 11 }, ["O"] = { 20 } },
    ["end"] = { ["U"] = { 12 }, ["O"] = { 21 } },
  },
  [101] = { ["lvl"] = 9, ["end"] = { ["U"] = { 12 } } },
  [102] = { ["lvl"] = 11, ["pre"] = { 103 }, ["start"] = { ["O"] = { 20 } } },
  [103] = { ["lvl"] = 8, ["close"] = { 100, 103 }, ["start"] = { ["U"] = { 999 } } },
  [104] = { ["start"] = { ["I"] = { 700 } } },
  [106] = { ["lvl"] = 30, ["pre"] = { 100 }, ["start"] = { ["U"] = { 10 } } },
}
'''

TURTLE_DATA = '''pfDB["quests"]["data-turtle"] = {
  [100] = {
    ["lvl"] = 20, ["min"] = 15, ["race"] = 178, ["class"] = 64,
    ["pre"] = { 102, 102, 999 }, ["close"] = { 100, 103 },
    ["start"] = { ["U"] = { 10 } }, ["end"] = { ["O"] = { 21 } },
  },
  [101] = "_",
  [102] = { ["lvl"] = 21, ["pre"] = { 100 }, ["start"] = { ["O"] = { 20 } } },
  [104] = { ["pre"] = {}, ["start"] = { ["I"] = { 700 } } },
  [107] = { ["lvl"] = 40, ["min"] = 35, ["pre"] = { 100 }, ["start"] = { ["U"] = { 10 } } },
  [108] = { ["pre"] = { 999 }, ["start"] = { ["U"] = { 999 } } },
}
'''


def _copy_progression_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "pfquest"
    turtle = tmp_path / "pfquest-turtle"
    shutil.copytree(BASE_FIXTURE, base)
    shutil.copytree(TURTLE_FIXTURE, turtle)
    (base / "db" / "quests.lua").write_text(BASE_DATA, encoding="utf-8")
    (turtle / "db" / "quests-turtle.lua").write_text(TURTLE_DATA, encoding="utf-8")
    return base, turtle


def _seed_world(connection) -> None:
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


def _prepare(connection, base: Path, turtle: Path) -> tuple[str, str]:
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
    return base_identity_revision, turtle_identity_revision


def test_parse_preserves_source_lists_and_normalizes_sets():
    progression = parse_quest_progression(
        {
            "lvl": 20,
            "min": 15,
            "race": 178,
            "class": 64,
            "pre": {1: 7, 2: 7, 3: 8},
            "close": {1: 100, 2: 103},
        },
        quest_id=100,
    )
    assert progression.quest_level == 20
    assert progression.minimum_level == 15
    assert progression.race_mask == 178
    assert progression.class_mask == 64
    assert progression.prerequisite_source_ids == (7, 7, 8)
    assert progression.prerequisite_ids == (7, 8)
    assert progression.duplicate_prerequisite_ids == (7,)
    assert progression.close_source_ids == (100, 103)
    assert progression.close_member_ids == (100, 103)


def test_progression_reconcile_is_idempotent_and_queryable(tmp_path):
    base, turtle = _copy_progression_fixtures(tmp_path)
    with connect_database(tmp_path / "progression.sqlite3") as connection:
        _prepare(connection, base, turtle)
        first = reconcile_pfquest_turtle_quest_progression(
            connection, pfquest_root=base, pfquest_turtle_root=turtle
        )
        second = reconcile_pfquest_turtle_quest_progression(
            connection, pfquest_root=base, pfquest_turtle_root=turtle
        )

        assert first.status == "succeeded"
        assert first.details["changed_effective_progression_ids"] == [100, 101, 102, 104, 107, 108]
        assert first.details["duplicate_source_members"] == [
            {
                "source_key": "pfquest-turtle",
                "quest_id": 100,
                "field": "pre",
                "duplicate_quest_id": 102,
            }
        ]
        assert {
            (row["quest_id"], row["relation"], row["target_quest_id"], row["reason"])
            for row in first.details["unresolved_progression_relations"]
        } == {
            (100, "prerequisite", 999, "missing_quest_identity"),
            (108, "prerequisite", 999, "missing_quest_identity"),
        }
        assert first.details["self_prerequisite_ids"] == []
        assert first.details["prerequisite_cycles"] == [[100, 102]]
        assert first.details["close_self_missing_ids"] == []
        assert [100, 103] == first.details["close_self_member_ids"]
        assert first.details["close_group_mismatch_pairs"] == []

        result = quest_by_id(connection, 100)
        assert result is not None
        assert result["progression"]["quest_level"] == 20
        assert result["progression"]["minimum_level"] == 15
        assert result["progression"]["race_mask"] == 178
        assert result["progression"]["class_mask"] == 64
        pre = result["progression"]["prerequisite_set"]
        assert pre["semantics"] == "any_of"
        assert pre["selected_member_count"] == 2
        assert pre["materialized_member_count"] == 1
        assert pre["is_complete"] is False
        assert [row["quest_id"] for row in pre["members"]] == [102]
        assert [row["quest_id"] for row in result["progression"]["follow_ups"]] == [102, 106, 107]
        close_set = result["progression"]["close_set"]
        assert close_set["semantics"] == "exclusive_group_member_set"
        assert close_set["selected_member_count"] == 2
        assert close_set["is_complete"] is True
        assert [row["quest_id"] for row in close_set["members"]] == [100, 103]
        provenance = result["progression"]["provenance"]
        assert provenance["quest_level"]["source_key"] == "pfquest-turtle"
        assert provenance["prerequisite_set"]["selection_policy"] == TURTLE_SELECTION_POLICY
        assert [
            row["selection"]["source_key"] for row in provenance["prerequisite_members"]
        ] == ["pfquest-turtle"]

        selected_policy = connection.execute(
            """
            SELECT cs.selection_policy
            FROM observation_groups og
            JOIN canonical_selections cs ON cs.observation_group_id = og.id
            WHERE og.subject_kind='quest' AND og.subject_key='100' AND og.fact_key=?
            """,
            (PREREQUISITE_SET_FACT,),
        ).fetchone()[0]
        assert selected_policy == TURTLE_SELECTION_POLICY

        # Presence is source-shaped: an explicit empty pre={} is distinct from an absent pre field.
        # pfQuest runtime treats a declared pre list as an any-of condition, so an empty declared set
        # must remain inspectable rather than being collapsed into "no pre field".
        result_104 = quest_by_id(connection, 104)
        assert result_104 is not None
        assert result_104["progression"]["quest_level"] is None
        assert result_104["progression"]["prerequisite_set"]["declared"] is True
        assert result_104["progression"]["prerequisite_set"]["members"] == []

        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert second.details["canonical_progression_rows_deleted"] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def _create_curated_batch(connection) -> int:
    source_id = connection.execute(
        "INSERT INTO data_sources(source_key, display_name, source_kind) VALUES ('curated-p3t03','Curated','test')"
    ).lastrowid
    return connection.execute(
        """
        INSERT INTO import_batches(source_id,source_revision,status,importer_version,rows_read)
        VALUES (?, 'curated-v1', 'running', 'test/1', 2)
        """,
        (source_id,),
    ).lastrowid


def test_custom_scalar_and_prerequisite_selection_is_preserved(tmp_path):
    base, turtle = _copy_progression_fixtures(tmp_path)
    with connect_database(tmp_path / "protected.sqlite3") as connection:
        _prepare(connection, base, turtle)
        reconcile_pfquest_turtle_quest_progression(
            connection, pfquest_root=base, pfquest_turtle_root=turtle
        )
        batch_id = _create_curated_batch(connection)

        level_observation = record_scalar_observation(
            connection,
            subject_kind="quest",
            subject_key=100,
            fact_key=QUEST_LEVEL_FACT,
            import_batch_id=batch_id,
            value=99,
            source_record_type="curated",
            raw_identifier="100:quest_level",
        )
        level_group = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id=?", (level_observation,)
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=level_group,
            observation_id=level_observation,
            selection_policy="manual-test",
            selection_reason="Protect curated quest level.",
        )

        set_observation = record_scalar_observation(
            connection,
            subject_kind="quest",
            subject_key=100,
            fact_key=PREREQUISITE_SET_FACT,
            import_batch_id=batch_id,
            value=[103],
            source_record_type="curated",
            raw_identifier="100:pre:set",
        )
        set_group = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id=?", (set_observation,)
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=set_group,
            observation_id=set_observation,
            selection_policy="manual-test",
            selection_reason="Protect curated prerequisite set.",
        )
        relation_observation = record_relation_observation(
            connection,
            subject_kind="quest",
            subject_key=100,
            fact_key=PREREQUISITE_RELATION_FACT,
            import_batch_id=batch_id,
            target_kind="quest",
            target_key=103,
            relation_instance_key="103",
            attributes={"requirement_mode": "any_of"},
            source_record_type="curated",
            raw_identifier="100:prerequisite:103",
        )
        relation_group = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id=?",
            (relation_observation,),
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=relation_group,
            observation_id=relation_observation,
            selection_policy="manual-test",
            selection_reason="Protect curated prerequisite member.",
        )

        summary = reconcile_pfquest_turtle_quest_progression(
            connection, pfquest_root=base, pfquest_turtle_root=turtle
        )
        result = quest_by_id(connection, 100)
        assert result is not None
        assert result["progression"]["quest_level"] == 99
        assert [
            member["quest_id"]
            for member in result["progression"]["prerequisite_set"]["members"]
        ] == [103]
        assert summary.details["protected_canonical_rows_retained"] == 3


def test_progression_revisions_are_content_derived(tmp_path):
    base, turtle = _copy_progression_fixtures(tmp_path)
    base_revision = compute_pfquest_quest_progression_revision(base)
    turtle_revision = compute_pfquest_turtle_quest_progression_revision(turtle)
    assert base_revision.startswith("sha256:")
    assert turtle_revision.startswith("sha256:")

    base_path = base / "db" / "quests.lua"
    base_path.write_text(base_path.read_text().replace('["lvl"] = 12', '["lvl"] = 13'))
    assert compute_pfquest_quest_progression_revision(base) != base_revision

    turtle_path = turtle / "overwrites.lua"
    turtle_path.write_text(turtle_path.read_text() + "\n-- progression revision marker\n")
    assert compute_pfquest_turtle_quest_progression_revision(turtle) != turtle_revision
